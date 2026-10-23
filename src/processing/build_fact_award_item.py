"""Construye la tabla relacional proceso-adjudicación-proveedor-ítem con Spark."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from scripts.setup_windows_hadoop import helper_home


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convierte releases OCDS JSONL.GZ en la tabla fact_award_item."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/fact_award_item"),
    )
    parser.add_argument("--years", nargs="+", required=True)
    parser.add_argument(
        "--master",
        default="local[*]",
        help="Spark master; use local[*] en ejecución local.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reemplaza explícitamente una salida existente.",
    )
    return parser.parse_args()


def input_paths(input_dir: Path, years: list[str]) -> list[str]:
    paths = [input_dir / f"{year}.jsonl.gz" for year in years]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Faltan archivos de entrada: {', '.join(missing)}")
    return [str(path) for path in paths]


def configure_windows_hadoop() -> Path | None:
    """Configure the project-local Windows helper before the JVM starts."""
    if os.name != "nt":
        return None

    home = Path(os.environ.get("HADOOP_HOME", helper_home()))
    binary_dir = home / "bin"
    required_files = ("winutils.exe", "hadoop.dll")
    missing = [filename for filename in required_files if not (binary_dir / filename).is_file()]
    if missing:
        message = (
            f"Faltan helpers de Hadoop para Windows: {', '.join(missing)}. "
            "Ejecute: python scripts/setup_windows_hadoop.py"
        )
        raise RuntimeError(message)

    os.environ["HADOOP_HOME"] = str(home)
    os.environ["PATH"] = f"{binary_dir}{os.pathsep}{os.environ['PATH']}"
    return home


def build_fact_award_item(releases: DataFrame) -> DataFrame:
    """Flatten OCDS releases to the declared analytical grain."""
    source_year = F.regexp_extract(F.input_file_name(), r"([12][0-9]{3})\.jsonl\.gz", 1)
    awards = (
        releases.withColumn("source_year", source_year)
        .withColumn("award", F.explode_outer("awards"))
        .where(F.col("award.id").isNotNull())
        .withColumn("supplier", F.explode_outer("award.suppliers"))
        .withColumn("item", F.explode_outer("award.items"))
    )

    return awards.select(
        F.col("source_year").cast("int").alias("source_year"),
        F.col("ocid").alias("process_ocid"),
        F.col("id").alias("release_id"),
        F.to_timestamp("date").alias("release_date"),
        F.to_timestamp("publishedDate").alias("published_date"),
        F.col("buyer.id").alias("entity_id"),
        F.col("buyer.name").alias("entity_name"),
        F.col("tender.procuringEntity.id").alias("procuring_entity_id"),
        F.col("tender.procuringEntity.name").alias("procuring_entity_name"),
        F.col("tender.id").alias("tender_id"),
        F.col("tender.title").alias("tender_title"),
        F.col("tender.description").alias("tender_description"),
        F.col("tender.mainProcurementCategory").alias("procurement_category"),
        F.col("tender.procurementMethod").alias("procurement_method"),
        F.col("tender.procurementMethodDetails").alias("procurement_method_details"),
        F.col("tender.numberOfTenderers").cast("int").alias("number_of_tenderers"),
        F.col("award.id").alias("award_id"),
        F.to_timestamp("award.date").alias("award_date"),
        F.col("award.value.amount").cast("decimal(20,2)").alias("award_amount"),
        F.col("award.value.currency").alias("award_currency"),
        F.col("supplier.id").alias("supplier_id"),
        F.col("supplier.name").alias("supplier_name"),
        F.col("item.id").alias("item_id"),
        F.col("item.description").alias("item_description"),
        F.col("item.classification.id").alias("item_classification_id"),
        F.col("item.classification.description").alias("item_classification_description"),
        F.col("item.totalValue.amount").cast("decimal(20,2)").alias("item_amount"),
        F.col("item.totalValue.currency").alias("item_currency"),
        F.col("item.quantity").cast("double").alias("item_quantity"),
        F.col("item.unit.name").alias("item_unit_name"),
    )


def run() -> None:
    args = parse_args()
    paths = input_paths(args.input_dir, args.years)
    output_dir = args.output_dir.resolve()
    hadoop_home = configure_windows_hadoop()

    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-build-fact-award-item")
        .master(args.master)
        .config("spark.sql.session.timeZone", "America/Lima")
        .config("spark.sql.shuffle.partitions", "8")
    )
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    spark = builder.getOrCreate()
    try:
        releases = spark.read.json(paths)
        fact = build_fact_award_item(releases).where(
            F.col("process_ocid").isNotNull() & F.col("supplier_id").isNotNull()
        )

        write_mode = "overwrite" if args.overwrite else "errorifexists"
        (
            fact.repartition("source_year")
            .write.mode(write_mode)
            .partitionBy("source_year")
            .parquet(str(output_dir))
        )

        summary = fact.agg(
            F.count("*").alias("rows"),
            F.countDistinct("process_ocid").alias("processes"),
            F.countDistinct("award_id").alias("awards"),
            F.countDistinct("supplier_id").alias("suppliers"),
            F.countDistinct("entity_id").alias("entities"),
            F.sum(F.col("item_id").isNull().cast("int")).alias("rows_without_award_item"),
        )
        summary.show(truncate=False)
        print(f"Tabla creada: {output_dir}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()

