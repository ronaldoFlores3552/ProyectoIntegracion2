"""Evalúa vecindario proveedor-proveedor en la validación retrospectiva."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from src.features.build_part1 import directory_fingerprint
from src.models.recommendation_baseline import read_table, score_rankings
from src.processing.build_fact_award_item import publish_output, staging_dir
from src.quality.profile_fact_award_item import write_json_atomically

MAX_EXPANSION = 5_000_000
MAX_SPARSE_BYTES = 512 * 1024 * 1024


def neighbor_rankings(
    train: pd.DataFrame,
    entities: set[str],
    *,
    k_neighbors: int = 50,
    shrinkage: float = 20,
    top_k: int = 20,
):
    """Coseno ponderado, reducido por soporte; no crea una matriz entidad × catálogo densa."""
    supplier_ids = sorted(train.supplier_id.unique())
    entity_ids = sorted(train.entity_id.unique())
    si = {s: i for i, s in enumerate(supplier_ids)}
    ei = {e: i for i, e in enumerate(entity_ids)}
    if train.duplicated(["entity_id", "supplier_id"]).any():
        raise ValueError("Pares duplicados")
    degree = train.groupby("entity_id").size().to_numpy(dtype=np.int64)
    expansion = int(sum(int(v) * (int(v) - 1) // 2 for v in degree))
    if expansion > MAX_EXPANSION:
        raise ValueError(f"Expansión de coocurrencias excede límite: {expansion}")
    rows = train.entity_id.map(ei).to_numpy()
    cols = train.supplier_id.map(si).to_numpy()
    values = train.strength.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Fuerzas inválidas")
    matrix = sparse.csr_matrix((values, (rows, cols)), shape=(len(ei), len(si)))
    binary = matrix.copy()
    binary.data = np.ones_like(binary.data)
    norm = np.sqrt(np.asarray(matrix.power(2).sum(axis=0)).ravel())
    edges_r, edges_c, edges_v = [], [], []
    estimate = 0
    for first in range(0, len(si), 128):
        last = min(first + 128, len(si))
        partial = matrix[:, first:last]
        binary_partial = binary[:, first:last]
        row_degree = np.diff(matrix.indptr).astype(np.int64)
        block_degree = np.diff(partial.indptr).astype(np.int64)
        # Cota de entradas generadas antes de agrupar; no estima todo el pico del proceso.
        block_estimate = int(np.dot(row_degree, block_degree)) * 32 * 3
        estimate = max(estimate, block_estimate)
        if block_estimate > MAX_SPARSE_BYTES:
            raise ValueError(f"Bloque excede límite estimado: {block_estimate} bytes")
        dots = (partial.T @ matrix).tocsr()
        common = (binary_partial.T @ binary).tocsr()
        for supplier in range(first, last):
            local = supplier - first
            start, end = dots.indptr[local : local + 2]
            indices = dots.indices[start:end]
            scores = dots.data[start:end]
            common_counts = common[local, indices].toarray().ravel()
            sims = (
                scores
                / (norm[supplier] * norm[indices])
                * common_counts
                / (common_counts + shrinkage)
            )
            valid = (indices != supplier) & (sims > 0)
            indices, sims = indices[valid], sims[valid]
            order = np.lexsort((indices, -sims))[:k_neighbors]
            edges_r.extend([supplier] * len(order))
            edges_c.extend(indices[order].tolist())
            edges_v.extend(sims[order].tolist())
    neighbors = sparse.csr_matrix((edges_v, (edges_r, edges_c)), shape=(len(si), len(si)))
    rankings = {}
    for entity in sorted(entities):
        vector = matrix.getrow(ei[entity])
        scores = (vector @ neighbors).tocsr()
        keep = ~np.isin(scores.indices, vector.indices)
        indices, values = scores.indices[keep], scores.data[keep]
        order = np.lexsort((indices, -values))[:top_k]
        rankings[entity] = [supplier_ids[i] for i in indices[order]]
    return rankings, {
        "pair_expansion": expansion,
        "estimated_sparse_bytes": estimate,
        "directed_neighbor_edges": int(neighbors.nnz),
    }


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
        "--output-dir", type=Path, default=Path("artifacts/recommendation_neighbors")
    )
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
        raise ValueError("Entradas cambiaron desde auditoría, preparación o baseline")
    cut = source / "2023"
    train = read_table(cut / "train", ["entity_id", "supplier_id", "strength"])
    future = read_table(cut / "future_pairs", ["entity_id", "supplier_id", "eligible_positive"])
    positives = defaultdict(set)
    for row in future.loc[future.eligible_positive].itertuples(index=False):
        positives[row.entity_id].add(row.supplier_id)
    rankings, diagnostics = neighbor_rankings(train, set(positives))
    history = train.groupby("entity_id").supplier_id.nunique().to_dict()
    catalog_size = train.supplier_id.nunique()
    counts = {entity: catalog_size - history[entity] for entity in positives}
    metrics = pd.concat([score_rankings(rankings, positives, counts, k) for k in (10, 20)])
    rank_rows = [
        {"entity_id": entity, "supplier_id": supplier, "rank": position}
        for entity, suppliers in rankings.items()
        for position, supplier in enumerate(suppliers, 1)
    ]
    summary = {
        str(k): {key: float(group[key].mean()) for key in ("recall", "precision", "ndcg")}
        for k, group in metrics.groupby("k")
    }
    if directory_fingerprint(source) != fingerprint:
        raise RuntimeError("Entradas cambiaron durante evaluación")
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
            "input_sha256": fingerprint,
            "cut": 2023,
            "method": "coseno de proveedores",
            "neighbors": 50,
            "shrinkage": 20,
            "entities_evaluated": len(positives),
            "entities_with_ranking": sum(bool(v) for v in rankings.values()),
            "provider_coverage": len({r["supplier_id"] for r in rank_rows}) / catalog_size,
            "metrics_macro": summary,
            "diagnostics": diagnostics,
            "availability": meta["availability"],
        },
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"Vecindario publicado: {output}; {summary}; {diagnostics}")


if __name__ == "__main__":
    run()
