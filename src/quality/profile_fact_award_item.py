"""Perfil reproducible de calidad y EDA inicial para fact_award_item."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)

KEY_COLUMNS = ("process_ocid", "award_id", "supplier_id")
CANDIDATE_KEY_COLUMNS = (*KEY_COLUMNS, "item_id")
QUALITY_COLUMNS = (
    "source_year",
    "process_ocid",
    "award_id",
    "supplier_id",
    "entity_id",
    "procuring_entity_id",
    "award_date",
    "award_amount",
    "award_currency",
    "item_id",
    "item_classification_id",
)
CATEGORICAL_COLUMNS = ("award_currency", "procurement_category", "procurement_method")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed/fact_award_item"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/quality/fact_award_item"),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reemplaza explícitamente un perfil publicado.",
    )
    return parser.parse_args()


def configure_pyspark_python() -> None:
    """Keep local Spark workers in the same virtual environment as the driver."""
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)


def missing_or_blank(column: str) -> F.Column:
    return F.col(column).isNull() | (F.trim(F.col(column).cast("string")) == "")


def valid_key(columns: tuple[str, ...]) -> F.Column:
    condition = F.lit(True)
    for column in columns:
        condition = condition & ~missing_or_blank(column)
    return condition


def _as_json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    return value


def _row_to_json(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _as_json_value(value) for key, value in row.items()}


def candidate_duplicate_groups(fact: DataFrame) -> DataFrame:
    """Return candidate repeated keys; this is a diagnostic and never removes rows."""
    return (
        fact.where(valid_key(KEY_COLUMNS))
        .groupBy(*CANDIDATE_KEY_COLUMNS)
        .count()
        .where(F.col("count") > 1)
    )


def profile_by_year(fact: DataFrame) -> DataFrame:
    award_key = F.when(
        valid_key(("process_ocid", "award_id")),
        F.struct(F.col("process_ocid"), F.col("award_id")),
    )
    award_supplier_key = F.when(
        valid_key(KEY_COLUMNS),
        F.struct(F.col("process_ocid"), F.col("award_id"), F.col("supplier_id")),
    )
    return (
        fact.groupBy("source_year")
        .agg(
            F.count("*").alias("rows"),
            F.countDistinct("process_ocid").alias("distinct_processes"),
            F.countDistinct(award_key).alias("distinct_awards"),
            F.countDistinct(award_supplier_key).alias("distinct_award_suppliers"),
            F.countDistinct("supplier_id").alias("distinct_suppliers"),
            F.countDistinct("entity_id").alias("distinct_entities"),
            F.sum(missing_or_blank("item_id").cast("long")).alias("rows_missing_item_id"),
        )
        .orderBy("source_year")
    )


def profile_categories(fact: DataFrame) -> DataFrame:
    frames: list[DataFrame] = []
    for column in CATEGORICAL_COLUMNS:
        frames.append(
            fact.select(
                F.lit(column).alias("dimension"),
                F.when(missing_or_blank(column), F.lit("<MISSING>"))
                .otherwise(F.trim(F.col(column).cast("string")))
                .alias("value"),
            )
        )
    categories = frames[0]
    for frame in frames[1:]:
        categories = categories.unionByName(frame)
    return categories.groupBy("dimension", "value").count().orderBy("dimension", F.desc("count"))


def collect_profile(fact: DataFrame, input_dir: Path) -> dict[str, Any]:
    """Collect only small quality metadata; large summaries remain in Parquet."""
    award_key = F.when(
        valid_key(("process_ocid", "award_id")),
        F.struct(F.col("process_ocid"), F.col("award_id")),
    )
    award_supplier_key = F.when(
        valid_key(KEY_COLUMNS),
        F.struct(F.col("process_ocid"), F.col("award_id"), F.col("supplier_id")),
    )
    aggregations: list[F.Column] = [
        F.count("*").alias("rows"),
        F.countDistinct("process_ocid").alias("distinct_processes"),
        F.countDistinct(award_key).alias("distinct_awards"),
        F.countDistinct(award_supplier_key).alias("distinct_award_suppliers"),
        F.countDistinct("supplier_id").alias("distinct_suppliers"),
        F.countDistinct("entity_id").alias("distinct_entities"),
        F.min("award_date").alias("min_award_date"),
        F.max("award_date").alias("max_award_date"),
        F.sum(F.when(F.col("award_amount").isNull(), 1).otherwise(0)).alias("award_amount_null"),
        F.sum(F.when(F.col("award_amount") > 0, 1).otherwise(0)).alias("award_amount_positive"),
        F.sum(F.when(F.col("award_amount") == 0, 1).otherwise(0)).alias("award_amount_zero"),
        F.sum(F.when(F.col("award_amount") < 0, 1).otherwise(0)).alias("award_amount_negative"),
        F.sum(
            (
                valid_key(("entity_id", "procuring_entity_id"))
                & (F.col("entity_id") != F.col("procuring_entity_id"))
            ).cast("long")
        ).alias("buyer_procuring_entity_id_mismatch"),
    ]
    for column in QUALITY_COLUMNS:
        aggregations.append(F.sum(missing_or_blank(column).cast("long")).alias(f"{column}_missing"))

    global_metrics = _row_to_json(fact.agg(*aggregations).first().asDict())
    duplicate_metrics = _row_to_json(
        candidate_duplicate_groups(fact)
        .agg(
            F.count("*").alias("candidate_duplicate_groups"),
            F.coalesce(F.sum(F.col("count") - 1), F.lit(0)).alias(
                "candidate_duplicate_excess_rows"
            ),
        )
        .first()
        .asDict()
    )
    exact_duplicate_rows = fact.count() - fact.dropDuplicates().count()

    return {
        "profile_version": 1,
        "input_dir": str(input_dir.resolve()),
        "schema": [{"name": name, "type": data_type} for name, data_type in fact.dtypes],
        "global_metrics": global_metrics,
        "candidate_key_diagnostics": {
            **duplicate_metrics,
            "exact_duplicate_excess_rows": exact_duplicate_rows,
            "candidate_key_columns": list(CANDIDATE_KEY_COLUMNS),
        },
        "interpretation": {
            "award_amount_is_not_summed": (
                "award_amount pertenece a la adjudicación y puede repetirse por cada ítem; "
                "este perfil no lo suma."
            ),
            "duplicates_are_not_removed": (
                "Las repeticiones se reportan para revisión; no se eliminan en esta etapa."
            ),
        },
    }


def write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_as_json_value) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not (input_dir / "_SUCCESS").is_file():
        raise FileNotFoundError(f"No existe una tabla publicada con _SUCCESS: {input_dir}")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(
            f"El perfil ya existe: {output_dir}. Use --overwrite para regenerarlo."
        )

    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-profile-fact-award-item")
        .master("local[*]")
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

        fact = spark.read.parquet(str(input_dir)).cache()
        profile = collect_profile(fact, input_dir)
        staging = staging_dir(output_dir)
        shutil.rmtree(staging, ignore_errors=True)

        profile_by_year(fact).write.mode("overwrite").parquet(str(staging / "by_source_year"))
        profile_categories(fact).write.mode("overwrite").parquet(str(staging / "category_counts"))
        candidate_duplicate_groups(fact).write.mode("overwrite").parquet(
            str(staging / "candidate_key_duplicates")
        )
        write_json_atomically(staging / "profile.json", profile)
        (staging / "_SUCCESS").touch()
        publish_output(staging, output_dir)

        metrics = profile["global_metrics"]
        print(
            "Perfil creado: "
            f"rows={metrics['rows']}, distinct_awards={metrics['distinct_awards']}, "
            f"exact_duplicate_excess_rows="
            f"{profile['candidate_key_diagnostics']['exact_duplicate_excess_rows']}"
        )
        print(f"Perfil publicado: {output_dir}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()

