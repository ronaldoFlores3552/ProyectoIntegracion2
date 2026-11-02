"""Selecciona ALS implícito usando únicamente la validación retrospectiva de 2023."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.ml.recommendation import ALS
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from threadpoolctl import threadpool_limits

from src.features.build_part1 import directory_fingerprint
from src.models.recommendation_baseline import read_table, score_rankings
from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)
from src.quality.profile_fact_award_item import write_json_atomically

MAX_FACTOR_BYTES = 256 * 1024 * 1024
MAX_SCORE_OPERATIONS = 2_000_000_000
CONFIGS = ({"rank": 16, "reg": 0.1, "alpha": 10.0}, {"rank": 32, "reg": 0.1, "alpha": 10.0})


def exact_rankings(user_factors, item_factors, train, entities, *, top_k=20):
    """Top-k exacto por bloques, excluyendo historial; empate por ID de proveedor."""
    item_factors = item_factors.sort_values("supplier_id").reset_index(drop=True)
    ids = item_factors.supplier_id.to_numpy()
    item_vectors = np.stack(item_factors.features.to_numpy()).astype(np.float32)
    user_vectors = {
        row.entity_id: np.asarray(row.features, dtype=np.float32)
        for row in user_factors.itertuples(index=False)
    }
    eligible_entities = sorted(entities)
    if not set(eligible_entities).issubset(user_vectors):
        raise ValueError("Faltan factores de entidades conocidas")
    if len(ids) * len(eligible_entities) * item_vectors.shape[1] > MAX_SCORE_OPERATIONS:
        raise ValueError("El cálculo exacto excede el límite de operaciones")
    if item_vectors.nbytes > MAX_FACTOR_BYTES:
        raise ValueError("Factores exceden límite de memoria")
    indices = {supplier: index for index, supplier in enumerate(ids)}
    history = defaultdict(list)
    for row in train[["entity_id", "supplier_id"]].itertuples(index=False):
        history[row.entity_id].append(indices[row.supplier_id])
    rankings = {}
    with threadpool_limits(limits=1):
        for start in range(0, len(eligible_entities), 32):
            batch = eligible_entities[start : start + 32]
            scores = np.stack([user_vectors[e] for e in batch]) @ item_vectors.T
            if not np.isfinite(scores).all():
                raise ValueError("Puntuaciones no finitas")
            for row, entity in enumerate(batch):
                scores[row, history[entity]] = -np.inf
                order = np.lexsort((np.arange(len(ids)), -scores[row]))
                order = order[np.isfinite(scores[row, order])][:top_k]
                rankings[entity] = ids[order].tolist()
    return rankings


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed/recommendation"))
    parser.add_argument(
        "--events-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument(
        "--baseline-dir", type=Path, default=Path("artifacts/recommendation_baseline")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/recommendation_als"))
    parser.add_argument("--master", default="local[4]")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    stage = staging_dir(output)
    for target in (output, stage, output.with_name(output.name + ".previous")):
        for protected in (source, args.events_dir.resolve(), args.baseline_dir.resolve()):
            if target == protected or target in protected.parents or protected in target.parents:
                raise ValueError("Rutas de entrada y salida solapadas")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite")
    if not (source / "_SUCCESS").is_file() or not (args.baseline_dir / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta publicación de cortes o baseline")
    meta = json.loads((source / "_metadata.json").read_text(encoding="utf-8"))
    base = json.loads((args.baseline_dir / "_metadata.json").read_text(encoding="utf-8"))
    fingerprint = directory_fingerprint(source)
    if (
        base["input_sha256"] != fingerprint
        or directory_fingerprint(args.events_dir) != meta["input_sha256"]
    ):
        raise ValueError("Entradas cambiaron desde preparación o baseline")
    cut = source / "2023"
    train = read_table(
        cut / "train", ["entity_id", "supplier_id", "entity_index", "supplier_index"]
    )
    future = read_table(cut / "future_pairs", ["entity_id", "supplier_id", "eligible_positive"])
    entities = read_table(cut / "entities", ["entity_id", "entity_index"])
    suppliers = read_table(cut / "suppliers", ["supplier_id", "supplier_index"])
    positives = defaultdict(set)
    for row in future.loc[future.eligible_positive].itertuples(index=False):
        positives[row.entity_id].add(row.supplier_id)
    history = train.groupby("entity_id").supplier_id.nunique().to_dict()
    counts = {entity: len(suppliers) - history[entity] for entity in positives}
    hadoop = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("recommendation-als-validation")
        .master(args.master)
        .config("spark.sql.session.timeZone", "America/Lima")
        .config("spark.sql.shuffle.partitions", "8")
    )
    if hadoop:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop / "bin"))
    spark = builder.getOrCreate()
    results, details = [], []
    try:
        interactions = (
            spark.read.parquet(str(cut / "train")).select(
                F.col("entity_index").cast("int").alias("user"),
                F.col("supplier_index").cast("int").alias("item"),
                F.col("strength").cast("float").alias("strength"),
            )
        ).cache()
        for config in CONFIGS:
            model = ALS(
                userCol="user",
                itemCol="item",
                ratingCol="strength",
                implicitPrefs=True,
                rank=config["rank"],
                regParam=config["reg"],
                alpha=config["alpha"],
                maxIter=10,
                seed=42,
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
            ranking = exact_rankings(u, i, train, set(positives))
            metrics = pd.concat([score_rankings(ranking, positives, counts, k) for k in (10, 20)])
            metrics["rank"] = config["rank"]
            summaries = {
                str(k): {key: float(group[key].mean()) for key in ("recall", "precision", "ndcg")}
                for k, group in metrics.groupby("k")
            }
            results.append(
                {
                    "config": config,
                    "metrics_macro": summaries,
                    "provider_coverage": len({s for v in ranking.values() for s in v})
                    / len(suppliers),
                }
            )
            details.append((ranking, metrics))
            print(f"Validación ALS {config}: {summaries}", flush=True)
    finally:
        spark.stop()
    winner = max(
        range(len(results)),
        key=lambda j: (results[j]["metrics_macro"]["10"]["ndcg"], -CONFIGS[j]["rank"]),
    )
    ranking, metrics = details[winner]
    if directory_fingerprint(source) != fingerprint:
        raise RuntimeError("Entradas cambiaron durante evaluación")
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    rows = [
        {"entity_id": e, "supplier_id": s, "rank": n}
        for e, values in ranking.items()
        for n, s in enumerate(values, 1)
    ]
    pd.DataFrame(rows).to_parquet(stage / "rankings.parquet", index=False)
    pd.concat([m for _, m in details]).to_parquet(stage / "metrics_by_entity.parquet", index=False)
    write_json_atomically(
        stage / "_metadata.json",
        {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_sha256": fingerprint,
            "cut": 2023,
            "method": "Spark ALS implícito",
            "selection": "NDCG@10 macro; empate por menor rango",
            "results": results,
            "selected": results[winner]["config"],
            "maxIter": 10,
            "seed": 42,
            "entities_evaluated": len(positives),
            "availability": meta["availability"],
        },
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"ALS validación publicado: {output}; seleccionado {results[winner]['config']}")


if __name__ == "__main__":
    run()
