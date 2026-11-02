"""Construye interacciones anuales por entidad, proveedor, categoría y moneda."""

from __future__ import annotations

import argparse
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.processing.build_fact_award import configure_pyspark_python, missing_or_blank
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)
from src.quality.profile_fact_award_item import write_json_atomically

MISSING = "<MISSING>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--awards-dir", type=Path, default=Path("data/processed/fact_award"))
    parser.add_argument(
        "--suppliers-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument(
        "--supplier-output-dir", type=Path, default=Path("data/processed/entity_supplier_year")
    )
    parser.add_argument(
        "--category-output-dir", type=Path, default=Path("data/processed/entity_category_year")
    )
    parser.add_argument("--master", default="local[*]")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _prepared(frame: DataFrame, dimension: str) -> DataFrame:
    eligible = frame.where(F.col("award_date").isNotNull() & ~missing_or_blank("entity_id"))
    if dimension == "supplier_id":
        eligible = eligible.where(~missing_or_blank("supplier_id"))
    currency_known = ~missing_or_blank("award_currency")
    prepared = (
        eligible.withColumn("award_year", F.year("award_date"))
        .withColumn("_currency_known", currency_known)
        .withColumn(
            "award_currency",
            F.when(currency_known, F.trim(F.col("award_currency"))).otherwise(F.lit(MISSING)),
        )
    )
    if dimension == "procurement_category":
        prepared = prepared.withColumn(
            dimension,
            F.when(missing_or_blank(dimension), F.lit(MISSING)).otherwise(F.trim(F.col(dimension))),
        )
    return prepared


def build_interaction(frame: DataFrame, dimension: str, amount_column: str) -> DataFrame:
    """Aggregate distinct input-grain rows without combining or inventing currencies."""
    prepared = _prepared(frame, dimension)
    amount_eligible = F.col("_currency_known") & F.col(amount_column).isNotNull()
    return prepared.groupBy("entity_id", dimension, "award_year", "award_currency").agg(
        F.count("*").alias("award_count"),
        F.count(F.when(amount_eligible, 1)).alias("amount_known_count"),
        F.sum(F.when(amount_eligible, F.col(amount_column))).alias("amount_sum"),
        F.max("award_date").alias("latest_award_date"),
    )


def source_metrics(frame: DataFrame, dimension: str, amount_column: str) -> dict:
    """Count exclusions and coverage without treating overlapping reasons as additive."""
    valid_date = F.col("award_date").isNotNull()
    valid_entity = ~missing_or_blank("entity_id")
    valid_dimension = (
        ~missing_or_blank("supplier_id") if dimension == "supplier_id" else F.lit(True)
    )
    eligible = valid_date & valid_entity & valid_dimension
    currency_known = ~missing_or_blank("award_currency")
    return frame.agg(
        F.count("*").alias("input_rows"),
        F.count(F.when(~valid_date, 1)).alias("missing_date_rows"),
        F.count(F.when(~valid_entity, 1)).alias("missing_entity_rows"),
        F.count(F.when(~valid_dimension, 1)).alias("missing_supplier_rows"),
        F.count(F.when(~eligible, 1)).alias("excluded_rows"),
        F.count(F.when(eligible, 1)).alias("eligible_rows"),
        F.count(F.when(eligible & ~currency_known, 1)).alias("eligible_missing_currency_rows"),
        F.count(F.when(eligible & F.col(amount_column).isNull(), 1)).alias(
            "eligible_missing_amount_rows"
        ),
        F.count(F.when(eligible & currency_known & F.col(amount_column).isNotNull(), 1)).alias(
            "eligible_amount_known_rows"
        ),
        F.count(
            F.when(eligible & missing_or_blank("procurement_category"), 1)
        ).alias("eligible_missing_category_rows"),
    ).first().asDict()


def _validate_paths(inputs: tuple[Path, ...], outputs: tuple[Path, ...], overwrite: bool) -> None:
    for path in inputs:
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"No existe una tabla publicada con _SUCCESS: {path}")
    protected = [*inputs, *outputs]
    for index, output in enumerate(outputs):
        if output.exists() and not overwrite:
            raise FileExistsError(
                f"La salida ya existe: {output}. Use --overwrite para regenerarla."
            )
        for other in protected[: len(inputs) + index]:
            if output == other or output in other.parents or other in output.parents:
                raise ValueError(
                    f"Las rutas de entrada y salida no pueden solaparse: {output}, {other}"
                )
        for temporary in (staging_dir(output), output.with_name(f"{output.name}.previous")):
            for other in protected:
                if temporary == other or temporary in other.parents or other in temporary.parents:
                    raise ValueError(
                        f"Ruta temporal en conflicto con una entrada o salida: {temporary}"
                    )


def _check_sentinel(frame: DataFrame, dimension: str) -> None:
    columns = ["award_currency"]
    if dimension == "procurement_category":
        columns.append(dimension)
    condition = F.lit(False)
    for column in columns:
        condition = condition | (F.trim(F.col(column)) == MISSING)
    if frame.where(condition).limit(1).count():
        raise ValueError(f"La fuente contiene el valor reservado {MISSING} en {columns}.")


def run() -> None:
    args = parse_args()
    inputs = (args.awards_dir.resolve(), args.suppliers_dir.resolve())
    outputs = (args.supplier_output_dir.resolve(), args.category_output_dir.resolve())
    _validate_paths(inputs, outputs, args.overwrite)

    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-build-interactions")
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
        awards = spark.read.parquet(str(inputs[0])).cache()
        suppliers = spark.read.parquet(str(inputs[1])).cache()
        run_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        jobs = (
            (suppliers, "supplier_id", "award_amount_single_supplier", outputs[0], inputs[1]),
            (awards, "procurement_category", "award_amount", outputs[1], inputs[0]),
        )
        staged = []
        for frame, dimension, amount_column, output, source in jobs:
            _check_sentinel(frame, dimension)
            metrics = source_metrics(frame, dimension, amount_column)
            result = build_interaction(frame, dimension, amount_column)
            stage = staging_dir(output)
            shutil.rmtree(stage, ignore_errors=True)
            result.write.mode("overwrite").partitionBy("award_year").parquet(str(stage))
            published = spark.read.parquet(str(stage))
            check = published.agg(
                F.count("*").alias("output_rows"),
                F.coalesce(F.sum("award_count"), F.lit(0)).alias("reconciled_rows"),
                F.coalesce(F.sum("amount_known_count"), F.lit(0)).alias("reconciled_amount_rows"),
            ).first().asDict()
            if (check["reconciled_rows"] != metrics["eligible_rows"] or
                    check["reconciled_amount_rows"] != metrics["eligible_amount_known_rows"]):
                raise RuntimeError(f"La salida no concilia con su fuente: {output}")
            metadata = {
                "version": 1,
                "run_id": run_id,
                "created_at_utc": created_at,
                "input_dir": str(source),
                "dimension": dimension,
                "amount_column": amount_column,
                "missing_label": MISSING,
                "input_metrics": metrics,
                "output_metrics": check,
            }
            write_json_atomically(stage / "_metadata.json", metadata)
            staged.append((stage, output, metadata))
        for stage, output, metadata in staged:
            publish_output(stage, output)
            print(f"Tabla creada: {output} | métricas: {metadata['input_metrics']}")
        print(f"Corrida de interacciones: {run_id}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
