"""Publica la unidad comprador×segmento×modalidad para la pregunta P1."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from src.processing.build_fact_award import configure_pyspark_python, missing_or_blank
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)
from src.quality.profile_fact_award_item import write_json_atomically

UNIT_KEYS = ("buyer_id", "department", "cubso_segment", "procurement_method_details")
NONCOMPETITIVE_DETAILS = frozenset(
    {
        "Contratación Directa",
        "Regímen Especial",
        "Contratación Internacional",
        "Convenio",
        "Adjudicación Abreviada",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument(
        "--awards-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/market_p1"))
    parser.add_argument("--start-award-year", type=int, default=2023)
    parser.add_argument("--end-award-year", type=int, default=2024)
    parser.add_argument("--master", default="local[*]", help="Spark master; use local[*] en local.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _median(column: str) -> F.Column:
    return F.expr(f"percentile_approx({column}, 0.5, 10000)")


def select_awards_in_window(
    awards: DataFrame, start_award_year: int, end_award_year: int
) -> DataFrame:
    """Restrict award events before they define either side of P1."""
    return awards.where(F.col("award_year").between(start_award_year, end_award_year))


def select_p1_processes(
    tenders: DataFrame,
    awards: DataFrame,
    tenderers: DataFrame,
    buyers: DataFrame,
    start_award_year: int,
    end_award_year: int,
) -> DataFrame:
    """Keep competitive processes with the fields needed by both sides of P1."""
    eligible_awards = select_awards_in_window(awards, start_award_year, end_award_year)
    award_processes = eligible_awards.select("process_ocid").dropDuplicates()
    distinct_participants = tenderers.groupBy("process_ocid").agg(
        F.count("*").cast("int").alias("distinct_reported_participants")
    )
    competitive = (
        (F.col("procurement_method") == "open")
        & (~F.col("procurement_method_details").isin(*NONCOMPETITIVE_DETAILS))
    )
    return (
        tenders.join(award_processes, "process_ocid", "inner")
        .join(distinct_participants, "process_ocid", "left")
        .join(buyers.select("buyer_id", "department"), "buyer_id", "left")
        .where(competitive)
        .where(F.col("cubso_segment").isNotNull())
        .where(F.col("tenderer_list_count") > 0)
        .where(~missing_or_blank("buyer_id"))
        .select(
            "process_ocid",
            "buyer_id",
            "department",
            "cubso_segment",
            "procurement_method_details",
            "tenderer_list_count",
            "number_of_tenderers",
            F.coalesce("distinct_reported_participants", F.lit(0)).alias(
                "distinct_reported_participants"
            ),
        )
    )


def build_buyer_segment_method(processes: DataFrame, awards: DataFrame) -> DataFrame:
    """Measure award concentration and participation on the same selected processes."""
    award_events = (
        awards.join(processes.select("process_ocid", *UNIT_KEYS), "process_ocid", "inner")
        .where(~missing_or_blank("supplier_id"))
        .select(*UNIT_KEYS, "process_ocid", "award_id", "supplier_id")
        .dropDuplicates()
    )
    supplier_counts = award_events.groupBy(*UNIT_KEYS, "supplier_id").agg(
        F.countDistinct(F.struct("process_ocid", "award_id"))
        .cast("long")
        .alias("supplier_award_count")
    )
    totals = supplier_counts.groupBy(*UNIT_KEYS).agg(
        F.sum("supplier_award_count").cast("long").alias("award_count"),
        F.count("*").cast("int").alias("distinct_suppliers"),
    )
    shares = supplier_counts.join(totals, list(UNIT_KEYS), "inner").withColumn(
        "supplier_share", F.col("supplier_award_count") / F.col("award_count")
    )
    ranking = Window.partitionBy(*UNIT_KEYS).orderBy(
        F.desc("supplier_award_count"), F.asc("supplier_id")
    )
    concentration = (
        shares.groupBy(*UNIT_KEYS)
        .agg(F.sum(F.pow("supplier_share", 2)).alias("hhi"))
        .join(
            shares.withColumn("_rank", F.row_number().over(ranking))
            .where(F.col("_rank") == 1)
            .select(
                *UNIT_KEYS,
                F.col("supplier_id").alias("top_supplier_id"),
                F.col("supplier_award_count").alias("top_supplier_award_count"),
                F.col("supplier_share").alias("top_supplier_share"),
            ),
            list(UNIT_KEYS),
            "inner",
        )
        .join(totals, list(UNIT_KEYS), "inner")
    )
    participation = processes.groupBy(*UNIT_KEYS).agg(
        F.countDistinct("process_ocid").cast("long").alias("process_count"),
        _median("tenderer_list_count").cast("double").alias("reported_participants_median"),
        _median("distinct_reported_participants")
        .cast("double")
        .alias("distinct_reported_participants_median"),
        _median("number_of_tenderers").cast("double").alias("number_of_tenderers_median"),
        F.sum(F.col("number_of_tenderers").isNotNull().cast("int"))
        .cast("long")
        .alias("processes_with_number_of_tenderers"),
    )
    return participation.join(concentration, list(UNIT_KEYS), "inner")


def _validate_inputs(participation: Path, awards: Path, output: Path, overwrite: bool) -> None:
    for path in (participation, awards):
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta una entrada publicada con _SUCCESS: {path}")
    for child in ("fact_tender", "fact_tenderer", "dim_buyer"):
        if not (participation / child / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta la tabla de participación completa: {child}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite para regenerar.")
    for target in (output, staging_dir(output), output.with_name(f"{output.name}.previous")):
        for source in (participation, awards):
            if target == source or target in source.parents or source in target.parents:
                raise ValueError(f"La salida se solapa con una entrada: {target}")


def run() -> None:
    args = parse_args()
    if args.start_award_year > args.end_award_year:
        raise ValueError("La ventana de adjudicación es inválida.")
    participation_dir, awards_dir, output = (
        args.participation_dir.resolve(),
        args.awards_dir.resolve(),
        args.output_dir.resolve(),
    )
    _validate_inputs(participation_dir, awards_dir, output, args.overwrite)
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-build-market-p1")
        .master(args.master)
        .config("spark.sql.session.timeZone", "America/Lima")
        .config("spark.sql.shuffle.partitions", "8")
    )
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    spark = builder.getOrCreate()
    try:
        if hadoop_home:
            native_loader = spark.sparkContext._jvm.org.apache.hadoop.util.NativeCodeLoader
            if not native_loader.isNativeCodeLoaded():
                raise RuntimeError(
                    "La JVM no cargó hadoop.dll; ejecute setup_windows_hadoop.py --check."
                )
        tenders = spark.read.parquet(str(participation_dir / "fact_tender"))
        tenderers = spark.read.parquet(str(participation_dir / "fact_tenderer"))
        buyers = spark.read.parquet(str(participation_dir / "dim_buyer"))
        awards = spark.read.parquet(str(awards_dir))
        selected = select_p1_processes(
            tenders, awards, tenderers, buyers, args.start_award_year, args.end_award_year
        )
        # La concentración debe usar exactamente la misma ventana que define
        # los procesos elegibles; un proceso puede tener adjudicaciones con
        # fechas de otros años en los releases de las fuentes 2023--2024.
        window_awards = select_awards_in_window(
            awards, args.start_award_year, args.end_award_year
        )
        metrics = build_buyer_segment_method(selected, window_awards)
        if metrics.groupBy(*UNIT_KEYS).count().where(F.col("count") > 1).limit(1).count():
            raise ValueError("buyer_segment_method no tiene grano único.")
        stage = staging_dir(output)
        shutil.rmtree(stage, ignore_errors=True)
        tables = {"p1_processes": selected, "buyer_segment_method": metrics}
        for name, frame in tables.items():
            frame.write.mode("overwrite").parquet(str(stage / name))
            if not (stage / name / "_SUCCESS").is_file():
                raise RuntimeError(f"La tabla {name} no dejó _SUCCESS.")
        written = {name: spark.read.parquet(str(stage / name)) for name in tables}
        metadata = {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "award_window": {"start_year": args.start_award_year, "end_year": args.end_award_year},
            "unit": list(UNIT_KEYS),
            "competitive_rule": {
                "procurement_method": "open",
                "excluded_details": sorted(NONCOMPETITIVE_DETAILS),
            },
            "participant_measure": "tenderer_list_count; participantes reportados",
            "concentration_measure": (
                "adjudicaciones con proveedor por unidad; HHI y cuota principal"
            ),
            "tables": {
                name: {"rows": written[name].count(), "columns": written[name].columns}
                for name in tables
            },
        }
        write_json_atomically(stage / "_metadata.json", metadata)
        (stage / "_SUCCESS").touch()
        publish_output(stage, output)
        print(f"P1 publicado: {output}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
