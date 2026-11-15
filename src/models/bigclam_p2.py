"""Comunidades solapadas BigCLAM en el subgrafo departamental de co-participación P2."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import community as community_louvain
import networkx as nx
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.metrics import average_precision_score, roc_auc_score

from src.models.partition_subgraph_p2 import (
    department_graph,
    department_rows,
    giant_component,
    participant_attributes,
)
from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--department", default="PUNO")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/bigclam"))
    parser.add_argument("--min-recurrent-processes", type=int, default=5)
    parser.add_argument("--max-recurrent-participants", type=int, default=30)
    parser.add_argument(
        "--communities", type=int, nargs="+", default=[5, 10, 20, 30, 40, 50, 70, 100]
    )
    parser.add_argument("--holdout", type=float, default=0.1)
    parser.add_argument("--tolerance", type=float, default=0.005)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sensitivity-seeds", type=int, nargs="*", default=[7, 99])
    parser.add_argument("--threshold-factors", type=float, nargs="+", default=[0.5, 1.0, 2.0])
    parser.add_argument("--louvain-resolution", type=float, default=1.5)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def seed_neighborhoods(adjacency: sparse.csr_matrix, k: int) -> np.ndarray:
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    blocked = np.zeros(adjacency.shape[0], dtype=bool)
    factors = np.zeros((adjacency.shape[0], k))
    chosen = 0
    for node in np.argsort(-degree, kind="stable"):
        if blocked[node]:
            continue
        neighbors = adjacency.indices[adjacency.indptr[node] : adjacency.indptr[node + 1]]
        factors[node, chosen] = 1.0
        factors[neighbors, chosen] = 1.0
        blocked[node] = True
        blocked[neighbors] = True
        chosen += 1
        if chosen == k:
            break
    return factors


def symmetric(pairs: np.ndarray, n: int) -> sparse.csr_matrix:
    if len(pairs) == 0:
        return sparse.csr_matrix((n, n))
    values = np.ones(2 * len(pairs))
    return sparse.coo_matrix(
        (values, (np.r_[pairs[:, 0], pairs[:, 1]], np.r_[pairs[:, 1], pairs[:, 0]])),
        shape=(n, n),
    ).tocsr()


def pair_dots(factors: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    return np.einsum("ij,ij->i", factors[rows], factors[cols])


def log_likelihood(
    factors: np.ndarray, rows: np.ndarray, cols: np.ndarray, excluded: np.ndarray | None = None
) -> float:
    dots = pair_dots(factors, rows, cols)
    edges = np.log1p(-np.exp(-np.clip(dots, 1e-10, None))).sum()
    total = factors.sum(axis=0)
    non_edges = 0.5 * (total @ total - np.einsum("ij,ij->", factors, factors)) - dots.sum()
    if excluded is not None and len(excluded):
        non_edges -= pair_dots(factors, excluded[:, 0], excluded[:, 1]).sum()
    return float(edges - non_edges)


def node_loglik(values: np.ndarray, neighbors: np.ndarray, outside: np.ndarray) -> float:
    dots = np.clip(neighbors @ values, 1e-10, None)
    return float(np.log1p(-np.exp(-dots)).sum() - values @ outside)


def update_node(
    current: np.ndarray, neighbors: np.ndarray, outside: np.ndarray
) -> np.ndarray | None:
    dots = np.clip(neighbors @ current, 1e-10, None)
    gradient = (neighbors * (np.exp(-dots) / -np.expm1(-dots))[:, None]).sum(axis=0) - outside
    scale = np.abs(gradient).max()
    if scale == 0:
        return None
    base, step = node_loglik(current, neighbors, outside), 1.0 / max(scale, 1.0)
    for _ in range(40):
        candidate = np.clip(current + step * gradient, 0.0, 1e3)
        if node_loglik(candidate, neighbors, outside) >= base + 1e-4 * gradient @ (
            candidate - current
        ):
            return candidate
        step *= 0.5
    return None


def fit_bigclam(
    adjacency: sparse.csr_matrix,
    k: int,
    iterations: int,
    seed: int,
    excluded: np.ndarray | None = None,
) -> tuple[np.ndarray, list[float]]:
    rng = np.random.default_rng(seed)
    n = adjacency.shape[0]
    factors = seed_neighborhoods(adjacency, k) + rng.uniform(0, 0.01, (n, k))
    upper = sparse.triu(adjacency, k=1).tocoo()
    rows, cols = upper.row, upper.col
    hidden = symmetric(excluded if excluded is not None else np.empty((0, 2), int), n)
    indptr, indices = adjacency.indptr, adjacency.indices
    total = factors.sum(axis=0)
    history = [log_likelihood(factors, rows, cols, excluded)]
    for _ in range(iterations):
        for node in rng.permutation(n):
            current = factors[node].copy()
            neighbors = factors[indices[indptr[node] : indptr[node + 1]]]
            partners = hidden.indices[hidden.indptr[node] : hidden.indptr[node + 1]]
            outside = total - current - neighbors.sum(axis=0) - factors[partners].sum(axis=0)
            candidate = update_node(current, neighbors, outside)
            if candidate is not None:
                total += candidate - current
                factors[node] = candidate
        history.append(log_likelihood(factors, rows, cols, excluded))
        if abs(history[-1] - history[-2]) < 1e-5 * abs(history[-2]):
            break
    return factors, history


def holdout_split(
    adjacency: sparse.csr_matrix, share: float, rng: np.random.Generator
) -> tuple[sparse.csr_matrix, np.ndarray, np.ndarray]:
    upper = sparse.triu(adjacency, k=1).tocoo()
    edges = np.column_stack([upper.row, upper.col])
    hidden = rng.choice(len(edges), int(share * len(edges)), replace=False)
    keep = np.setdiff1d(np.arange(len(edges)), hidden)
    n = adjacency.shape[0]
    existing = set(map(tuple, edges.tolist()))
    negatives: set[tuple[int, int]] = set()
    while len(negatives) < len(hidden):
        left, right = sorted(rng.choice(n, 2, replace=False).tolist())
        if (left, right) not in existing:
            negatives.add((left, right))
    return symmetric(edges[keep], n), edges[hidden], np.array(sorted(negatives))


def heldout_metrics(
    factors: np.ndarray, positives: np.ndarray, negatives: np.ndarray
) -> dict[str, float]:
    pairs = np.vstack([positives, negatives])
    scores = -np.expm1(-pair_dots(factors, pairs[:, 0], pairs[:, 1]))
    truth = np.r_[np.ones(len(positives)), np.zeros(len(negatives))]
    return {
        "heldout_auc": float(roc_auc_score(truth, scores)),
        "heldout_average_precision": float(average_precision_score(truth, scores)),
    }


def membership_threshold(nodes: int, edges: int) -> float:
    density = 2 * edges / (nodes * (nodes - 1))
    return float(np.sqrt(-np.log(1 - density)))


def sensitivity_factors(factors: list[float]) -> list[float]:
    return sorted(set(factors) | {1.0})


def membership_shares(factors: np.ndarray, threshold: float) -> dict[str, float]:
    per_node = (factors > threshold).sum(axis=1)
    return {
        "share_nodes_without_community": float((per_node == 0).mean()),
        "share_nodes_overlapping": float((per_node > 1).mean()),
    }


def run() -> None:
    args = parse_args()
    participation_dir, output_dir = args.participation_dir.resolve(), args.output_dir.resolve()
    if not (participation_dir / "fact_tenderer" / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta fact_tenderer publicado.")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    rows = department_rows(participation_dir, args.department, args.min_recurrent_processes)
    giant = giant_component(department_graph(rows, args.max_recurrent_participants))
    nodes = sorted(giant.nodes)
    adjacency = nx.to_scipy_sparse_array(giant, nodelist=nodes, weight=None, format="csr")
    adjacency = sparse.csr_matrix(adjacency)
    rng = np.random.default_rng(args.seed)
    train, positives, negatives = holdout_split(adjacency, args.holdout, rng)

    selection = []
    for k in sorted(set(args.communities)):
        factors, history = fit_bigclam(
            train, k, args.iterations, args.seed, np.vstack([positives, negatives])
        )
        selection.append(
            {
                "communities": k,
                **heldout_metrics(factors, positives, negatives),
                "train_loglik": history[-1],
                "iterations": len(history) - 1,
                "converged": len(history) - 1 < args.iterations,
            }
        )
    selection = pd.DataFrame(selection)
    eligible = selection.loc[selection.heldout_auc >= selection.heldout_auc.max() - args.tolerance]
    best_k = int(eligible.communities.min())
    factors, history = fit_bigclam(adjacency, best_k, args.iterations, args.seed)
    threshold = membership_threshold(len(nodes), giant.number_of_edges())

    fits = {args.seed: (factors, history)}
    for seed in args.sensitivity_seeds:
        if seed not in fits:
            fits[seed] = fit_bigclam(adjacency, best_k, args.iterations, seed)
    sensitivity = pd.DataFrame(
        [
            {
                "seed": seed,
                "threshold_factor": factor,
                "threshold": factor * threshold,
                "iterations": len(fit_history) - 1,
                "converged": len(fit_history) - 1 < args.iterations,
                **membership_shares(fit_factors, factor * threshold),
            }
            for seed, (fit_factors, fit_history) in sorted(fits.items())
            for factor in sensitivity_factors(args.threshold_factors)
        ]
    )

    member = factors > threshold
    memberships = pd.DataFrame(
        [
            {"participant_id": nodes[i], "community": int(c), "affiliation": float(factors[i, c])}
            for i, c in zip(*np.nonzero(member), strict=True)
        ]
    )
    per_node = member.sum(axis=1)
    upper = sparse.triu(adjacency, k=1).tocoo()
    edge_dots = pair_dots(factors, upper.row, upper.col)
    sizes = member.sum(axis=0)

    louvain = community_louvain.best_partition(
        giant, weight="weight", resolution=args.louvain_resolution, random_state=args.seed
    )
    louvain_groups: dict[int, set[str]] = {}
    for node, label in louvain.items():
        louvain_groups.setdefault(label, set()).add(node)
    attributes = participant_attributes(participation_dir, rows)
    communities = []
    for c in range(best_k):
        group = {nodes[i] for i in np.nonzero(member[:, c])[0]}
        if not group:
            continue
        jaccard = max(len(group & g) / len(group | g) for g in louvain_groups.values())
        segments = attributes.reindex(sorted(group)).dominant_segment.dropna()
        provinces = attributes.reindex(sorted(group)).dominant_province.dropna()
        communities.append(
            {
                "community": c,
                "members": len(group),
                "members_in_other_communities": int((per_node[member[:, c]] > 1).sum()),
                "best_louvain_jaccard": float(jaccard),
                "top_segment": segments.mode().iloc[0] if len(segments) else None,
                "top_segment_share": float(segments.value_counts(normalize=True).iloc[0])
                if len(segments)
                else 0.0,
                "top_province": provinces.mode().iloc[0] if len(provinces) else None,
                "top_province_share": float(provinces.value_counts(normalize=True).iloc[0])
                if len(provinces)
                else 0.0,
            }
        )

    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    selection.to_csv(stage / "model_selection.csv", index=False)
    memberships.to_parquet(stage / "memberships.parquet", index=False)
    pd.DataFrame(communities).to_csv(stage / "communities.csv", index=False)
    sensitivity.to_csv(stage / "sensitivity.csv", index=False)
    pd.DataFrame({"iteration": range(len(history)), "loglik": history}).to_csv(
        stage / "optimization_diagnostics.csv", index=False
    )
    affiliations = pd.DataFrame(factors, columns=[f"community_{c}" for c in range(best_k)])
    affiliations.insert(0, "participant_id", nodes)
    affiliations["memberships"] = per_node
    affiliations["louvain_community"] = [louvain[node] for node in nodes]
    affiliations.to_parquet(stage / "affiliations.parquet", index=False)
    selected = selection.loc[selection.communities == best_k].iloc[0]
    overlap_by_seed = sensitivity.loc[sensitivity.threshold_factor == 1.0].share_nodes_overlapping
    summary = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "department": args.department,
        "scope": "componente gigante de la proyección binaria de participantes recurrentes",
        "min_recurrent_processes": args.min_recurrent_processes,
        "max_recurrent_participants": args.max_recurrent_participants,
        "nodes": len(nodes),
        "edges": giant.number_of_edges(),
        "edge_rule": "arista binaria si la proyección normalizada tiene peso positivo",
        "selected_communities": best_k,
        "selection_rule": f"menor K con AUC a {args.tolerance} o menos del mejor",
        "heldout_protocol": (
            "pares reservados y el mismo número de no-aristas, excluidos del objetivo; "
            "AUC y AP solo para elegir K, no son una evaluación final independiente"
        ),
        "selected_heldout_auc": float(selected.heldout_auc),
        "selected_heldout_average_precision": float(selected.heldout_average_precision),
        "nodes_all_zero": int((factors.max(axis=1) <= 1e-8).sum()),
        "edges_probability_below_1e_4": int((-np.expm1(-edge_dots) < 1e-4).sum()),
        "holdout_share": args.holdout,
        "membership_threshold": threshold,
        "share_nodes_without_community": float((per_node == 0).mean()),
        "share_nodes_overlapping": float((per_node > 1).mean()),
        "mean_memberships_assigned": float(per_node[per_node > 0].mean()),
        "community_size_median": float(np.median(sizes[sizes > 0])),
        "final_loglik": history[-1],
        "final_iterations": len(history) - 1,
        "final_converged": len(history) - 1 < args.iterations,
        "max_iterations": args.iterations,
        "seed": args.seed,
        "sensitivity_seeds": sorted(fits),
        "overlap_share_min_across_seeds": float(overlap_by_seed.min()),
        "overlap_share_max_across_seeds": float(overlap_by_seed.max()),
        "louvain_resolution": args.louvain_resolution,
        "louvain_seed": args.seed,
    }
    (stage / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"BigCLAM P2 publicado: {output_dir}")


if __name__ == "__main__":
    run()
