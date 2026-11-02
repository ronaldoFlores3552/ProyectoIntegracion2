"""Publica una tabla con una fila por adjudicación-proveedor OCDS."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.processing.build_fact_award import (
    AWARD_KEY_COLUMNS,
    configure_pyspark_python,
    missing_or_blank,
)
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)

SUPPLIER_KEY_COLUMNS = (*AWARD_KEY_COLUMNS, "supplier_id")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--awards-dir", type=Path, default=Path("data/processed/fact_award"))
    parser.add_argument(
        "--award-items-dir",
        type=Path,
        default=Path("data/processed/fact_award_item"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/fact_award_supplier"),
    )
    parser.add_argument("--master", default="local[*]", help="Spark master; use local[*] en local.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reemplaza explícitamente una salida existente.",
    )
    return parser.parse_args()


def supplier_name_conflicts(fact_award_item: DataFrame) -> DataFrame:
    """Find supplier IDs with incompatible non-empty names inside one award."""
    normalized_name = F.trim(F.col("supplier_name"))
    return (
        fact_award_item.where(~missing_or_blank("supplier_id"))
        .where(~missing_or_blank("supplier_name"))
        .select(*SUPPLIER_KEY_COLUMNS, normalized_name.alias("supplier_name_normalized"))
        .dropDuplicates()
        .groupBy(*SUPPLIER_KEY_COLUMNS)
        .count()
        .where(F.col("count") > 1)
    )


def supplier_pairs(fact_award_item: DataFrame) -> DataFrame:
    """Return one stable supplier row per award, preserving a known name when present."""
    normalized_name = F.when(
        missing_or_blank("supplier_name"), F.lit(None).cast("string")
    ).otherwise(F.trim(F.col("supplier_name")))
    return (
        fact_award_item.where(~missing_or_blank("supplier_id"))
        .select(*SUPPLIER_KEY_COLUMNS, normalized_name.alias("supplier_name"))
        .groupBy(*SUPPLIER_KEY_COLUMNS)
        .agg(F.first("supplier_name", ignorenulls=True).alias("supplier_name"))
    )


def build_fact_award_supplier(fact_award: DataFrame, fact_award_item: DataFrame) -> DataFrame:
    """Join award-level facts with suppliers without allocating multi-supplier amounts."""
    pairs = supplier_pairs(fact_award_item)
    supplier_counts = pairs.groupBy(*AWARD_KEY_COLUMNS).agg(
        F.count("*").cast("int").alias("supplier_count_per_award")
    )
    awards = fact_award.select(
        "source_year",
        *AWARD_KEY_COLUMNS,
        "release_id",
        "entity_id",
        "entity_name",
        "tender_id",
        "procurement_category",
        "procurement_method",
        "award_date",
        F.year("award_date").alias("award_year"),
        F.col("award_amount").alias("award_amount_total"),
        "award_currency",
    )
    return (
        awards.join(pairs, list(AWARD_KEY_COLUMNS), "inner")
        .join(supplier_counts, list(AWARD_KEY_COLUMNS), "inner")
        .withColumn(
            "award_amount_single_supplier",
            F.when(F.col("supplier_count_per_award") == 1, F.col("award_amount_total")).otherwise(
                F.lit(None).cast("decimal(20,2)")
            ),
        )
        .select(
            "source_year",
            *AWARD_KEY_COLUMNS,
            "release_id",
            "entity_id",
            "entity_name",
            "tender_id",
            "procurement_category",
            "procurement_method",
            "award_date",
            "award_year",
            "supplier_id",
            "supplier_name",
            "supplier_count_per_award",
            "award_amount_total",
            "award_amount_single_supplier",
            "award_currency",
        )
    )


def _examples(frame: DataFrame, columns: tuple[str, ...]) -> str:
    rows = frame.select(*columns).limit(5).collect()
    return ", ".join(str(tuple(row[column] for column in columns)) for row in rows)


def _validate_input(fact_award: DataFrame, fact_award_item: DataFrame) -> None:
    missing_award_keys = fact_award.where(
        missing_or_blank("process_ocid") | missing_or_blank("award_id")
    )
    if missing_award_keys.limit(1).count():
        raise ValueError("fact_award contiene filas sin process_ocid o award_id.")

    duplicated_award_keys = fact_award.groupBy(*AWARD_KEY_COLUMNS).count().where(F.col("count") > 1)
    if duplicated_award_keys.limit(1).count():
        raise ValueError(
            "fact_award contiene adjudicaciones repetidas: "
            f"{_examples(duplicated_award_keys, AWARD_KEY_COLUMNS)}"
        )

    conflicts = supplier_name_conflicts(fact_award_item)
    if conflicts.limit(1).count():
        raise ValueError(
            "Un proveedor tiene nombres incompatibles dentro de una adjudicación: "
            f"{_examples(conflicts, SUPPLIER_KEY_COLUMNS)}"
        )

    pairs = supplier_pairs(fact_award_item).select(*AWARD_KEY_COLUMNS).dropDuplicates()
    awards = fact_award.select(*AWARD_KEY_COLUMNS)
    missing_suppliers = awards.join(pairs, list(AWARD_KEY_COLUMNS), "left_anti")
    if missing_suppliers.limit(1).count():
        raise ValueError(
            "Hay adjudicaciones sin proveedor en fact_award_item: "
            f"{_examples(missing_suppliers, AWARD_KEY_COLUMNS)}"
        )

    orphan_suppliers = pairs.join(awards, list(AWARD_KEY_COLUMNS), "left_anti")
    if orphan_suppliers.limit(1).count():
        raise ValueError(
            "Hay proveedores sin adjudicación correspondiente en fact_award: "
            f"{_examples(orphan_suppliers, AWARD_KEY_COLUMNS)}"
        )


def run() -> None:
    args = parse_args()
    awards_dir = args.awards_dir.resolve()
    award_items_dir = args.award_items_dir.resolve()
    output_dir = args.output_dir.resolve()
    for path in (awards_dir, award_items_dir):
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"No existe una tabla publicada con _SUCCESS: {path}")
    if output_dir.exists() and not args.overwrite:
        state = "completa" if (output_dir / "_SUCCESS").is_file() else "INCOMPLETA (sin _SUCCESS)"
        raise FileExistsError(
            f"La salida ya existe y está {state}: {output_dir}. Use --overwrite para regenerarla."
        )

    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-build-fact-award-supplier")
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

        fact_award = spark.read.parquet(str(awards_dir)).cache()
        fact_award_item = spark.read.parquet(str(award_items_dir)).cache()
        _validate_input(fact_award, fact_award_item)
        fact_award_supplier = build_fact_award_supplier(fact_award, fact_award_item)

        staging = staging_dir(output_dir)
        shutil.rmtree(staging, ignore_errors=True)
        (
            fact_award_supplier.repartition("source_year")
            .write.mode("overwrite")
            .partitionBy("source_year")
            .parquet(str(staging))
        )
        publish_output(staging, output_dir)

        summary = spark.read.parquet(str(output_dir)).agg(
            F.count("*").alias("award_supplier_rows"),
            F.countDistinct(F.struct(*AWARD_KEY_COLUMNS)).alias("distinct_awards"),
            F.countDistinct("supplier_id").alias("suppliers"),
            F.sum((F.col("supplier_count_per_award") > 1).cast("long")).alias(
                "rows_from_multi_supplier_awards"
            ),
            F.sum(F.col("award_amount_single_supplier").isNotNull().cast("long")).alias(
                "rows_with_safe_supplier_amount"
            ),
            F.sum(F.col("award_date").isNull().cast("long")).alias("rows_without_award_date"),
        )
        summary.show(truncate=False)
        print(f"Tabla creada: {output_dir}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
