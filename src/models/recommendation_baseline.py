"""Evalúa el baseline de popularidad sobre la validación retrospectiva."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import islice
from math import log2
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from src.features.build_part1 import directory_fingerprint
from src.processing.build_fact_award_item import publish_output, staging_dir
from src.quality.profile_fact_award_item import write_json_atomically

MAX_ROWS = 500_000
MAX_BYTES = 256 * 1024 * 1024


def rank_popularity(train: pd.DataFrame, entities: set[str], k: int = 20) -> dict[str, list[str]]:
    """Proveedores ordenados por entidades distintas; excluye historial sin cruzar el catálogo."""
    history: dict[str, set[str]] = defaultdict(set)
    popularity = Counter()
    for row in train[["entity_id", "supplier_id"]].itertuples(index=False):
        if row.supplier_id not in history[row.entity_id]:
            history[row.entity_id].add(row.supplier_id)
            popularity[row.supplier_id] += 1
    ordered = sorted(popularity, key=lambda supplier: (-popularity[supplier], supplier))
    return {
        entity: list(
            islice((supplier for supplier in ordered if supplier not in history[entity]), k)
        )
        for entity in sorted(entities)
    }


def score_rankings(
    rankings: dict[str, list[str]],
    positives: dict[str, set[str]],
    candidate_counts: dict[str, int],
    k: int,
) -> pd.DataFrame:
    """Métricas por entidad; posiciones no devueltas valen cero."""
    rows = []
    for entity, relevant in sorted(positives.items()):
        if not relevant:
            raise ValueError("No se evalúan entidades sin positivos")
        ku = min(k, candidate_counts[entity])
        ranking = rankings.get(entity, [])[:ku]
        if len(set(ranking)) != len(ranking) or ku < 1:
            raise ValueError("Ranking duplicado o sin candidatos")
        hits = [int(supplier in relevant) for supplier in ranking]
        dcg = sum(hit / log2(position + 2) for position, hit in enumerate(hits))
        ideal = sum(1 / log2(position + 2) for position in range(min(ku, len(relevant))))
        rows.append(
            {
                "entity_id": entity,
                "k": k,
                "candidate_count": candidate_counts[entity],
                "ranking_length": len(ranking),
                "positive_count": len(relevant),
                "hits": sum(hits),
                "recall": sum(hits) / len(relevant),
                "precision": sum(hits) / ku,
                "ndcg": dcg / ideal,
            }
        )
    return pd.DataFrame(rows)


def read_table(path: Path, columns: list[str]) -> pd.DataFrame:
    if not (path / "_SUCCESS").exists():
        raise FileNotFoundError(f"Tabla incompleta: {path}")
    size = sum(f.stat().st_size for f in path.rglob("*.parquet"))
    dataset = ds.dataset(path, format="parquet", exclude_invalid_files=True)
    if size > MAX_BYTES or dataset.count_rows() > MAX_ROWS:
        raise ValueError(f"Entrada excede el límite local: {path}")
    return dataset.to_table(columns=columns).to_pandas()


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed/recommendation"))
    parser.add_argument(
        "--events-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/recommendation_baseline")
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    stage = staging_dir(output)
    if not (source / "_SUCCESS").is_file():
        raise FileNotFoundError(f"Publicación incompleta: {source}")
    for target in (output, stage, output.with_name(output.name + ".previous")):
        if target == source or target in source.parents or source in target.parents:
            raise ValueError("Rutas de entrada y salida solapadas")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite")
    meta = json.loads((source / "_metadata.json").read_text(encoding="utf-8"))
    input_fact = args.events_dir.resolve()
    if not input_fact.exists() or directory_fingerprint(input_fact) != meta["input_sha256"]:
        raise ValueError("La fuente de eventos cambió desde la preparación")
    input_hash = directory_fingerprint(source)
    # El test 2024 no se consulta ni evalúa durante selección.
    cut = source / "2023"
    train = read_table(cut / "train", ["entity_id", "supplier_id"])
    future = read_table(cut / "future_pairs", ["entity_id", "supplier_id", "eligible_positive"])
    if train.duplicated(["entity_id", "supplier_id"]).any():
        raise ValueError("Pares duplicados en entrenamiento")
    positives = defaultdict(set)
    for row in future.loc[future.eligible_positive].itertuples(index=False):
        positives[row.entity_id].add(row.supplier_id)
    if not positives:
        raise ValueError("No hay positivos evaluables")
    history = train.groupby("entity_id").supplier_id.nunique().to_dict()
    catalog = set(train.supplier_id)
    counts = {entity: len(catalog) - history[entity] for entity in positives}
    rankings = rank_popularity(train, set(positives))
    metrics = pd.concat([score_rankings(rankings, positives, counts, k) for k in (10, 20)])
    rank_rows = [
        {"entity_id": entity, "supplier_id": supplier, "rank": position}
        for entity, suppliers in rankings.items()
        for position, supplier in enumerate(suppliers, 1)
    ]
    recommended = {row["supplier_id"] for row in rank_rows}
    summary = {
        str(k): {key: float(group[key].mean()) for key in ("recall", "precision", "ndcg")}
        for k, group in metrics.groupby("k")
    }
    if directory_fingerprint(source) != input_hash:
        raise RuntimeError("Entradas cambiaron durante evaluación")
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    pd.DataFrame(rank_rows).to_parquet(stage / "rankings.parquet", index=False)
    metrics.to_parquet(stage / "metrics_by_entity.parquet", index=False)
    write_json_atomically(
        stage / "_metadata.json",
        {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "input": str(source),
            "input_sha256": input_hash,
            "cut": 2023,
            "method": "popularidad por entidades distintas de entrenamiento",
            "tie_break": "supplier_id ascendente",
            "entities_evaluated": len(positives),
            "catalog_size": len(catalog),
            "distinct_recommended": len(recommended),
            "provider_coverage": len(recommended) / len(catalog),
            "metrics_macro": summary,
            "availability": meta["availability"],
        },
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"Baseline publicado: {output}; {summary}")


if __name__ == "__main__":
    run()
