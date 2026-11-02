"""Evalúa una vez los métodos congelados en la prueba retrospectiva de 2024."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pyspark.ml.recommendation import ALS
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from src.features.build_part1 import directory_fingerprint
from src.models.recommendation_als import exact_rankings
from src.models.recommendation_baseline import rank_popularity, read_table, score_rankings
from src.models.recommendation_neighbors import neighbor_rankings
from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)
from src.quality.profile_fact_award_item import write_json_atomically


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed/recommendation"))
    parser.add_argument(
        "--events-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument(
        "--baseline-dir", type=Path, default=Path("artifacts/recommendation_baseline")
    )
    parser.add_argument(
        "--neighbors-dir", type=Path, default=Path("artifacts/recommendation_neighbors")
    )
    parser.add_argument("--als-dir", type=Path, default=Path("artifacts/recommendation_als"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/recommendation_test"))
    parser.add_argument("--master", default="local[4]")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    stage = staging_dir(output)
    protected = [
        source,
        args.events_dir.resolve(),
        args.baseline_dir.resolve(),
        args.neighbors_dir.resolve(),
        args.als_dir.resolve(),
    ]
    for target in (output, stage, output.with_name(output.name + ".previous")):
        for path in protected:
            if target == path or target in path.parents or path in target.parents:
                raise ValueError("Rutas de entrada y salida solapadas")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; la prueba está congelada")
    for path in (source, *protected[2:]):
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta publicación completa: {path}")
    meta = json.loads((source / "_metadata.json").read_text(encoding="utf-8"))
    checks = [json.loads((p / "_metadata.json").read_text(encoding="utf-8")) for p in protected[2:]]
    fingerprint = directory_fingerprint(source)
    if any(c["input_sha256"] != fingerprint or c["cut"] != 2023 for c in checks):
        raise ValueError("Métodos no fueron validados sobre la misma entrada")
    if directory_fingerprint(args.events_dir) != meta["input_sha256"]:
        raise ValueError("La fuente cambió desde la preparación")
    config = checks[2]["selected"]
    if checks[1]["neighbors"] != 50 or checks[1]["shrinkage"] != 20:
        raise ValueError("Configuración de vecindario distinta de la validada")
    cut = source / "2024"
    train = read_table(
        cut / "train", ["entity_id", "supplier_id", "entity_index", "supplier_index", "strength"]
    )
    future = read_table(cut / "future_pairs", ["entity_id", "supplier_id", "eligible_positive"])
    entities = read_table(cut / "entities", ["entity_id", "entity_index"])
    suppliers = read_table(cut / "suppliers", ["supplier_id", "supplier_index"])
    positives = defaultdict(set)
    for row in future.loc[future.eligible_positive].itertuples(index=False):
        positives[row.entity_id].add(row.supplier_id)
    history = train.groupby("entity_id").supplier_id.nunique().to_dict()
    counts = {entity: len(suppliers) - history[entity] for entity in positives}
    rankings = {"popularidad": rank_popularity(train, set(positives))}
    rankings["vecindario"], diagnostics = neighbor_rankings(train, set(positives))
    print(f"Vecindario de prueba calculado: {diagnostics}", flush=True)
    hadoop = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("recommendation-als-test")
        .master(args.master)
        .config("spark.sql.session.timeZone", "America/Lima")
        .config("spark.sql.shuffle.partitions", "8")
    )
    if hadoop:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop / "bin"))
    spark = builder.getOrCreate()
    try:
        interactions = spark.read.parquet(str(cut / "train")).select(
            F.col("entity_index").cast("int").alias("user"),
            F.col("supplier_index").cast("int").alias("item"),
            F.col("strength").cast("float").alias("strength"),
        )
        model = ALS(
            userCol="user",
            itemCol="item",
            ratingCol="strength",
            implicitPrefs=True,
            rank=config["rank"],
            regParam=config["reg"],
            alpha=config["alpha"],
            maxIter=checks[2]["maxIter"],
            seed=checks[2]["seed"],
            coldStartStrategy="drop",
            numUserBlocks=4,
            numItemBlocks=4,
        ).fit(interactions)
        u = model.userFactors.toPandas().rename(columns={"id": "entity_index"})
        i = model.itemFactors.toPandas().rename(columns={"id": "supplier_index"})
        u = entities.merge(u, on="entity_index", validate="one_to_one")
        i = suppliers.merge(i, on="supplier_index", validate="one_to_one")
        if len(u) != len(entities) or len(i) != len(suppliers):
            raise ValueError("Faltan factores de entrenamiento")
        rankings["als"] = exact_rankings(u, i, train, set(positives))
    finally:
        spark.stop()
    all_metrics, all_ranks, summaries = [], [], {}
    for method, result in rankings.items():
        metrics = pd.concat([score_rankings(result, positives, counts, k) for k in (10, 20)])
        metrics["method"] = method
        all_metrics.append(metrics)
        all_ranks.extend(
            {"method": method, "entity_id": e, "supplier_id": s, "rank": n}
            for e, values in result.items()
            for n, s in enumerate(values, 1)
        )
        summaries[method] = {
            str(k): {key: float(group[key].mean()) for key in ("recall", "precision", "ndcg")}
            for k, group in metrics.groupby("k")
        }
        summaries[method]["entities_with_ranking"] = sum(bool(v) for v in result.values())
        summaries[method]["provider_coverage"] = len({s for v in result.values() for s in v}) / len(
            suppliers
        )
    if directory_fingerprint(source) != fingerprint:
        raise RuntimeError("Entradas cambiaron durante evaluación")
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    pd.DataFrame(all_ranks).to_parquet(stage / "rankings.parquet", index=False)
    pd.concat(all_metrics).to_parquet(stage / "metrics_by_entity.parquet", index=False)
    write_json_atomically(
        stage / "_metadata.json",
        {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_sha256": fingerprint,
            "cut": 2024,
            "selection_cut": 2023,
            "als_selected": config,
            "neighbor_parameters": {"neighbors": 50, "shrinkage": 20},
            "entities_evaluated": len(positives),
            "catalog_size": len(suppliers),
            "metrics_macro": summaries,
            "neighbor_diagnostics": diagnostics,
            "availability": meta["availability"],
        },
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"Prueba retrospectiva publicada: {output}; {summaries}")


if __name__ == "__main__":
    run()
