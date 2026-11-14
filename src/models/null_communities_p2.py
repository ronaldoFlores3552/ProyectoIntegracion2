"""Nulo P2 por Curveball: conserva tamaños de proceso y recurrencia."""

from __future__ import annotations

import argparse
import json
import random
import shutil
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import community as community_louvain
import networkx as nx
import pandas as pd

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--department", default="PUNO")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/null"))
    parser.add_argument("--min-recurrent-processes", type=int, default=5)
    parser.add_argument("--max-recurrent-participants", type=int, default=30)
    parser.add_argument("--resolution", type=float, default=1.5)
    parser.add_argument("--louvain-seed", type=int, default=42)
    parser.add_argument("--replicates", type=int, default=10)
    parser.add_argument("--trades-per-participant", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def curveball_trade(adjacency: list[set[int]], rng: random.Random) -> None:
    left, right = rng.sample(range(len(adjacency)), 2)
    only_left, only_right = adjacency[left] - adjacency[right], adjacency[right] - adjacency[left]
    if not only_left or not only_right:
        return
    pool = list(only_left | only_right)
    rng.shuffle(pool)
    common = adjacency[left] & adjacency[right]
    adjacency[left] = common | set(pool[: len(only_left)])
    adjacency[right] = common | set(pool[len(only_left) :])


def validate_margins(adjacency: list[set[int]], process_sizes: list[int]) -> bool:
    observed = [0] * len(process_sizes)
    for values in adjacency:
        for process in values:
            observed[process] += 1
    return observed == process_sizes


def build_projection(adjacency: list[set[int]], process_sizes: list[int], maximum: int) -> nx.Graph:
    processes: list[list[int]] = [[] for _ in process_sizes]
    for participant, values in enumerate(adjacency):
        for process in values:
            processes[process].append(participant)
    graph = nx.Graph()
    for participants in processes:
        size = len(participants)
        if 2 <= size <= maximum:
            weight = 1.0 / (size - 1)
            for left, right in combinations(sorted(participants), 2):
                previous = graph.get_edge_data(left, right, {}).get("weight", 0.0)
                graph.add_edge(left, right, weight=previous + weight)
    return graph


def run() -> None:
    args = parse_args()
    if args.replicates < 1 or args.trades_per_participant < 1:
        raise ValueError("Réplicas y trades deben ser positivos.")
    participation_dir, output_dir = args.participation_dir.resolve(), args.output_dir.resolve()
    if not (participation_dir / "fact_tenderer" / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta fact_tenderer publicado.")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    rows = pd.read_parquet(
        participation_dir / "fact_tenderer",
        columns=["process_ocid", "buyer_id", "participant_id"],
    ).drop_duplicates()
    buyers = pd.read_parquet(participation_dir / "dim_buyer", columns=["buyer_id", "department"])
    rows = rows.merge(buyers, on="buyer_id", how="inner", validate="many_to_one")
    rows = rows.loc[rows.department == args.department, ["process_ocid", "participant_id"]]
    recurrent = rows.groupby("participant_id").process_ocid.nunique()
    rows = rows.loc[
        rows.participant_id.isin(recurrent[recurrent >= args.min_recurrent_processes].index)
    ]
    participants = pd.Index(sorted(rows.participant_id.unique()))
    processes = pd.Index(sorted(rows.process_ocid.unique()))
    participant_codes = pd.Series(range(len(participants)), index=participants)
    process_codes = pd.Series(range(len(processes)), index=processes)
    adjacency = [set() for _ in participants]
    for participant, process in zip(rows.participant_id, rows.process_ocid, strict=True):
        adjacency[participant_codes[participant]].add(process_codes[process])
    process_sizes = [
        sum(process in values for values in adjacency) for process in range(len(processes))
    ]
    participant_sizes = [len(values) for values in adjacency]
    observed_graph = build_projection(adjacency, process_sizes, args.max_recurrent_participants)
    observed_partition = community_louvain.best_partition(
        observed_graph, weight="weight", resolution=args.resolution, random_state=args.louvain_seed
    )
    observed_modularity = float(
        community_louvain.modularity(observed_partition, observed_graph, weight="weight")
    )
    results = []
    for replicate in range(args.replicates):
        rng = random.Random(args.seed + replicate)
        randomized = [set(values) for values in adjacency]
        for _ in range(args.trades_per_participant * len(randomized)):
            curveball_trade(randomized, rng)
        if [len(values) for values in randomized] != participant_sizes or not validate_margins(
            randomized, process_sizes
        ):
            raise RuntimeError("El nulo no conservó ambos márgenes bipartitos.")
        graph = build_projection(randomized, process_sizes, args.max_recurrent_participants)
        partition = community_louvain.best_partition(
            graph, weight="weight", resolution=args.resolution, random_state=args.louvain_seed
        )
        modularity = community_louvain.modularity(partition, graph, weight="weight")
        results.append(
            {
                "replicate": replicate,
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
                "modularity": modularity,
                "community_count": len(set(partition.values())),
            }
        )
    result = pd.DataFrame(results)
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    result.to_csv(stage / "replicates.csv", index=False)
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "department": args.department,
        "observed_nodes": observed_graph.number_of_nodes(),
        "observed_edges": observed_graph.number_of_edges(),
        "observed_modularity": observed_modularity,
        "null_mean": float(result.modularity.mean()),
        "null_ci_low": float(result.modularity.quantile(0.025)),
        "null_ci_high": float(result.modularity.quantile(0.975)),
        "share_null_at_or_above_observed": float((result.modularity >= observed_modularity).mean()),
        "replicates": args.replicates,
        "trades_per_participant": args.trades_per_participant,
        "seed": args.seed,
    }
    (stage / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Nulo P2 publicado: {output_dir}")


if __name__ == "__main__":
    run()
