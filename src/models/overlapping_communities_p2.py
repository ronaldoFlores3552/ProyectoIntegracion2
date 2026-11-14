"""Detecta comunidades solapadas BigCLAM en el subgrafo reproducible de Puno."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import community as community_louvain
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--department", default="PUNO")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/overlap_puno"))
    parser.add_argument("--min-recurrent-processes", type=int, default=5)
    parser.add_argument("--max-recurrent-participants", type=int, default=30)
    parser.add_argument("--components", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=150)
    parser.add_argument("--learning-rate", type=float, default=0.0001)
    parser.add_argument("--membership-fraction", type=float, default=0.5)
    parser.add_argument("--negative-samples", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_puno_projection(
    participation_dir: Path,
    department: str,
    min_recurrent_processes: int,
    max_recurrent_participants: int,
) -> tuple[nx.Graph, list[str], dict[str, int]]:
    """Build the same recurrent-participant, k-limited projection used by the Puno null."""
    if not (participation_dir / "fact_tenderer" / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta fact_tenderer publicado.")
    if not (participation_dir / "dim_buyer" / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta dim_buyer publicado.")
    rows = pd.read_parquet(
        participation_dir / "fact_tenderer",
        columns=["process_ocid", "buyer_id", "participant_id"],
    ).drop_duplicates()
    buyers = pd.read_parquet(participation_dir / "dim_buyer", columns=["buyer_id", "department"])
    rows = rows.merge(buyers, on="buyer_id", how="inner", validate="many_to_one")
    rows = rows.loc[
        rows.department.eq(department), ["process_ocid", "participant_id"]
    ].drop_duplicates()
    recurrent = rows.groupby("participant_id").process_ocid.nunique()
    rows = rows.loc[
        rows.participant_id.isin(recurrent[recurrent.ge(min_recurrent_processes)].index)
    ]
    groups = rows.groupby("process_ocid").participant_id.agg(lambda values: sorted(set(values)))
    graph = nx.Graph()
    processable = 0
    excluded_large = 0
    for participants in groups:
        size = len(participants)
        if size > max_recurrent_participants:
            excluded_large += 1
            continue
        if size < 2:
            continue
        processable += 1
        weight = 1.0 / (size - 1)
        for left, right in combinations(participants, 2):
            previous = graph.get_edge_data(left, right, {}).get("weight", 0.0)
            graph.add_edge(left, right, weight=previous + weight)
    nodes = sorted(graph.nodes)
    return graph, nodes, {
        "department_processes_after_recurrence_filter": int(len(groups)),
        "projectable_processes": processable,
        "excluded_processes_above_maximum": excluded_large,
        "recurrent_participants_before_projection": int(rows.participant_id.nunique()),
    }


def bigclam_objective(affiliations: np.ndarray, edges: np.ndarray) -> float:
    """Return BigCLAM's unweighted log-likelihood over one undirected graph."""
    if len(edges) == 0:
        raise ValueError("BigCLAM requiere al menos una arista.")
    edge_scores = np.einsum("ij,ij->i", affiliations[edges[:, 0]], affiliations[edges[:, 1]])
    edge_log_probability = np.log(-np.expm1(-np.maximum(edge_scores, 1e-12))).sum()
    total = affiliations.sum(axis=0)
    all_pair_scores = 0.5 * (float(total @ total) - float((affiliations * affiliations).sum()))
    nonedge_scores = all_pair_scores - float(edge_scores.sum())
    return float(edge_log_probability - nonedge_scores)


def fit_bigclam(
    node_count: int,
    edges: np.ndarray,
    components: int,
    iterations: int,
    learning_rate: float,
    seed: int,
) -> tuple[np.ndarray, pd.DataFrame]:
    """Fit a non-negative BigCLAM model with monotone projected line search."""
    if node_count < 2 or components < 1 or iterations < 1 or learning_rate <= 0:
        raise ValueError("Nodos, componentes, iteraciones y learning rate deben ser positivos.")
    rng = np.random.default_rng(seed)
    affiliations = rng.gamma(shape=1.0, scale=0.1, size=(node_count, components)) + 1e-8
    objective = bigclam_objective(affiliations, edges)
    rows: list[dict[str, float | int]] = [
        {"iteration": 0, "objective": objective, "learning_rate": learning_rate}
    ]
    rate = learning_rate
    for iteration in range(1, iterations + 1):
        total = affiliations.sum(axis=0)
        gradient = -(total - affiliations)
        edge_scores = np.einsum(
            "ij,ij->i", affiliations[edges[:, 0]], affiliations[edges[:, 1]]
        )
        attraction = 1.0 / -np.expm1(-np.maximum(edge_scores, 1e-12))
        np.add.at(gradient, edges[:, 0], affiliations[edges[:, 1]] * attraction[:, None])
        np.add.at(gradient, edges[:, 1], affiliations[edges[:, 0]] * attraction[:, None])
        candidate_rate = rate
        for _ in range(20):
            candidate = np.maximum(affiliations + candidate_rate * gradient, 1e-10)
            candidate_objective = bigclam_objective(candidate, edges)
            if candidate_objective >= objective:
                break
            candidate_rate *= 0.5
        else:
            break
        relative_gain = (candidate_objective - objective) / max(1.0, abs(objective))
        affiliations, objective = candidate, candidate_objective
        rate = min(candidate_rate * 1.05, learning_rate)
        rows.append(
            {
                "iteration": iteration,
                "objective": objective,
                "learning_rate": candidate_rate,
                "relative_gain": relative_gain,
            }
        )
        if relative_gain < 1e-7:
            break
    return affiliations, pd.DataFrame(rows)


def memberships_from_affiliations(
    affiliations: np.ndarray, membership_fraction: float
) -> list[tuple[int, int, float, int]]:
    """Assign each node to all components near its strongest non-negative affiliation."""
    if not 0 < membership_fraction <= 1:
        raise ValueError("membership_fraction debe estar en (0, 1].")
    output: list[tuple[int, int, float, int]] = []
    for node, values in enumerate(affiliations):
        maximum = float(values.max())
        selected = np.flatnonzero(values >= maximum * membership_fraction)
        for component in selected:
            rank = int((values > values[component]).sum() + 1)
            output.append((node, int(component), float(values[component]), rank))
    return output


def sampled_reconstruction_metrics(
    affiliations: np.ndarray, edges: np.ndarray, negative_samples: int, seed: int
) -> dict[str, float | int]:
    """Evaluate edge scores against sampled absent pairs; this is fit, not prediction."""
    node_count = len(affiliations)
    possible = node_count * (node_count - 1) // 2
    edge_codes = {int(left) * node_count + int(right) for left, right in edges}
    available = possible - len(edge_codes)
    sample_size = min(negative_samples, len(edges), available)
    if sample_size < 1:
        raise ValueError("No hay suficientes pares ausentes para el diagnóstico de reconstrucción.")
    rng = np.random.default_rng(seed)
    selected_edges = edges[rng.choice(len(edges), size=sample_size, replace=False)]
    negatives: list[tuple[int, int]] = []
    while len(negatives) < sample_size:
        left, right = sorted(rng.choice(node_count, size=2, replace=False))
        if left * node_count + right not in edge_codes:
            edge_codes.add(left * node_count + right)
            negatives.append((int(left), int(right)))
    pairs = np.vstack([selected_edges, np.asarray(negatives, dtype=int)])
    pair_scores = np.einsum("ij,ij->i", affiliations[pairs[:, 0]], affiliations[pairs[:, 1]])
    scores = 1.0 - np.exp(-pair_scores)
    labels = np.r_[np.ones(sample_size), np.zeros(sample_size)]
    return {
        "positive_edges_sampled": int(sample_size),
        "negative_pairs_sampled": int(sample_size),
        "sampled_reconstruction_auc": float(roc_auc_score(labels, scores)),
        "sampled_reconstruction_average_precision": float(average_precision_score(labels, scores)),
    }


def compare_with_louvain(
    nodes: list[str], graph: nx.Graph, memberships: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    partition = community_louvain.best_partition(
        graph, weight="weight", resolution=1.5, random_state=42
    )
    louvain = pd.DataFrame(
        {"participant_id": nodes, "louvain_community": [partition[node] for node in nodes]}
    )
    rows: list[dict[str, float | int]] = []
    for component, group in memberships.groupby("community"):
        counts = (
            group.merge(louvain, on="participant_id", validate="many_to_one")
            .louvain_community.value_counts()
        )
        dominant = int(counts.index[0])
        overlap = int(counts.iloc[0])
        louvain_size = int((louvain.louvain_community == dominant).sum())
        component_size = int(len(group))
        rows.append(
            {
                "community": int(component),
                "members": component_size,
                "dominant_louvain_community": dominant,
                "overlap_members": overlap,
                "dominant_louvain_members": louvain_size,
                "jaccard_with_dominant_louvain": overlap
                / (component_size + louvain_size - overlap),
            }
        )
    return louvain, pd.DataFrame(rows).sort_values("community")


def run() -> None:
    args = parse_args()
    if args.min_recurrent_processes < 1 or args.max_recurrent_participants < 2:
        raise ValueError("Los límites de recurrencia y tamaño de proceso no son válidos.")
    participation_dir, output_dir = args.participation_dir.resolve(), args.output_dir.resolve()
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    graph, nodes, coverage = build_puno_projection(
        participation_dir,
        args.department,
        args.min_recurrent_processes,
        args.max_recurrent_participants,
    )
    if graph.number_of_nodes() < 2 or graph.number_of_edges() < 1:
        raise ValueError("El subgrafo seleccionado no permite ajustar BigCLAM.")
    node_codes = {node: index for index, node in enumerate(nodes)}
    edges = np.asarray(
        [(node_codes[left], node_codes[right]) for left, right in graph.edges], dtype=int
    )
    affiliations, diagnostics = fit_bigclam(
        len(nodes), edges, args.components, args.iterations, args.learning_rate, args.seed
    )
    membership_rows = memberships_from_affiliations(affiliations, args.membership_fraction)
    memberships = pd.DataFrame(
        membership_rows, columns=["node_index", "community", "affiliation", "rank"]
    )
    memberships.insert(
        0, "participant_id", [nodes[index] for index in memberships.pop("node_index")]
    )
    affiliation_table = pd.DataFrame(
        affiliations, index=pd.Index(nodes, name="participant_id"), columns=range(args.components)
    ).rename(columns=lambda component: f"community_{component}").reset_index()
    louvain, comparison = compare_with_louvain(nodes, graph, memberships)
    reconstruction = sampled_reconstruction_metrics(
        affiliations, edges, args.negative_samples, args.seed
    )
    memberships_per_node = memberships.groupby("participant_id").size()
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    memberships.to_parquet(stage / "memberships.parquet", index=False)
    affiliation_table.to_parquet(stage / "affiliations.parquet", index=False)
    louvain.to_parquet(stage / "louvain_memberships.parquet", index=False)
    comparison.to_csv(stage / "overlap_louvain_comparison.csv", index=False)
    diagnostics.to_csv(stage / "optimization_diagnostics.csv", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "BigCLAM no negativo, optimización por ascenso proyectado con búsqueda de línea",
        "scope": "Subgrafo de participantes reportados de Puno; no se extrapola al país.",
        "inputs": {
            "participation_dir": str(participation_dir),
            "participation_metadata_sha256": sha256_file(participation_dir / "_metadata.json"),
        },
        "parameters": {
            "department": args.department,
            "min_recurrent_processes": args.min_recurrent_processes,
            "max_recurrent_participants": args.max_recurrent_participants,
            "components": args.components,
            "iterations_requested": args.iterations,
            "iterations_completed": int(diagnostics.iteration.max()),
            "learning_rate_initial": args.learning_rate,
            "membership_fraction": args.membership_fraction,
            "seed": args.seed,
        },
        "coverage": {
            **coverage,
            "nodes_in_projection": graph.number_of_nodes(),
            "edges_in_projection": graph.number_of_edges(),
            "nodes_with_membership": int(memberships_per_node.size),
            "memberships": int(len(memberships)),
            "share_nodes_in_multiple_communities": float((memberships_per_node > 1).mean()),
        },
        "diagnostics": {
            "objective_initial": float(diagnostics.iloc[0].objective),
            "objective_final": float(diagnostics.iloc[-1].objective),
            **reconstruction,
            "warning": (
                "Las métricas usan el mismo grafo ajustado y pares ausentes muestreados; "
                "diagnostican ajuste, no predicción prospectiva."
            ),
        },
        "comparison": {
            "louvain_resolution": 1.5,
            "louvain_seed": 42,
            "interpretation": (
                "La comparación indica solapamiento de membresías, no mercados reales "
                "ni evidencia de colusión."
            ),
        },
        "files": [
            "memberships.parquet",
            "affiliations.parquet",
            "louvain_memberships.parquet",
            "overlap_louvain_comparison.csv",
            "optimization_diagnostics.csv",
        ],
    }
    (stage / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Comunidades solapadas BigCLAM publicadas: {output_dir}")


if __name__ == "__main__":
    run()
