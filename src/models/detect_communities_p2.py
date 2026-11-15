"""Explora comunidades Louvain ponderadas en la proyección P2 filtrada."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import community as community_louvain
import networkx as nx
import pandas as pd
import pyarrow.dataset as ds
from sklearn.metrics import adjusted_rand_score

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--projection-dir", type=Path, default=Path("data/processed/market_p2_k30"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/communities"))
    parser.add_argument("--resolution", type=float, nargs="+", default=[0.5, 1.0, 1.5])
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 42, 99])
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_weighted_graph(edges_dir: Path) -> nx.Graph:
    """Build one undirected weighted NetworkX graph from Parquet batches."""
    graph = nx.Graph()
    scanner = ds.dataset(str(edges_dir), format="parquet").scanner(
        columns=["participant_left", "participant_right", "newman_weight"], batch_size=131_072
    )
    for batch in scanner.to_batches():
        for left, right, weight in zip(
            batch.column("participant_left").to_pylist(),
            batch.column("participant_right").to_pylist(),
            batch.column("newman_weight").to_pylist(),
            strict=True,
        ):
            graph.add_edge(left, right, weight=float(weight))
    return graph


def run_louvain(graph: nx.Graph, resolution: float, seed: int) -> tuple[dict[str, int], float]:
    partition = community_louvain.best_partition(
        graph, weight="weight", resolution=resolution, random_state=seed
    )
    modularity = community_louvain.modularity(partition, graph, weight="weight")
    return partition, float(modularity)


def _validate_inputs(projection_dir: Path, output_dir: Path, overwrite: bool) -> None:
    if (
        not (projection_dir / "_SUCCESS").is_file()
        or not (projection_dir / "coparticipation_edges" / "_SUCCESS").is_file()
    ):
        raise FileNotFoundError(f"Falta una proyección P2 publicada: {projection_dir}")
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")


def run() -> None:
    args = parse_args()
    if not args.resolution or not args.seeds or any(value <= 0 for value in args.resolution):
        raise ValueError("Resoluciones positivas y al menos una semilla son obligatorias.")
    projection_dir, output_dir = args.projection_dir.resolve(), args.output_dir.resolve()
    _validate_inputs(projection_dir, output_dir, args.overwrite)
    graph = load_weighted_graph(projection_dir / "coparticipation_edges")
    nodes = sorted(graph.nodes)
    memberships: list[pd.DataFrame] = []
    summaries: list[dict[str, float | int]] = []
    partitions: dict[tuple[float, int], dict[str, int]] = {}
    for resolution in sorted(set(args.resolution)):
        for seed in sorted(set(args.seeds)):
            partition, modularity = run_louvain(graph, resolution, seed)
            partitions[(resolution, seed)] = partition
            sizes = pd.Series(partition).value_counts()
            memberships.append(
                pd.DataFrame(
                    {
                        "participant_id": nodes,
                        "resolution": resolution,
                        "seed": seed,
                        "community": [partition[node] for node in nodes],
                    }
                )
            )
            summaries.append(
                {
                    "resolution": resolution,
                    "seed": seed,
                    "modularity": modularity,
                    "community_count": int(len(sizes)),
                    "largest_community_nodes": int(sizes.max()),
                    "largest_community_share": float(sizes.max() / len(nodes)),
                }
            )
    stability: list[dict[str, float | int]] = []
    for resolution in sorted(set(args.resolution)):
        seeds = sorted(set(args.seeds))
        for index, left_seed in enumerate(seeds):
            for right_seed in seeds[index + 1 :]:
                left = [partitions[(resolution, left_seed)][node] for node in nodes]
                right = [partitions[(resolution, right_seed)][node] for node in nodes]
                stability.append(
                    {
                        "resolution": resolution,
                        "left_seed": left_seed,
                        "right_seed": right_seed,
                        "ari": float(adjusted_rand_score(left, right)),
                    }
                )
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    pd.concat(memberships, ignore_index=True).to_parquet(stage / "memberships.parquet", index=False)
    pd.DataFrame(summaries).to_csv(stage / "runs.csv", index=False)
    pd.DataFrame(stability).to_csv(stage / "stability.csv", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_projection_dir": str(projection_dir),
        "nodes": len(nodes),
        "edges": graph.number_of_edges(),
        "weight": "newman_weight",
        "resolutions": sorted(set(args.resolution)),
        "seeds": sorted(set(args.seeds)),
        "files": ["memberships.parquet", "runs.csv", "stability.csv"],
    }
    (stage / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Comunidades P2 publicadas: {output_dir}")


if __name__ == "__main__":
    run()
