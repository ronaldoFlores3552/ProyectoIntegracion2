"""Prepara cortes retrospectivos de relaciones entidad–proveedor con Spark."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.features.build_part1 import build_dictionary, directory_fingerprint
from src.processing.build_fact_award import configure_pyspark_python, missing_or_blank
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)
from src.quality.profile_fact_award_item import write_json_atomically


def split_pairs(events: DataFrame, year: int) -> tuple[DataFrame, DataFrame]:
    """Devuelve interacciones de entrenamiento y pares futuros con estado frío/repetido."""
    valid = events.where(
        F.col("award_date").isNotNull()
        & ~missing_or_blank("entity_id")
        & ~missing_or_blank("supplier_id")
    ).withColumn("_year", F.year("award_date"))
    train = (
        valid.where(F.col("_year") < year)
        .groupBy("entity_id", "supplier_id")
        .agg(F.count("*").cast("long").alias("interaction_count"))
        .withColumn("strength", F.log1p("interaction_count"))
    )
    future = valid.where(F.col("_year") == year).select("entity_id", "supplier_id").distinct()
    seen_pairs = train.select("entity_id", "supplier_id").withColumn("seen", F.lit(True))
    entities = train.select("entity_id").distinct().withColumn("entity_known", F.lit(True))
    suppliers = train.select("supplier_id").distinct().withColumn("supplier_known", F.lit(True))
    future = (
        future.join(seen_pairs, ["entity_id", "supplier_id"], "left")
        .join(entities, "entity_id", "left")
        .join(suppliers, "supplier_id", "left")
        .fillna(False, subset=["seen", "entity_known", "supplier_known"])
        .withColumn(
            "eligible_positive", ~F.col("seen") & F.col("entity_known") & F.col("supplier_known")
        )
    )
    return train, future


def prepare_cut(events: DataFrame, year: int) -> tuple[DataFrame, DataFrame, DataFrame, DataFrame]:
    train, future = split_pairs(events, year)
    entities = build_dictionary(train, "entity_id", "entity_index")
    suppliers = build_dictionary(train, "supplier_id", "supplier_index")
    matrix = train.join(entities, "entity_id").join(suppliers, "supplier_id")
    return matrix, future, entities, suppliers


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/recommendation"))
    parser.add_argument("--master", default="local[4]")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    stage = staging_dir(output)
    if not (source / "_SUCCESS").is_file():
        raise FileNotFoundError(f"Falta publicación completa: {source}")
    for target in (output, stage, output.with_name(output.name + ".previous")):
        if target == source or target in source.parents or source in target.parents:
            raise ValueError(f"Ruta de entrada y salida solapadas: {target}")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite para regenerar")
    hadoop = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("recommendation-preparation")
        .master(args.master)
        .config("spark.sql.session.timeZone", "America/Lima")
        .config("spark.sql.shuffle.partitions", "8")
    )
    if hadoop:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop / "bin"))
    spark = builder.getOrCreate()
    try:
        events = spark.read.parquet(str(source)).cache()
        key = ["process_ocid", "award_id", "supplier_id"]
        if (
            events.where(missing_or_blank("process_ocid") | missing_or_blank("award_id"))
            .limit(1)
            .count()
        ):
            raise ValueError("Clave de adjudicación incompleta")
        if events.groupBy(*key).count().where(F.col("count") > 1).limit(1).count():
            raise ValueError("Duplicados en clave adjudicación-proveedor")
        if (
            events.where(
                F.col("award_date").isNotNull()
                & (F.col("award_year").isNull() | (F.year("award_date") != F.col("award_year")))
            )
            .limit(1)
            .count()
        ):
            raise ValueError("award_year no coincide con fecha en America/Lima")
        totals = (
            events.agg(
                F.count("*").alias("rows"),
                F.sum(F.col("award_date").isNull().cast("long")).alias("missing_date"),
                F.sum(missing_or_blank("entity_id").cast("long")).alias("missing_entity"),
                F.sum(missing_or_blank("supplier_id").cast("long")).alias("missing_supplier"),
                F.sum(
                    (
                        F.col("award_date").isNull()
                        | missing_or_blank("entity_id")
                        | missing_or_blank("supplier_id")
                    ).cast("long")
                ).alias("excluded_union"),
            )
            .first()
            .asDict()
        )
        sha_before = directory_fingerprint(source)
        shutil.rmtree(stage, ignore_errors=True)
        cuts = {}
        for year in (2023, 2024):
            matrix, future, entities, suppliers = prepare_cut(events, year)
            cut_dir = stage / str(year)
            for name, frame in (
                ("train", matrix),
                ("future_pairs", future),
                ("entities", entities),
                ("suppliers", suppliers),
            ):
                frame.write.mode("error").parquet(str(cut_dir / name))
            # Releer lo publicado evita que las estadísticas se basen en otro plan.
            train = spark.read.parquet(str(cut_dir / "train"))
            future = spark.read.parquet(str(cut_dir / "future_pairs"))
            e = spark.read.parquet(str(cut_dir / "entities"))
            s = spark.read.parquet(str(cut_dir / "suppliers"))
            size = {"train_pairs": train.count(), "entities": e.count(), "suppliers": s.count()}
            if size["entities"] > 2**31 - 1 or size["suppliers"] > 2**31 - 1:
                raise ValueError("Los diccionarios exceden los índices enteros de ALS")
            row = (
                future.agg(
                    F.count("*").alias("future_pairs"),
                    F.sum(F.col("seen").cast("long")).alias("repeated_pairs"),
                    F.sum((~F.col("seen")).cast("long")).alias("new_pairs"),
                    F.sum(F.col("eligible_positive").cast("long")).alias("eligible_positives"),
                    F.countDistinct(F.when(F.col("eligible_positive"), F.col("entity_id"))).alias(
                        "eligible_entities"
                    ),
                )
                .first()
                .asDict()
            )
            cuts[str(year)] = {**size, **row}
        if sha_before != directory_fingerprint(source):
            raise RuntimeError("La fuente cambió durante la preparación")
        metadata = {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "input": str(source),
            "input_sha256": sha_before,
            "timezone": "America/Lima",
            "exclusions": totals,
            "cuts": cuts,
            "availability": "retrospective; historical availability unverified",
            "candidates": "training suppliers excluding each entity's training pairs",
        }
        write_json_atomically(stage / "_metadata.json", metadata)
        (stage / "_SUCCESS").touch()
        publish_output(stage, output)
        print(f"Cortes publicados: {output}; {cuts}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
