"""Evalúa perfiles de texto de ítems en la validación retrospectiva de 2023."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from src.features.build_part1 import directory_fingerprint
from src.models.recommendation_baseline import read_table, score_rankings
from src.processing.build_fact_award_item import publish_output, staging_dir
from src.quality.profile_fact_award_item import write_json_atomically

MAX_DOCUMENTS = 200_000
MAX_TOKENS = 3_000_000
MAX_SPARSE_BYTES = 512 * 1024 * 1024


def select_training_items(events: pd.DataFrame, items: pd.DataFrame, train: pd.DataFrame):
    """Recupera solo ítems de eventos del corte y reconcilia conteos con la matriz."""
    key = ["process_ocid", "award_id", "supplier_id"]
    valid = (
        events.award_date.notna()
        & events.award_year.lt(2023)
        & events.entity_id.notna()
        & events.supplier_id.notna()
        & events.entity_id.str.strip().ne("")
        & events.supplier_id.str.strip().ne("")
    )
    eligible = events.loc[valid, key + ["entity_id"]]
    if eligible.duplicated(key).any() or items.duplicated(key + ["item_id"]).any():
        raise ValueError("Claves duplicadas en eventos o ítems")
    rebuilt = eligible.groupby(["entity_id", "supplier_id"]).size().rename("count").reset_index()
    reconcile = train.merge(
        rebuilt, on=["entity_id", "supplier_id"], how="outer", validate="one_to_one"
    )
    if reconcile.isna().any().any() or not reconcile.interaction_count.eq(reconcile["count"]).all():
        raise ValueError("Eventos no concilian con matriz de entrenamiento")
    return items.merge(eligible, on=key, how="inner", validate="many_to_one")


def content_rankings(items: pd.DataFrame, train: pd.DataFrame, entities: set[str], *, min_df=3):
    """TF-IDF por ítem, suma de perfiles y coseno sobre candidatos no vistos."""
    docs = items.copy()
    docs["item_description"] = docs.item_description.fillna("").astype(str).str.strip()
    docs = docs.loc[docs.item_description.ne("")].reset_index(drop=True)
    if not len(docs) or len(docs) > MAX_DOCUMENTS:
        raise ValueError("Número de documentos fuera de los límites")
    # Cada token produce como máximo un unigrama y un bigrama; evita vectorizar entradas enormes.
    tokens = sum(len(re.findall(r"(?u)\b\w\w+\b", text)) for text in docs.item_description)
    if tokens > MAX_TOKENS:
        raise ValueError(f"Demasiados tokens: {tokens}")
    vectorizer = TfidfVectorizer(
        strip_accents="unicode",
        lowercase=True,
        ngram_range=(1, 2),
        min_df=min_df,
        max_df=0.8,
        max_features=30_000,
        sublinear_tf=True,
        dtype=np.float32,
    )
    vectors = vectorizer.fit_transform(docs.item_description).tocsr()
    # Perfiles agregados contienen a lo sumo los términos de entrada; incluye copias temporales.
    estimate = int(vectors.nnz * 16 * 5 + (len(docs) + len(train)) * 64)
    if estimate > MAX_SPARSE_BYTES:
        raise ValueError(f"Memoria dispersa estimada excede límite: {estimate}")
    entity_ids = sorted(train.entity_id.unique())
    supplier_ids = sorted(train.supplier_id.unique())
    ei = {value: index for index, value in enumerate(entity_ids)}
    si = {value: index for index, value in enumerate(supplier_ids)}
    if not set(docs.entity_id).issubset(ei) or not set(docs.supplier_id).issubset(si):
        raise ValueError("Ítems con entidad o proveedor ajeno al entrenamiento")
    positions = np.arange(len(docs))
    weights = np.ones(len(docs), dtype=np.float32)
    entity_map = sparse.csr_matrix(
        (weights, (docs.entity_id.map(ei), positions)), shape=(len(ei), len(docs))
    )
    supplier_map = sparse.csr_matrix(
        (weights, (docs.supplier_id.map(si), positions)), shape=(len(si), len(docs))
    )
    entity_profiles = normalize(entity_map @ vectors, norm="l2").tocsr()
    supplier_profiles = normalize(supplier_map @ vectors, norm="l2").tocsr()
    transpose = supplier_profiles.T.tocsr()
    history = defaultdict(set)
    for row in train[["entity_id", "supplier_id"]].itertuples(index=False):
        history[row.entity_id].add(si[row.supplier_id])
    rankings = {}
    for entity in sorted(entities):
        scores = (entity_profiles.getrow(ei[entity]) @ transpose).tocsr()
        keep = ~np.isin(scores.indices, list(history[entity]))
        indices, values = scores.indices[keep], scores.data[keep]
        # supplier_ids se ordenó lexicográficamente; el índice resuelve empates.
        order = np.lexsort((indices, -values))[:20]
        rankings[entity] = [supplier_ids[index] for index in indices[order]]
    diagnostics = {
        "documents": len(docs),
        "tokens_before_vectorization": tokens,
        "terms": len(vectorizer.vocabulary_),
        "document_nonzero": int(vectors.nnz),
        "estimated_sparse_bytes": estimate,
        "entities_with_profile": int((np.diff(entity_profiles.indptr) > 0).sum()),
        "suppliers_with_profile": int((np.diff(supplier_profiles.indptr) > 0).sum()),
    }
    return rankings, diagnostics


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed/recommendation"))
    parser.add_argument(
        "--events-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument("--items-dir", type=Path, default=Path("data/processed/fact_award_item"))
    parser.add_argument(
        "--baseline-dir", type=Path, default=Path("artifacts/recommendation_baseline")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/recommendation_content"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    source, events_path, items_path = (
        args.input_dir.resolve(),
        args.events_dir.resolve(),
        args.items_dir.resolve(),
    )
    output = args.output_dir.resolve()
    stage = staging_dir(output)
    protected = (source, events_path, items_path, args.baseline_dir.resolve())
    for target in (output, stage, output.with_name(output.name + ".previous")):
        for path in protected:
            if target == path or target in path.parents or path in target.parents:
                raise ValueError("Rutas de entrada y salida solapadas")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite")
    for path in protected:
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta publicación: {path}")
    meta = json.loads((source / "_metadata.json").read_text(encoding="utf-8"))
    baseline = json.loads((args.baseline_dir / "_metadata.json").read_text(encoding="utf-8"))
    hashes = {str(p): directory_fingerprint(p) for p in protected[:3]}
    if (
        hashes[str(source)] != baseline["input_sha256"]
        or hashes[str(events_path)] != meta["input_sha256"]
    ):
        raise ValueError("Las fuentes cambiaron desde preparación y baseline")
    train = read_table(source / "2023/train", ["entity_id", "supplier_id", "interaction_count"])
    future = read_table(
        source / "2023/future_pairs", ["entity_id", "supplier_id", "eligible_positive"]
    )
    key = ["process_ocid", "award_id", "supplier_id"]
    events = read_table(events_path, key + ["entity_id", "award_date", "award_year"])
    items = read_table(items_path, key + ["item_id", "item_description"])
    items = select_training_items(events, items, train)
    positives = defaultdict(set)
    for row in future.loc[future.eligible_positive].itertuples(index=False):
        positives[row.entity_id].add(row.supplier_id)
    if not positives:
        raise ValueError("No hay positivos evaluables")
    rankings, diagnostics = content_rankings(items, train, set(positives))
    history = train.groupby("entity_id").supplier_id.nunique().to_dict()
    catalog = train.supplier_id.nunique()
    counts = {entity: catalog - history[entity] for entity in positives}
    metrics = pd.concat([score_rankings(rankings, positives, counts, k) for k in (10, 20)])
    rank_rows = [
        {"entity_id": entity, "supplier_id": supplier, "rank": position}
        for entity, values in rankings.items()
        for position, supplier in enumerate(values, 1)
    ]
    summary = {
        str(k): {key: float(group[key].mean()) for key in ("recall", "precision", "ndcg")}
        for k, group in metrics.groupby("k")
    }
    if any(directory_fingerprint(p) != hashes[str(p)] for p in protected[:3]):
        raise RuntimeError("Una entrada cambió durante la evaluación")
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    pd.DataFrame(rank_rows, columns=["entity_id", "supplier_id", "rank"]).to_parquet(
        stage / "rankings.parquet", index=False
    )
    metrics.to_parquet(stage / "metrics_by_entity.parquet", index=False)
    write_json_atomically(
        stage / "_metadata.json",
        {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_sha256": hashes[str(source)],
            "items_sha256": hashes[str(items_path)],
            "events_sha256": hashes[str(events_path)],
            "cut": 2023,
            "method": "TF-IDF de descripciones de ítems y coseno de perfiles",
            "parameters": {
                "min_df": 3,
                "max_df": 0.8,
                "max_features": 30000,
                "ngram_range": [1, 2],
                "sublinear_tf": True,
                "strip_accents": "unicode",
            },
            "entities_evaluated": len(positives),
            "entities_with_ranking": sum(bool(v) for v in rankings.values()),
            "catalog_size": catalog,
            "provider_coverage": len({r["supplier_id"] for r in rank_rows}) / catalog,
            "metrics_macro": summary,
            "diagnostics": diagnostics,
            "availability": meta["availability"],
            "evaluation": "validación exploratoria 2023; prueba 2024 ya observada",
        },
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"Contenido exploratorio publicado: {output}; {summary}; {diagnostics}")


if __name__ == "__main__":
    run()
