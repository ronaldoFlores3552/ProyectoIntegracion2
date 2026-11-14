"""Publica los grafos base de P2 sin materializar pares fuera de Spark."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.features.build_market_p1 import select_awards_in_window
from src.processing.build_fact_award import configure_pyspark_python, missing_or_blank
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)
from src.quality.profile_fact_award_item import write_json_atomically


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument(
        "--awards-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/market_p2"))
    parser.add_argument("--start-award-year", type=int, default=2023)
    parser.add_argument("--end-award-year", type=int, default=2024)
    parser.add_argument("--min-recurrent-processes", type=int, default=5)
    parser.add_argument("--master", default="local[*]", help="Spark master; use local[*] en local.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def build_award_edges(tenders: DataFrame, awards: DataFrame) -> DataFrame:
    """Build buyer--awarded-supplier edges from unique award events."""
    process_buyers = tenders.select("process_ocid", "buyer_id").where(~missing_or_blank("buyer_id"))
    events = (
        awards.join(process_buyers, "process_ocid", "inner")
        .where(~missing_or_blank("supplier_id"))
        .select(
            "process_ocid",
            "award_id",
            "buyer_id",
            "supplier_id",
            "award_currency",
            "award_amount_single_supplier",
        )
        .dropDuplicates(["process_ocid", "award_id", "supplier_id"])
        .withColumn(
            "pen_amount",
            F.when(
                (F.col("award_currency") == "PEN") & (F.col("award_amount_single_supplier") > 0),
                F.col("award_amount_single_supplier").cast("decimal(24,2)"),
            ),
        )
    )
    return events.groupBy("buyer_id", "supplier_id").agg(
        F.countDistinct(F.struct("process_ocid", "award_id")).cast("long").alias("award_count"),
        F.countDistinct("process_ocid").cast("long").alias("process_count"),
        F.sum("pen_amount").cast("decimal(24,2)").alias("pen_amount_total"),
        F.sum(F.col("pen_amount").isNotNull().cast("int")).cast("long").alias("pen_award_count"),
    )


def build_participation_edges(tenderers: DataFrame) -> DataFrame:
    """Build buyer--reported-participant edges from process-level participation."""
    rows = tenderers.where(~missing_or_blank("buyer_id") & ~missing_or_blank("participant_id"))
    return rows.groupBy("buyer_id", "participant_id").agg(
        F.countDistinct("process_ocid").cast("long").alias("process_count")
    )


def build_coparticipation(
    tenderers: DataFrame, min_recurrent_processes: int
) -> tuple[DataFrame, DataFrame]:
    """Project recurrent reported participants with Newman-style process-size weights."""
    rows = (
        tenderers.where(~missing_or_blank("participant_id"))
        .select("process_ocid", "participant_id")
        .dropDuplicates()
    )
    recurrent = (
        rows.groupBy("participant_id")
        .agg(F.countDistinct("process_ocid").cast("long").alias("participant_process_count"))
        .where(F.col("participant_process_count") >= min_recurrent_processes)
    )
    retained = rows.join(recurrent.select("participant_id"), "participant_id", "inner")
    coverage = (
        rows.groupBy("process_ocid")
        .agg(F.count("*").cast("long").alias("reported_participant_count"))
        .join(
            retained.groupBy("process_ocid").agg(
                F.count("*").cast("long").alias("recurrent_participant_count")
            ),
            "process_ocid",
            "left",
        )
        .fillna({"recurrent_participant_count": 0})
        .withColumn("is_projectable", (F.col("recurrent_participant_count") >= 2).cast("boolean"))
    )
    projectable = retained.join(
        coverage.where(F.col("is_projectable")).select(
            "process_ocid", "recurrent_participant_count"
        ),
        "process_ocid",
        "inner",
    )
    left = projectable.select("process_ocid", F.col("participant_id").alias("participant_left"))
    right = projectable.select("process_ocid", F.col("participant_id").alias("participant_right"))
    pairs = (
        left.join(right, "process_ocid", "inner")
        .where(F.col("participant_left") < F.col("participant_right"))
        .join(
            coverage.select("process_ocid", "recurrent_participant_count"), "process_ocid", "inner"
        )
        .withColumn(
            "newman_process_weight",
            F.lit(1.0) / (F.col("recurrent_participant_count") - F.lit(1.0)),
        )
    )
    edges = pairs.groupBy("participant_left", "participant_right").agg(
        F.countDistinct("process_ocid").cast("long").alias("shared_process_count"),
        F.sum("newman_process_weight").cast("double").alias("newman_weight"),
    )
    return coverage, edges


def _validate_inputs(participation: Path, awards: Path, output: Path, overwrite: bool) -> None:
    for path in (participation, awards):
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta una entrada publicada con _SUCCESS: {path}")
    for child in ("fact_tender", "fact_tenderer"):
        if not (participation / child / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta la tabla de participación completa: {child}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite para regenerar.")
    for target in (output, staging_dir(output), output.with_name(f"{output.name}.previous")):
        for source in (participation, awards):
            if target == source or target in source.parents or source in target.parents:
                raise ValueError(f"La salida se solapa con una entrada: {target}")


def _assert_unique(frame: DataFrame, keys: list[str], name: str) -> None:
    if frame.groupBy(*keys).count().where(F.col("count") > 1).limit(1).count():
        raise ValueError(f"{name} no tiene grano único: {keys}")


def run() -> None:
    args = parse_args()
    if args.start_award_year > args.end_award_year:
        raise ValueError("La ventana de adjudicación es inválida.")
    if args.min_recurrent_processes < 2:
        raise ValueError("El umbral de recurrencia debe ser al menos 2 procesos.")
    participation_dir, awards_dir, output = (
        args.participation_dir.resolve(),
        args.awards_dir.resolve(),
        args.output_dir.resolve(),
    )
    _validate_inputs(participation_dir, awards_dir, output, args.overwrite)
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-build-market-p2")
        .master(args.master)
        .config("spark.sql.session.timeZone", "America/Lima")
        .config("spark.sql.shuffle.partitions", "16")
    )
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    spark = builder.getOrCreate()
    try:
        if hadoop_home:
            loader = spark.sparkContext._jvm.org.apache.hadoop.util.NativeCodeLoader
            if not loader.isNativeCodeLoaded():
                raise RuntimeError(
                    "La JVM no cargó hadoop.dll; ejecute setup_windows_hadoop.py --check."
                )
        tenders = spark.read.parquet(str(participation_dir / "fact_tender"))
        tenderers = spark.read.parquet(str(participation_dir / "fact_tenderer"))
        awards = select_awards_in_window(
            spark.read.parquet(str(awards_dir)), args.start_award_year, args.end_award_year
        )
        award_edges = build_award_edges(tenders, awards)
        participation_edges = build_participation_edges(tenderers)
        process_coverage, coparticipation_edges = build_coparticipation(
            tenderers, args.min_recurrent_processes
        )
        _assert_unique(award_edges, ["buyer_id", "supplier_id"], "graph_award_edges")
        _assert_unique(
            participation_edges, ["buyer_id", "participant_id"], "graph_participation_edges"
        )
        _assert_unique(
            coparticipation_edges,
            ["participant_left", "participant_right"],
            "coparticipation_edges",
        )
        if (
            coparticipation_edges.where(F.col("participant_left") >= F.col("participant_right"))
            .limit(1)
            .count()
        ):
            raise ValueError("coparticipation_edges contiene autoaristas o pares sin ordenar.")
        stage = staging_dir(output)
        shutil.rmtree(stage, ignore_errors=True)
        tables = {
            "graph_award_edges": award_edges,
            "graph_participation_edges": participation_edges,
            "coparticipation_process_coverage": process_coverage,
            "coparticipation_edges": coparticipation_edges,
        }
        for name, frame in tables.items():
            frame.write.mode("overwrite").parquet(str(stage / name))
            if not (stage / name / "_SUCCESS").is_file():
                raise RuntimeError(f"La tabla {name} no dejó _SUCCESS.")
        written = {name: spark.read.parquet(str(stage / name)) for name in tables}
        metadata = {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "award_window": {"start_year": args.start_award_year, "end_year": args.end_award_year},
            "recurrent_participant_rule": {
                "minimum_processes": args.min_recurrent_processes,
                "universe": "fact_tenderer; participantes reportados",
            },
            "coparticipation_weight": (
                "Para cada proceso con k participantes recurrentes, cada par único recibe 1/(k-1)."
            ),
            "tables": {
                name: {"rows": written[name].count(), "columns": written[name].columns}
                for name in tables
            },
            "coverage": {
                "all_processes": written["coparticipation_process_coverage"].count(),
                "projectable_processes": written["coparticipation_process_coverage"]
                .where(F.col("is_projectable"))
                .count(),
                "recurrent_participants": tenderers.select("participant_id")
                .where(~missing_or_blank("participant_id"))
                .groupBy("participant_id")
                .count()
                .where(F.col("count") >= args.min_recurrent_processes)
                .count(),
            },
        }
        write_json_atomically(stage / "_metadata.json", metadata)
        (stage / "_SUCCESS").touch()
        publish_output(stage, output)
        print(f"P2 base publicado: {output}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
