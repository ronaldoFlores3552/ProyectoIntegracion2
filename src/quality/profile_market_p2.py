"""Diagnostica escala, cobertura y componentes de la proyección P2."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.dataset as ds
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    publish_output,
    staging_dir,
)


class UnionFind:
    """Union-Find determinista en memoria de nodos, no de aristas."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, node: str) -> str:
        if node not in self.parent:
            self.parent[node] = node
            self.rank[node] = 0
            return node
        parent = self.parent[node]
        if parent != node:
            self.parent[node] = self.find(parent)
        return self.parent[node]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        left_rank, right_rank = self.rank[left_root], self.rank[right_root]
        if left_rank < right_rank:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if left_rank == right_rank:
            self.rank[left_root] += 1

    def components(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for node in self.parent:
            groups.setdefault(self.find(node), []).append(node)
        return groups


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market-dir", type=Path, default=Path("data/processed/market_p2"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/diagnostics"))
    parser.add_argument("--master", default="local[*]", help="Spark master; use local[*] en local.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def node_metrics(edges: DataFrame) -> DataFrame:
    """Compute undirected degree and Newman-weight strength in Spark."""
    incident = edges.select(
        F.col("participant_left").alias("participant_id"),
        F.col("participant_right").alias("neighbor_id"),
        "newman_weight",
    ).unionByName(
        edges.select(
            F.col("participant_right").alias("participant_id"),
            F.col("participant_left").alias("neighbor_id"),
            "newman_weight",
        )
    )
    return incident.groupBy("participant_id").agg(
        F.countDistinct("neighbor_id").cast("long").alias("degree"),
        F.sum("newman_weight").cast("double").alias("strength"),
    )


def _quantiles(frame: DataFrame, column: str) -> dict[str, float]:
    values = frame.approxQuantile(column, [0.0, 0.5, 0.9, 0.99, 1.0], 0.001)
    return dict(zip(("min", "p50", "p90", "p99", "max"), values, strict=True))


def stream_components(edges_dir: Path) -> tuple[list[tuple[str, str]], list[tuple[str, int]]]:
    """Read only edge batches and return deterministic node/component assignments."""
    union_find = UnionFind()
    dataset = ds.dataset(str(edges_dir), format="parquet")
    scanner = dataset.scanner(columns=["participant_left", "participant_right"], batch_size=131_072)
    for batch in scanner.to_batches():
        left_values = batch.column("participant_left").to_pylist()
        right_values = batch.column("participant_right").to_pylist()
        for left, right in zip(left_values, right_values, strict=True):
            union_find.union(left, right)
    groups = union_find.components()
    canonical = {root: min(nodes) for root, nodes in groups.items()}
    memberships = sorted((node, canonical[union_find.find(node)]) for node in union_find.parent)
    sizes = sorted(
        ((canonical[root], len(nodes)) for root, nodes in groups.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return memberships, sizes


def _write_csv(path: Path, rows: list[tuple[object, ...]], headers: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)


def _validate_inputs(market_dir: Path, output_dir: Path, overwrite: bool) -> None:
    if not (market_dir / "_SUCCESS").is_file():
        raise FileNotFoundError(f"Falta una entrada publicada con _SUCCESS: {market_dir}")
    for child in ("coparticipation_edges", "coparticipation_process_coverage"):
        if not (market_dir / child / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta una tabla P2 publicada: {child}")
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")


def run() -> None:
    args = parse_args()
    market_dir, output_dir = args.market_dir.resolve(), args.output_dir.resolve()
    _validate_inputs(market_dir, output_dir, args.overwrite)
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-profile-market-p2")
        .master(args.master)
        .config("spark.sql.shuffle.partitions", "16")
    )
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    spark = builder.getOrCreate()
    try:
        edges = spark.read.parquet(str(market_dir / "coparticipation_edges"))
        coverage = spark.read.parquet(str(market_dir / "coparticipation_process_coverage"))
        metrics = node_metrics(edges)
        edge_count, node_count = edges.count(), metrics.count()
        degree_one = metrics.where(F.col("degree") == 1).count()
        strength_one = metrics.where(F.col("strength") <= 1.0).count()
        degree_quantiles = _quantiles(metrics, "degree")
        strength_quantiles = _quantiles(metrics, "strength")
        edge_weight_quantiles = _quantiles(edges, "newman_weight")
        coverage_summary = (
            coverage.agg(
                F.count("*").alias("processes_with_participants"),
                F.sum(F.col("is_projectable").cast("long")).alias("projectable_processes"),
                F.sum((F.col("recurrent_participant_count") == 0).cast("long")).alias(
                    "no_recurrent"
                ),
                F.sum((F.col("recurrent_participant_count") == 1).cast("long")).alias(
                    "one_recurrent"
                ),
                F.avg("reported_participant_count").alias("mean_reported_participants"),
                F.avg("recurrent_participant_count").alias("mean_recurrent_participants"),
            )
            .first()
            .asDict()
        )
        stage = staging_dir(output_dir)
        shutil.rmtree(stage, ignore_errors=True)
        metrics.write.mode("overwrite").parquet(str(stage / "node_metrics"))
        if not (stage / "node_metrics" / "_SUCCESS").is_file():
            raise RuntimeError("node_metrics no dejó _SUCCESS.")
    finally:
        spark.stop()

    memberships, component_sizes = stream_components(market_dir / "coparticipation_edges")
    _write_csv(
        stage / "component_membership.csv",
        memberships,
        ("participant_id", "component_id"),
    )
    _write_csv(stage / "components.csv", component_sizes, ("component_id", "node_count"))
    largest_component = component_sizes[0][1] if component_sizes else 0
    summary = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_market_dir": str(market_dir),
        "method": {
            "node_metrics": (
                "Spark: degree and sum of Newman weights over undirected incident edges."
            ),
            "components": (
                "Exact Union-Find over PyArrow Parquet batches; edge list is never loaded fully "
                "in memory."
            ),
        },
        "projection": {
            "nodes": node_count,
            "undirected_edges": edge_count,
            "density": (2 * edge_count) / (node_count * (node_count - 1)),
            "degree_one_nodes": degree_one,
            "degree_one_share": degree_one / node_count,
            "strength_at_most_one_nodes": strength_one,
            "strength_at_most_one_share": strength_one / node_count,
            "degree_quantiles": degree_quantiles,
            "strength_quantiles": strength_quantiles,
            "edge_weight_quantiles": edge_weight_quantiles,
        },
        "components": {
            "component_count": len(component_sizes),
            "largest_component_nodes": largest_component,
            "largest_component_share": largest_component / node_count,
            "top_component_sizes": [size for _, size in component_sizes[:10]],
        },
        "coverage": coverage_summary,
        "files": ["node_metrics/", "component_membership.csv", "components.csv"],
    }
    (stage / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Diagnóstico P2 publicado: {output_dir}")


if __name__ == "__main__":
    run()
