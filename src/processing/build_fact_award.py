"""Publica una tabla con una fila por adjudicación OCDS."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)

AWARD_KEY_COLUMNS = ("process_ocid", "award_id")
AWARD_COLUMNS = (
    "source_year",
    "process_ocid",
    "release_id",
    "release_date",
    "published_date",
    "entity_id",
    "entity_name",
    "procuring_entity_id",
    "procuring_entity_name",
    "tender_id",
    "tender_title",
    "tender_description",
    "procurement_category",
    "procurement_method",
    "procurement_method_details",
    "number_of_tenderers",
    "award_id",
    "award_date",
    "award_amount",
    "award_currency",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed/fact_award_item"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/fact_award"))
    parser.add_argument("--master", default="local[*]", help="Spark master; use local[*] en local.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reemplaza explícitamente una salida existente.",
    )
    return parser.parse_args()


def missing_or_blank(column: str) -> F.Column:
    return F.col(column).isNull() | (F.trim(F.col(column).cast("string")) == "")


def configure_pyspark_python() -> None:
    """Keep local Spark workers in the same virtual environment as the driver."""
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)


def award_level_conflicts(fact_award_item: DataFrame) -> DataFrame:
    """Find keys that have more than one distinct award-level representation."""
    return (
        fact_award_item.select(*AWARD_COLUMNS)
        .dropDuplicates()
        .groupBy(*AWARD_KEY_COLUMNS)
        .count()
        .where(F.col("count") > 1)
    )


def build_fact_award(fact_award_item: DataFrame) -> DataFrame:
    """Project the item-grain table to one unique, validated award-level row."""
    return fact_award_item.select(*AWARD_COLUMNS).dropDuplicates()


def _validate_input(fact_award_item: DataFrame) -> None:
    missing_key = fact_award_item.where(
        missing_or_blank("process_ocid") | missing_or_blank("award_id")
    ).limit(1)
    if missing_key.count():
        raise ValueError("fact_award_item contiene filas sin process_ocid o award_id.")

    conflicts = award_level_conflicts(fact_award_item).limit(5).collect()
    if conflicts:
        examples = ", ".join(
            f"({row['process_ocid']}, {row['award_id']})" for row in conflicts
        )
        raise ValueError(
            "Una adjudicación tiene atributos de nivel adjudicación conflictivos: "
            f"{examples}. Defina una regla de versión antes de publicar fact_award."
        )


def run() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not (input_dir / "_SUCCESS").is_file():
        raise FileNotFoundError(f"No existe una tabla publicada con _SUCCESS: {input_dir}")
    if output_dir.exists() and not args.overwrite:
        state = "completa" if (output_dir / "_SUCCESS").is_file() else "INCOMPLETA (sin _SUCCESS)"
        raise FileExistsError(
            f"La salida ya existe y está {state}: {output_dir}. Use --overwrite para regenerarla."
        )

    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-build-fact-award")
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
                    "La JVM no cargó hadoop.dll. Ejecute: "
                    "python scripts/setup_windows_hadoop.py --check"
                )

        fact_award_item = spark.read.parquet(str(input_dir)).cache()
        _validate_input(fact_award_item)
        fact_award = build_fact_award(fact_award_item)

        staging = staging_dir(output_dir)
        shutil.rmtree(staging, ignore_errors=True)
        (
            fact_award.repartition("source_year")
            .write.mode("overwrite")
            .partitionBy("source_year")
            .parquet(str(staging))
        )
        publish_output(staging, output_dir)

        summary = spark.read.parquet(str(output_dir)).agg(
            F.count("*").alias("awards"),
            F.countDistinct("process_ocid").alias("processes"),
            F.countDistinct("entity_id").alias("entities"),
            F.countDistinct("award_currency").alias("currencies"),
        )
        summary.show(truncate=False)
        print(f"Tabla creada: {output_dir}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
