"""Publica vectores, matriz dispersa y grafo KNN de la Parte I con Spark."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)
from src.quality.profile_fact_award_item import write_json_atomically


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--supplier-dir", type=Path, default=Path("data/processed/entity_supplier_year")
    )
    parser.add_argument(
        "--category-dir", type=Path, default=Path("data/processed/entity_category_year")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/part1"))
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--max-pairs", type=int, default=10000000)
    parser.add_argument("--master", default="local[4]")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def directory_fingerprint(path: Path) -> str:
    """Huella del contenido actual, no prueba del origen histórico de la tabla."""
    digest = hashlib.sha256()
    files = (p for p in path.rglob("*") if p.is_file() and not p.name.startswith("."))
    for file in sorted(files, key=lambda p: p.relative_to(path).as_posix()):
        relative = file.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = hashlib.sha256()
        with file.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                content.update(block)
        digest.update(content.digest())
    return digest.hexdigest()


def validate_inputs(supplier: Path, category: Path, output: Path, overwrite: bool) -> dict:
    inputs = (supplier, category)
    for path in inputs:
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta _SUCCESS: {path}")
    for target in (output, staging_dir(output), output.with_name(output.name + ".previous")):
        for source in inputs:
            if target == source or target in source.parents or source in target.parents:
                raise ValueError(f"Salida solapada con entrada: {target}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite para regenerar.")
    metadata = [json.loads((p / "_metadata.json").read_text(encoding="utf-8")) for p in inputs]
    if not metadata[0].get("run_id") or metadata[0]["run_id"] != metadata[1].get("run_id"):
        raise ValueError("Las interacciones no pertenecen a la misma corrida.")
    return {
        "run_id": metadata[0]["run_id"],
        "supplier_sha256": directory_fingerprint(supplier),
        "category_sha256": directory_fingerprint(category),
    }


def windowed(frame: DataFrame, start: int, end: int) -> DataFrame:
    return frame.where(F.col("award_year").between(start, end))


def build_dictionary(frame: DataFrame, column: str, index: str) -> DataFrame:
    """Asigna índices estables por bucket y nombre; solo 256 totales se ordenan globalmente."""
    keys = (
        frame.select(column)
        .distinct()
        .withColumn("_bucket", F.pmod(F.xxhash64(column), F.lit(256)))
    )
    bucket_sizes = keys.groupBy("_bucket").count()
    preceding = Window.orderBy("_bucket").rowsBetween(Window.unboundedPreceding, -1)
    offsets = bucket_sizes.withColumn(
        "_offset", F.coalesce(F.sum("count").over(preceding), F.lit(0))
    )
    position = Window.partitionBy("_bucket").orderBy(column)
    return (
        keys.join(F.broadcast(offsets.select("_bucket", "_offset")), "_bucket")
        .withColumn(index, (F.col("_offset") + F.row_number().over(position) - 1).cast("long"))
        .select(column, index)
    )


def build_matrix(frame: DataFrame) -> tuple[DataFrame, DataFrame, DataFrame]:
    counts = frame.groupBy("entity_id", "supplier_id").agg(
        F.sum("award_count").cast("long").alias("interaction_count")
    )
    entities = build_dictionary(counts, "entity_id", "entity_index")
    suppliers = build_dictionary(counts, "supplier_id", "supplier_index")
    matrix = counts.join(entities, "entity_id").join(suppliers, "supplier_id")
    return matrix, entities, suppliers


def build_features(frame: DataFrame) -> tuple[DataFrame, list[str], list[dict]]:
    categories = [
        r[0]
        for r in frame.select("procurement_category")
        .distinct()
        .orderBy("procurement_category")
        .collect()
    ]
    if not categories or len(categories) > 100:
        raise ValueError("Se requieren entre 1 y 100 categorías para esta representación.")
    counts = frame.groupBy("entity_id", "procurement_category").agg(
        F.sum("award_count").cast("long").alias("category_count")
    )
    totals = counts.groupBy("entity_id").agg(F.sum("category_count").alias("award_count"))
    pivot = (
        counts.groupBy("entity_id").pivot("procurement_category", categories).sum("category_count")
    )
    # Renombrar antes de seleccionar permite categorías con puntos o caracteres especiales.
    for index, name in enumerate(categories):
        pivot = pivot.withColumnRenamed(name, f"category_{index}")
    features = totals.join(pivot, "entity_id").withColumn("log_award_count", F.log1p("award_count"))
    for index in range(len(categories)):
        features = features.withColumn(
            f"fraction_{index}",
            F.coalesce(F.col(f"category_{index}"), F.lit(0)) / F.col("award_count"),
        ).drop(f"category_{index}")
    dimensions = ["log_award_count"] + [f"fraction_{i}" for i in range(len(categories))]
    aggregations = []
    for i, column in enumerate(dimensions):
        aggregations.extend(
            [F.avg(column).alias(f"mean_{i}"), F.stddev_pop(column).alias(f"std_{i}")]
        )
    statistics = features.agg(*aggregations).first().asDict()
    params = [
        {"dimension": column, "mean": statistics[f"mean_{i}"], "std": statistics[f"std_{i}"] or 0.0}
        for i, column in enumerate(dimensions)
    ]
    scaled = [
        ((F.col(p["dimension"]) - F.lit(p["mean"])) / F.lit(p["std"]) if p["std"] else F.lit(0.0))
        for p in params
    ]
    features = features.withColumn("vector_original", F.array(*[F.col(c) for c in dimensions]))
    return features.withColumn("vector_scaled", F.array(*scaled)), categories, params


def build_knn(features: DataFrame, k: int, max_pairs: int) -> tuple[DataFrame, int]:
    count = features.count()
    pairs = count * (count - 1)
    if pairs > max_pairs:
        raise ValueError(f"KNN exacto necesita {pairs} pares; límite configurado: {max_pairs}.")
    left = features.select(F.col("entity_id").alias("src"), F.col("vector_scaled").alias("a"))
    right = features.select(F.col("entity_id").alias("dst"), F.col("vector_scaled").alias("b"))
    distances = (
        left.crossJoin(F.broadcast(right))
        .where(F.col("src") != F.col("dst"))
        .withColumn(
            "distance",
            F.sqrt(
                F.expr(
                    "aggregate(zip_with(a, b, (x, y) -> (x-y)*(x-y)), "
                    "cast(0.0 as double), (acc, x) -> acc+x)"
                )
            ),
        )
    )
    ranking = Window.partitionBy("src").orderBy("distance", "dst")
    edges = (
        distances.withColumn("neighbor_rank", F.row_number().over(ranking))
        .where(F.col("neighbor_rank") <= k)
        .select("src", "dst", "distance", "neighbor_rank")
    )
    return edges, pairs


def run() -> None:
    args = parse_args()
    if args.start_year > args.end_year or args.k < 1 or args.max_pairs < 0:
        raise ValueError("Ventana, k o límite de pares inválidos.")
    supplier, category, output = (
        p.resolve() for p in (args.supplier_dir, args.category_dir, args.output_dir)
    )
    lineage = validate_inputs(supplier, category, output, args.overwrite)
    hadoop = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("parte1-representaciones")
        .master(args.master)
        .config("spark.sql.session.timeZone", "America/Lima")
        .config("spark.sql.shuffle.partitions", "8")
    )
    if hadoop:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop / "bin"))
    spark = builder.getOrCreate()
    try:
        native_loader = spark.sparkContext._jvm.org.apache.hadoop.util.NativeCodeLoader
        if hadoop and not native_loader.isNativeCodeLoaded():
            raise RuntimeError(
                "La JVM no cargó hadoop.dll; revise setup_windows_hadoop.py --check."
            )
        suppliers = spark.read.option("pathGlobFilter", "*.parquet").parquet(str(supplier))
        categories = spark.read.option("pathGlobFilter", "*.parquet").parquet(str(category))
        s = windowed(suppliers, args.start_year, args.end_year).cache()
        c = windowed(categories, args.start_year, args.end_year).cache()
        bad_supplier = (F.col('entity_id').isNull() | F.col('supplier_id').isNull()
                        | (F.col('award_count') <= 0) | F.col('award_count').isNull())
        bad_category = (F.col('entity_id').isNull() | F.col('procurement_category').isNull()
                        | (F.col('award_count') <= 0) | F.col('award_count').isNull())
        if s.where(bad_supplier).limit(1).count() or c.where(bad_category).limit(1).count():
            raise ValueError('Las interacciones contienen claves o conteos inválidos.')
        total_s = s.agg(F.sum("award_count")).first()[0] or 0
        total_c = c.agg(F.sum("award_count")).first()[0] or 0
        if not total_s or not total_c:
            raise ValueError("La ventana seleccionada no contiene adjudicaciones elegibles.")
        matrix, entities, providers = build_matrix(s)
        features, names, params = build_features(c)
        features = features.cache()
        node_count = features.count()
        edges, pair_count = build_knn(features, args.k, args.max_pairs)
        stage = staging_dir(output)
        shutil.rmtree(stage, ignore_errors=True)
        tables = {
            "entity_features": features,
            "matrix": matrix,
            "entity_dictionary": entities,
            "supplier_dictionary": providers,
            "graph_nodes": features.select("entity_id"),
            "graph_edges": edges,
        }
        for name, frame in tables.items():
            frame.write.mode("overwrite").parquet(str(stage / name))
            if not (stage / name / "_SUCCESS").is_file():
                raise RuntimeError(f"Salida incompleta: {name}")
        written = {name: spark.read.parquet(str(stage / name)) for name in tables}
        matrix_stats = (
            written["matrix"]
            .agg(F.count("*").alias("rows"), F.sum("interaction_count").alias("count_sum"))
            .first()
        )
        entity_count = written["entity_dictionary"].count()
        provider_count = written["supplier_dictionary"].count()
        edge_count = written["graph_edges"].count()
        if matrix_stats["count_sum"] != total_s:
            raise RuntimeError("Los conteos de matriz no concilian con su fuente.")
        if edge_count != node_count * min(args.k, max(node_count - 1, 0)):
            raise RuntimeError("El grafo KNN no contiene el número esperado de aristas.")
        metadata = {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "window": {"start_award_year": args.start_year, "end_award_year": args.end_year},
            "lineage": lineage,
            "identity_policy": "ID originales, sin fusiones",
            "supplier_count_eligible": total_s,
            "category_count_eligible": total_c,
            "category_names": names,
            "scaling": params,
            "features": node_count,
            "matrix_rows": matrix_stats["rows"],
            "matrix_entities": entity_count,
            "matrix_suppliers": provider_count,
            "matrix_density": matrix_stats["rows"] / (entity_count * provider_count),
            "graph_nodes": node_count,
            "graph_edges": edge_count,
            "k": args.k,
            "graph_directed": True,
            "distance": "euclidean_population_standardized",
            "graph_candidate_pairs": pair_count,
            "max_pairs": args.max_pairs,
            "scaling_scope": "descriptivo: toda la ventana; no usar para evaluación temporal",
        }
        write_json_atomically(stage / "_metadata.json", metadata)
        (stage / "_SUCCESS").touch()
        publish_output(stage, output)
        print(f"Parte I publicada: {output}")
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
