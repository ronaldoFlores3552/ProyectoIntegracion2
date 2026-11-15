"""Sensibilidad de Louvain al orden de inserción de las aristas de la proyección P2."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from sklearn.metrics import adjusted_rand_score

from src.models.detect_communities_p2 import run_louvain
from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--projection-dir", type=Path, default=Path("data/processed/market_p2_k30"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/louvain_order"))
    parser.add_argument("--resolution", type=float, default=1.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--permutation-seeds", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_edges(edges_dir: Path) -> list[tuple[str, str, float]]:
    table = ds.dataset(str(edges_dir), format="parquet").to_table(
        columns=["participant_left", "participant_right", "newman_weight"]
    )
    return list(
        zip(
            table.column("participant_left").to_pylist(),
            table.column("participant_right").to_pylist(),
            [float(value) for value in table.column("newman_weight").to_pylist()],
            strict=True,
        )
    )


def edge_orders(
    edges: list[tuple[str, str, float]], permutation_seeds: list[int]
) -> dict[str, list[tuple[str, str, float]]]:
    orders = {"archivo": edges, "ordenado": sorted(edges)}
    for seed in permutation_seeds:
        permutation = np.random.default_rng(seed).permutation(len(edges))
        orders[f"aleatorio_{seed}"] = [edges[index] for index in permutation]
    return orders


def build_graph(edges: list[tuple[str, str, float]]) -> nx.Graph:
    graph = nx.Graph()
    graph.add_weighted_edges_from(edges)
    return graph


def run() -> None:
    args = parse_args()
    projection_dir, output_dir = args.projection_dir.resolve(), args.output_dir.resolve()
    if not (projection_dir / "coparticipation_edges" / "_SUCCESS").is_file():
        raise FileNotFoundError(f"Falta una proyección P2 publicada: {projection_dir}")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    edges = read_edges(projection_dir / "coparticipation_edges")
    partitions: dict[str, dict[str, int]] = {}
    runs = []
    for name, ordered in edge_orders(edges, args.permutation_seeds).items():
        partition, modularity = run_louvain(build_graph(ordered), args.resolution, args.seed)
        partitions[name] = partition
        runs.append(
            {
                "order": name,
                "modularity": modularity,
                "community_count": len(set(partition.values())),
            }
        )
    nodes = sorted(partitions["archivo"])
    agreement = [
        {
            "left": left,
            "right": right,
            "ari": float(
                adjusted_rand_score(
                    [partitions[left][node] for node in nodes],
                    [partitions[right][node] for node in nodes],
                )
            ),
        }
        for left, right in combinations(partitions, 2)
    ]
    runs_frame, agreement_frame = pd.DataFrame(runs), pd.DataFrame(agreement)
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    runs_frame.to_csv(stage / "runs.csv", index=False)
    agreement_frame.to_csv(stage / "agreement.csv", index=False)
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "edges": len(edges),
        "resolution": args.resolution,
        "louvain_seed": args.seed,
        "permutation_seeds": args.permutation_seeds,
        "modularity_min": float(runs_frame.modularity.min()),
        "modularity_max": float(runs_frame.modularity.max()),
        "ari_min": float(agreement_frame.ari.min()),
        "ari_max": float(agreement_frame.ari.max()),
        "reading": "misma semilla y mismo grafo; solo cambia el orden de inserción de las aristas",
    }
    (stage / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Sensibilidad al orden publicada: {output_dir}")


if __name__ == "__main__":
    run()
