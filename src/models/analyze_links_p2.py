"""Calcula HITS y PageRank reproducibles sobre los grafos P2 aprobados."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import spearmanr

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market-dir", type=Path, default=Path("data/processed/market_p2"))
    parser.add_argument("--projection-dir", type=Path, default=Path("data/processed/market_p2_k30"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/links"))
    parser.add_argument("--damping", type=float, nargs="+", default=[0.75, 0.85, 0.95])
    parser.add_argument("--tolerance", type=float, default=1e-10)
    parser.add_argument("--max-iterations", type=int, default=1000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def hits_bipartite(
    matrix: sparse.csr_matrix, tolerance: float, max_iterations: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return buyer hubs and supplier authorities by power iteration."""
    hubs = np.full(matrix.shape[0], 1 / np.sqrt(matrix.shape[0]))
    authorities = np.full(matrix.shape[1], 1 / np.sqrt(matrix.shape[1]))
    for iteration in range(1, max_iterations + 1):
        next_authorities = _normalize(matrix.T @ hubs)
        next_hubs = _normalize(matrix @ next_authorities)
        if (
            max(np.max(np.abs(next_hubs - hubs)), np.max(np.abs(next_authorities - authorities)))
            <= tolerance
        ):
            return next_hubs, next_authorities, iteration
        hubs, authorities = next_hubs, next_authorities
    raise RuntimeError("HITS no convergió dentro del máximo de iteraciones.")


def pagerank_weighted(
    matrix: sparse.csr_matrix, damping: float, tolerance: float, max_iterations: int
) -> tuple[np.ndarray, int]:
    """Run weighted PageRank on a symmetric sparse adjacency matrix."""
    node_count = matrix.shape[0]
    strength = np.asarray(matrix.sum(axis=1)).ravel()
    if np.any(strength <= 0):
        raise ValueError("PageRank requiere nodos sin fuerza cero en la proyección.")
    rank = np.full(node_count, 1 / node_count)
    for iteration in range(1, max_iterations + 1):
        next_rank = damping * (matrix.T @ (rank / strength)) + (1 - damping) / node_count
        if np.abs(next_rank - rank).sum() <= tolerance:
            return next_rank, iteration
        rank = next_rank
    raise RuntimeError("PageRank no convergió dentro del máximo de iteraciones.")


def _require_published(path: Path, child: str) -> None:
    if not (path / "_SUCCESS").is_file() or not (path / child / "_SUCCESS").is_file():
        raise FileNotFoundError(f"Falta una entrada publicada completa: {path / child}")


def _sparse_bipartite(edges: pd.DataFrame) -> tuple[sparse.csr_matrix, pd.Index, pd.Index]:
    buyer_codes, buyers = pd.factorize(edges["buyer_id"], sort=True)
    supplier_codes, suppliers = pd.factorize(edges["supplier_id"], sort=True)
    matrix = sparse.coo_matrix(
        (edges["award_count"].to_numpy(float), (buyer_codes, supplier_codes)),
        shape=(len(buyers), len(suppliers)),
    ).tocsr()
    return matrix, buyers, suppliers


def _sparse_projection(
    edges: pd.DataFrame,
) -> tuple[sparse.csr_matrix, pd.Index, np.ndarray, np.ndarray]:
    labels = pd.Index(
        pd.concat(
            [edges["participant_left"], edges["participant_right"]], ignore_index=True
        ).unique()
    ).sort_values()
    codes = pd.Series(np.arange(len(labels), dtype=np.int64), index=labels)
    left = codes.loc[edges["participant_left"]].to_numpy()
    right = codes.loc[edges["participant_right"]].to_numpy()
    weight = edges["newman_weight"].to_numpy(float)
    matrix = sparse.coo_matrix(
        (
            np.concatenate([weight, weight]),
            (np.concatenate([left, right]), np.concatenate([right, left])),
        ),
        shape=(len(labels), len(labels)),
    ).tocsr()
    degree = np.bincount(np.concatenate([left, right]), minlength=len(labels))
    strength = np.asarray(matrix.sum(axis=1)).ravel()
    return matrix, labels, degree, strength


def _rank(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="min", ascending=False).to_numpy(dtype=np.int64)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run() -> None:
    args = parse_args()
    if not all(0 < value < 1 for value in args.damping):
        raise ValueError("Cada amortiguamiento debe estar entre 0 y 1.")
    if args.tolerance <= 0 or args.max_iterations < 1:
        raise ValueError("La tolerancia y el máximo de iteraciones deben ser positivos.")
    market_dir, projection_dir, output_dir = (
        args.market_dir.resolve(),
        args.projection_dir.resolve(),
        args.output_dir.resolve(),
    )
    _require_published(market_dir, "graph_award_edges")
    _require_published(projection_dir, "coparticipation_edges")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    award_edges = pd.read_parquet(market_dir / "graph_award_edges")
    projection_edges = pd.read_parquet(projection_dir / "coparticipation_edges")
    bipartite, buyers, suppliers = _sparse_bipartite(award_edges)
    hubs, authorities, hits_iterations = hits_bipartite(
        bipartite, args.tolerance, args.max_iterations
    )
    buyer_strength = np.asarray(bipartite.sum(axis=1)).ravel()
    supplier_strength = np.asarray(bipartite.sum(axis=0)).ravel()
    buyer_degree = np.diff(bipartite.indptr)
    supplier_degree = np.diff(bipartite.tocsc().indptr)
    hub_table = pd.DataFrame(
        {
            "buyer_id": buyers,
            "hub_score": hubs,
            "award_strength": buyer_strength,
            "distinct_suppliers": buyer_degree,
            "hub_rank": _rank(hubs),
        }
    )
    authority_table = pd.DataFrame(
        {
            "supplier_id": suppliers,
            "authority_score": authorities,
            "award_strength": supplier_strength,
            "distinct_buyers": supplier_degree,
            "authority_rank": _rank(authorities),
        }
    )
    projection, participants, degree, strength = _sparse_projection(projection_edges)
    pagerank_tables: list[pd.DataFrame] = []
    pagerank_iterations: dict[str, int] = {}
    correlations: list[dict[str, float]] = []
    pagerank_scores: dict[float, np.ndarray] = {}
    for damping in sorted(set(args.damping)):
        score, iterations = pagerank_weighted(
            projection, damping, args.tolerance, args.max_iterations
        )
        pagerank_iterations[str(damping)] = iterations
        pagerank_scores[damping] = score
        pagerank_tables.append(
            pd.DataFrame(
                {
                    "participant_id": participants,
                    "damping": damping,
                    "pagerank_score": score,
                    "pagerank_rank": _rank(score),
                    "degree": degree,
                    "strength": strength,
                }
            )
        )
        correlations.append(
            {
                "damping": damping,
                "spearman_pagerank_degree": float(spearmanr(score, degree).statistic),
                "spearman_pagerank_strength": float(spearmanr(score, strength).statistic),
            }
        )
    damping_sensitivity = [
        {
            "left_damping": left,
            "right_damping": right,
            "spearman_rank": float(
                spearmanr(pagerank_scores[left], pagerank_scores[right]).statistic
            ),
        }
        for index, left in enumerate(sorted(pagerank_scores))
        for right in sorted(pagerank_scores)[index + 1 :]
    ]
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    hub_table.to_parquet(stage / "buyer_hubs.parquet", index=False)
    authority_table.to_parquet(stage / "supplier_authorities.parquet", index=False)
    pd.concat(pagerank_tables, ignore_index=True).to_parquet(
        stage / "pagerank_nodes.parquet", index=False
    )
    pd.DataFrame(correlations).to_csv(stage / "pagerank_correlations.csv", index=False)
    pd.DataFrame(damping_sensitivity).to_csv(
        stage / "pagerank_damping_sensitivity.csv", index=False
    )
    metadata: dict[str, object] = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "hits_market_dir": str(market_dir),
            "pagerank_projection_dir": str(projection_dir),
        },
        "hits": {
            "weight": "award_count",
            "buyers": len(buyers),
            "suppliers": len(suppliers),
            "edges": int(bipartite.nnz),
            "iterations": hits_iterations,
        },
        "pagerank": {
            "weight": "newman_weight",
            "nodes": len(participants),
            "undirected_edges": int(projection_edges.shape[0]),
            "damping": sorted(set(args.damping)),
            "iterations": pagerank_iterations,
            "tolerance": args.tolerance,
            "max_iterations": args.max_iterations,
            "damping_rank_sensitivity": damping_sensitivity,
        },
        "files": [
            "buyer_hubs.parquet",
            "supplier_authorities.parquet",
            "pagerank_nodes.parquet",
            "pagerank_correlations.csv",
            "pagerank_damping_sensitivity.csv",
        ],
    }
    _write_json(stage / "metadata.json", metadata)
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Centralidades P2 publicadas: {output_dir}")


if __name__ == "__main__":
    run()
