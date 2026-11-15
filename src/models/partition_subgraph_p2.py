"""Compara Girvan-Newman, espectral y Louvain en el subgrafo departamental de P2."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import community as community_louvain
import networkx as nx
import numpy as np
import pandas as pd
from networkx.algorithms.community import girvan_newman, modularity
from scipy import sparse
from sklearn.cluster import SpectralClustering
from sklearn.metrics import (
    adjusted_mutual_info_score,
    adjusted_rand_score,
    normalized_mutual_info_score,
)

from src.models.null_communities_p2 import build_projection
from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--department", default="PUNO")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/partition"))
    parser.add_argument("--min-recurrent-processes", type=int, default=5)
    parser.add_argument("--max-recurrent-participants", type=int, default=30)
    parser.add_argument("--spectral-k", type=int, nargs="+", default=list(range(2, 31)))
    parser.add_argument("--core-nodes", type=int, default=120)
    parser.add_argument("--max-gn-communities", type=int, default=20)
    parser.add_argument("--resolution", type=float, default=1.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def department_rows(participation_dir: Path, department: str, min_processes: int) -> pd.DataFrame:
    rows = pd.read_parquet(
        participation_dir / "fact_tenderer",
        columns=["process_ocid", "buyer_id", "participant_id"],
    ).drop_duplicates()
    buyers = pd.read_parquet(
        participation_dir / "dim_buyer", columns=["buyer_id", "department", "region"]
    )
    rows = rows.merge(buyers, on="buyer_id", how="inner", validate="many_to_one")
    rows = rows.loc[rows.department == department]
    recurrent = rows.groupby("participant_id").process_ocid.nunique()
    return rows.loc[rows.participant_id.isin(recurrent[recurrent >= min_processes].index)]


def department_graph(rows: pd.DataFrame, maximum: int) -> nx.Graph:
    participants = pd.Index(sorted(rows.participant_id.unique()))
    processes = pd.Index(sorted(rows.process_ocid.unique()))
    participant_codes = participants.get_indexer(rows.participant_id)
    process_codes = processes.get_indexer(rows.process_ocid)
    adjacency = [set() for _ in participants]
    for participant, process in zip(participant_codes, process_codes, strict=True):
        adjacency[participant].add(int(process))
    sizes = np.bincount(process_codes, minlength=len(processes)).tolist()
    graph = build_projection(adjacency, sizes, maximum)
    return nx.relabel_nodes(graph, dict(enumerate(participants)))


def canonical(graph: nx.Graph) -> nx.Graph:
    ordered = nx.Graph()
    ordered.add_nodes_from(sorted(graph.nodes))
    ordered.add_edges_from(
        sorted((min(u, v), max(u, v), data) for u, v, data in graph.edges(data=True))
    )
    return ordered


def giant_component(graph: nx.Graph) -> nx.Graph:
    nodes = max(nx.connected_components(graph), key=lambda c: (len(c), min(c)))
    return canonical(graph.subgraph(nodes))


def participant_attributes(participation_dir: Path, rows: pd.DataFrame) -> pd.DataFrame:
    tenders = pd.read_parquet(
        participation_dir / "fact_tender", columns=["process_ocid", "cubso_segment"]
    )
    frame = rows.merge(tenders, on="process_ocid", how="left")

    def dominant(column: str) -> pd.Series:
        counts = frame.dropna(subset=[column]).groupby(["participant_id", column]).size()
        counts = counts.reset_index(name="n").sort_values(
            ["participant_id", "n", column], ascending=[True, False, True]
        )
        return counts.drop_duplicates("participant_id").set_index("participant_id")[column]

    return pd.DataFrame(
        {"dominant_segment": dominant("cubso_segment"), "dominant_province": dominant("region")}
    ).rename_axis("participant_id")


def labels_from_sets(nodes: list[str], groups: list[set[str]]) -> dict[str, int]:
    labels = {}
    for index, group in enumerate(groups):
        for node in group:
            labels[node] = index
    return {node: labels[node] for node in nodes}


def groups_from_labels(labels: dict[str, int]) -> list[set[str]]:
    groups: dict[int, set[str]] = {}
    for node, label in labels.items():
        groups.setdefault(label, set()).add(node)
    return list(groups.values())


def spectral_partition(graph: nx.Graph, nodes: list[str], k: int, seed: int) -> dict[str, int]:
    affinity = sparse.csr_matrix(
        nx.to_scipy_sparse_array(graph, nodelist=nodes, weight="weight", format="csr")
    )
    affinity.indices = affinity.indices.astype(np.int32)
    affinity.indptr = affinity.indptr.astype(np.int32)
    labels = SpectralClustering(
        n_clusters=k, affinity="precomputed", assign_labels="cluster_qr", random_state=seed
    ).fit_predict(affinity)
    return dict(zip(nodes, labels.tolist(), strict=True))


def strongest_betweenness_edge(graph: nx.Graph) -> tuple[str, str]:
    centrality = nx.edge_betweenness_centrality(graph, weight="distance")
    return max(centrality, key=lambda edge: (round(centrality[edge], 12), sorted(edge)))


def girvan_newman_levels(graph: nx.Graph, max_communities: int) -> list[list[set[str]]]:
    working = graph.copy()
    for left, right, data in working.edges(data=True):
        working[left][right]["distance"] = 1.0 / data["weight"]
    levels = []
    for groups in girvan_newman(working, most_valuable_edge=strongest_betweenness_edge):
        levels.append([set(group) for group in groups])
        if len(groups) >= max_communities:
            break
    return levels


def describe(
    graph: nx.Graph, labels: dict[str, int], attributes: pd.DataFrame
) -> dict[str, float | int]:
    nodes = list(labels)
    known = attributes.reindex(nodes)
    result: dict[str, float | int] = {
        "communities": len(set(labels.values())),
        "modularity": float(modularity(graph, groups_from_labels(labels), weight="weight")),
        "largest_share": float(pd.Series(labels).value_counts().max() / len(nodes)),
    }
    for column in ("dominant_segment", "dominant_province"):
        mask = known[column].notna().to_numpy()
        values = [labels[node] for node, keep in zip(nodes, mask, strict=True) if keep]
        truth = known[column].dropna()
        result[f"nmi_{column}"] = float(normalized_mutual_info_score(truth, values))
        result[f"ami_{column}"] = float(adjusted_mutual_info_score(truth, values))
    return result


def run() -> None:
    args = parse_args()
    participation_dir, output_dir = args.participation_dir.resolve(), args.output_dir.resolve()
    if not (participation_dir / "fact_tenderer" / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta fact_tenderer publicado.")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    rows = department_rows(participation_dir, args.department, args.min_recurrent_processes)
    full = department_graph(rows, args.max_recurrent_participants)
    giant = giant_component(full)
    attributes = participant_attributes(participation_dir, rows)
    giant_nodes = sorted(giant.nodes)

    runs: list[dict] = []
    memberships: list[pd.DataFrame] = []

    def record(scope: str, method: str, config: str, graph, labels, seconds: float) -> None:
        runs.append(
            {"scope": scope, "method": method, "config": config, "seconds": round(seconds, 3)}
            | describe(graph, labels, attributes)
        )
        memberships.append(
            pd.DataFrame(
                {
                    "participant_id": list(labels),
                    "scope": scope,
                    "method": method,
                    "config": config,
                    "community": list(labels.values()),
                }
            )
        )

    start = time.perf_counter()
    louvain = community_louvain.best_partition(
        giant, weight="weight", resolution=args.resolution, random_state=args.seed
    )
    record("giant", "louvain", str(args.resolution), giant, louvain, time.perf_counter() - start)

    spectral_runs = {}
    for k in sorted(set(args.spectral_k)):
        start = time.perf_counter()
        labels = spectral_partition(giant, giant_nodes, k, args.seed)
        spectral_runs[k] = labels
        record("giant", "spectral", str(k), giant, labels, time.perf_counter() - start)
    spectral_scores = {int(r["config"]): r["modularity"] for r in runs if r["method"] == "spectral"}
    best_k = max(spectral_scores, key=lambda k: (spectral_scores[k], -k))

    strength = pd.Series(dict(giant.degree(weight="weight"))).round(9).sort_index()
    strength = strength.sort_values(ascending=False, kind="stable")
    core = giant_component(giant.subgraph(strength.index[: args.core_nodes]))
    core_nodes = sorted(core.nodes)
    start = time.perf_counter()
    levels = girvan_newman_levels(core, args.max_gn_communities)
    gn_seconds = time.perf_counter() - start
    level_rows = [
        {
            "level": index + 1,
            "communities": len(groups),
            "modularity": float(modularity(core, groups, weight="weight")),
        }
        for index, groups in enumerate(levels)
    ]
    best_level = max(level_rows, key=lambda row: row["modularity"])
    level_memberships = pd.DataFrame(
        [
            {"level": index + 1, "participant_id": node, "community": label}
            for index, groups in enumerate(levels)
            for node, label in labels_from_sets(core_nodes, groups).items()
        ]
    )
    gn_labels = labels_from_sets(core_nodes, levels[best_level["level"] - 1])
    record("core", "girvan_newman", str(best_level["communities"]), core, gn_labels, gn_seconds)

    start = time.perf_counter()
    core_louvain = community_louvain.best_partition(
        core, weight="weight", resolution=1.0, random_state=args.seed
    )
    record("core", "louvain", "1.0", core, core_louvain, time.perf_counter() - start)
    start = time.perf_counter()
    core_spectral = spectral_partition(core, core_nodes, best_level["communities"], args.seed)
    record(
        "core",
        "spectral",
        str(best_level["communities"]),
        core,
        core_spectral,
        time.perf_counter() - start,
    )

    def ari(left: dict[str, int], right: dict[str, int], nodes: list[str]) -> float:
        return float(adjusted_rand_score([left[n] for n in nodes], [right[n] for n in nodes]))

    agreement = [
        {
            "scope": "giant",
            "pair": "louvain-spectral",
            "ari": ari(louvain, spectral_runs[best_k], giant_nodes),
        },
        {
            "scope": "core",
            "pair": "girvan_newman-louvain",
            "ari": ari(gn_labels, core_louvain, core_nodes),
        },
        {
            "scope": "core",
            "pair": "girvan_newman-spectral",
            "ari": ari(gn_labels, core_spectral, core_nodes),
        },
        {
            "scope": "core",
            "pair": "louvain-spectral",
            "ari": ari(core_louvain, core_spectral, core_nodes),
        },
    ]

    layout = nx.spring_layout(core, weight="weight", seed=args.seed, iterations=200)
    layout_frame = pd.DataFrame(
        [{"participant_id": node, "x": float(x), "y": float(y)} for node, (x, y) in layout.items()]
    ).merge(attributes.reset_index(), on="participant_id", how="left")
    core_edges = pd.DataFrame(
        [{"left": u, "right": v, "weight": float(d["weight"])} for u, v, d in core.edges(data=True)]
    )

    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(runs).to_csv(stage / "runs.csv", index=False)
    pd.DataFrame(level_rows).to_csv(stage / "girvan_newman_levels.csv", index=False)
    pd.DataFrame(agreement).to_csv(stage / "agreement.csv", index=False)
    pd.concat(memberships, ignore_index=True).to_parquet(stage / "memberships.parquet", index=False)
    layout_frame.to_parquet(stage / "core_layout.parquet", index=False)
    core_edges.to_parquet(stage / "core_edges.parquet", index=False)
    level_memberships.to_parquet(stage / "girvan_newman_memberships.parquet", index=False)
    attributes.reset_index().to_parquet(stage / "attributes.parquet", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "department": args.department,
        "min_recurrent_processes": args.min_recurrent_processes,
        "max_recurrent_participants": args.max_recurrent_participants,
        "graph": {"nodes": full.number_of_nodes(), "edges": full.number_of_edges()},
        "giant": {"nodes": giant.number_of_nodes(), "edges": giant.number_of_edges()},
        "core": {
            "requested_nodes": args.core_nodes,
            "nodes": core.number_of_nodes(),
            "edges": core.number_of_edges(),
        },
        "spectral_best_k": best_k,
        "girvan_newman_best": best_level,
        "girvan_newman_seconds": round(gn_seconds, 3),
        "seed": args.seed,
    }
    (stage / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Particiones P2 publicadas: {output_dir}")


if __name__ == "__main__":
    run()
