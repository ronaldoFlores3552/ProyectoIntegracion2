"""Publica perfiles de compradores para Fase 6 sin variables resultado de P1."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.features.build_market_p1 import NONCOMPETITIVE_DETAILS, select_awards_in_window
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
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/buyer_profiles"))
    parser.add_argument("--start-award-year", type=int, default=2023)
    parser.add_argument("--end-award-year", type=int, default=2024)
    parser.add_argument("--master", default="local[*]")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def build_profiles(tenders: DataFrame, awards: DataFrame) -> DataFrame:
    """Use volume, composition and diversity; never P1 concentration or participation."""
    processes = tenders.where(~missing_or_blank("buyer_id")).select(
        "process_ocid",
        "buyer_id",
        "procurement_method",
        "procurement_method_details",
        "cubso_segment",
    )
    process_metrics = processes.groupBy("buyer_id").agg(
        F.countDistinct("process_ocid").cast("long").alias("process_count"),
        F.sum(F.col("procurement_method_details").isin(*NONCOMPETITIVE_DETAILS).cast("long"))
        .cast("long")
        .alias("noncompetitive_process_count"),
        F.countDistinct("cubso_segment").cast("long").alias("distinct_cubso_segments"),
    )
    segments = (
        processes.where(F.col("cubso_segment").isNotNull())
        .groupBy("buyer_id", "cubso_segment")
        .count()
    )
    entropy = (
        segments.join(process_metrics.select("buyer_id", "process_count"), "buyer_id")
        .withColumn("share", F.col("count") / F.col("process_count"))
        .groupBy("buyer_id")
        .agg(F.sum(-F.col("share") * F.log(F.col("share"))).alias("cubso_entropy"))
    )
    events = (
        awards.join(processes.select("process_ocid", "buyer_id"), "process_ocid", "inner")
        .where(~missing_or_blank("supplier_id"))
        .select(
            "buyer_id",
            "supplier_id",
            "procurement_category",
            "award_currency",
            "award_amount_single_supplier",
        )
    )
    pen = events.where(
        (F.col("award_currency") == "PEN") & (F.col("award_amount_single_supplier") > 0)
    )
    totals = pen.groupBy("buyer_id").agg(
        F.sum(F.col("award_amount_single_supplier").cast("double")).alias("pen_amount_total")
    )
    categories = (
        pen.groupBy("buyer_id")
        .pivot("procurement_category", ["goods", "services", "works"])
        .sum("award_amount_single_supplier")
    )
    for category in ("goods", "services", "works"):
        categories = categories.withColumnRenamed(category, f"pen_{category}")
    suppliers = events.groupBy("buyer_id").agg(
        F.countDistinct("supplier_id").cast("long").alias("distinct_suppliers")
    )
    return (
        process_metrics.join(entropy, "buyer_id", "left")
        .join(totals, "buyer_id", "left")
        .join(categories, "buyer_id", "left")
        .join(suppliers, "buyer_id", "left")
        .fillna(0)
        .select(
            "buyer_id",
            "process_count",
            "noncompetitive_process_count",
            "distinct_cubso_segments",
            "cubso_entropy",
            "pen_amount_total",
            "distinct_suppliers",
            F.log1p("process_count").alias("log_process_count"),
            F.log1p("pen_amount_total").alias("log_pen_amount"),
            F.log1p("distinct_suppliers").alias("log_distinct_suppliers"),
            (F.col("noncompetitive_process_count") / F.col("process_count")).alias(
                "noncompetitive_fraction"
            ),
            *[
                (F.col(f"pen_{category}") / F.col("pen_amount_total")).alias(
                    f"amount_fraction_{category}"
                )
                for category in ("goods", "services", "works")
            ],
        )
    )


def run() -> None:
    args = parse_args()
    participation, awards_dir, output = (
        args.participation_dir.resolve(),
        args.awards_dir.resolve(),
        args.output_dir.resolve(),
    )
    for path in (participation, awards_dir):
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta _SUCCESS: {path}")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite.")
    hadoop = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-buyer-profiles")
        .master(args.master)
        .config("spark.sql.shuffle.partitions", "8")
    )
    if hadoop:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop / "bin"))
    spark = builder.getOrCreate()
    try:
        tenders = spark.read.parquet(str(participation / "fact_tender"))
        awards = select_awards_in_window(
            spark.read.parquet(str(awards_dir)), args.start_award_year, args.end_award_year
        )
        profiles = build_profiles(tenders, awards)
        if profiles.groupBy("buyer_id").count().where("count > 1").limit(1).count():
            raise ValueError("buyer_features no es único.")
        stage = staging_dir(output)
        shutil.rmtree(stage, ignore_errors=True)
        profiles.write.mode("overwrite").parquet(str(stage / "buyer_features"))
        written = spark.read.parquet(str(stage / "buyer_features"))
        write_json_atomically(
            stage / "_metadata.json",
            {
                "version": 1,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "window": [args.start_award_year, args.end_award_year],
                "excluded": ["HHI", "concentración", "participación"],
                "rows": written.count(),
                "columns": written.columns,
            },
        )
        (stage / "_SUCCESS").touch()
        publish_output(stage, output)
        print(f"Perfiles de compradores publicados: {output}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
