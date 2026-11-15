"""Clustering renovado de compradores con perfiles no contaminados por P1."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import hdbscan
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from src.processing.build_fact_award_item import publish_output, staging_dir

FEATURES = [
    "log_process_count",
    "log_pen_amount",
    "log_distinct_suppliers",
    "cubso_entropy",
    "noncompetitive_fraction",
    "amount_fraction_goods",
    "amount_fraction_services",
    "amount_fraction_works",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profiles-dir", type=Path, default=Path("data/processed/buyer_profiles"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/buyer_clustering"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    profiles_dir, output = args.profiles_dir.resolve(), args.output_dir.resolve()
    if (
        not (profiles_dir / "_SUCCESS").is_file()
        or not (profiles_dir / "buyer_features" / "_SUCCESS").is_file()
    ):
        raise FileNotFoundError("Faltan perfiles publicados.")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite.")
    frame = (
        pd.read_parquet(profiles_dir / "buyer_features")
        .sort_values("buyer_id")
        .reset_index(drop=True)
    )
    values = frame[FEATURES].to_numpy(float)
    if not np.isfinite(values).all() or frame.buyer_id.duplicated().any():
        raise ValueError("Perfiles inválidos.")
    matrix = StandardScaler().fit_transform(values)
    records = []
    assignments = []
    models = {}
    for k in range(2, 9):
        labels = KMeans(
            n_clusters=k, init="k-means++", n_init=20, random_state=args.seed
        ).fit_predict(matrix)
        counts = np.bincount(labels)
        score = float(silhouette_score(matrix, labels, sample_size=1500, random_state=args.seed))
        records.append(
            {
                "method": "kmeans",
                "config": str(k),
                "silhouette": score,
                "min_cluster_size": int(counts.min()),
            }
        )
        assignments.append(
            pd.DataFrame(
                {"buyer_id": frame.buyer_id, "method": "kmeans", "config": str(k), "label": labels}
            )
        )
        models[("kmeans", str(k))] = labels
        ward = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(matrix)
        records.append(
            {
                "method": "ward",
                "config": str(k),
                "silhouette": float(
                    silhouette_score(matrix, ward, sample_size=1500, random_state=args.seed)
                ),
                "min_cluster_size": int(np.bincount(ward).min()),
            }
        )
        assignments.append(
            pd.DataFrame(
                {"buyer_id": frame.buyer_id, "method": "ward", "config": str(k), "label": ward}
            )
        )
    for size in (30, 60):
        labels = hdbscan.HDBSCAN(
            min_cluster_size=size, min_samples=10, core_dist_n_jobs=1
        ).fit_predict(matrix)
        kept = labels != -1
        records.append(
            {
                "method": "hdbscan",
                "config": f"{size}:10",
                "silhouette": float(
                    silhouette_score(
                        matrix[kept],
                        labels[kept],
                        sample_size=min(1500, kept.sum()),
                        random_state=args.seed,
                    )
                )
                if len(set(labels[kept])) > 1
                else None,
                "min_cluster_size": int(np.bincount(labels[kept]).min()) if kept.any() else 0,
                "coverage": float(kept.mean()),
            }
        )
        assignments.append(
            pd.DataFrame(
                {
                    "buyer_id": frame.buyer_id,
                    "method": "hdbscan",
                    "config": f"{size}:10",
                    "label": labels,
                }
            )
        )
    metrics = pd.DataFrame(records)
    eligible = metrics[
        (metrics.method == "kmeans") & (metrics.min_cluster_size >= max(15, int(0.01 * len(frame))))
    ]
    selected = eligible.sort_values(["silhouette", "config"], ascending=[False, True]).iloc[0]
    all_assign = pd.concat(assignments, ignore_index=True)
    all_assign["selected"] = (all_assign.method == "kmeans") & (
        all_assign.config == selected.config
    )
    base = models[("kmeans", selected.config)]
    stability = []
    for seed in (7, 21, 99):
        rng = np.random.default_rng(seed)
        sample = np.sort(rng.choice(len(frame), int(0.8 * len(frame)), replace=False))
        labels = KMeans(
            n_clusters=int(selected.config), init="k-means++", n_init=20, random_state=seed
        ).fit_predict(matrix[sample])
        stability.append(
            {
                "seed": seed,
                "ari_vs_full_on_sample": float(adjusted_rand_score(base[sample], labels)),
            }
        )
    profiles = (
        all_assign[all_assign.selected]
        .merge(frame, on="buyer_id")
        .groupby("label")
        .agg(
            buyers=("buyer_id", "size"),
            median_processes=("process_count", "median"),
            median_pen=("pen_amount_total", "median"),
            median_suppliers=("distinct_suppliers", "median"),
            median_noncompetitive=("noncompetitive_fraction", "median"),
            median_entropy=("cubso_entropy", "median"),
        )
        .reset_index()
    )
    stage = staging_dir(output)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    for name, data in [
        ("features", frame),
        ("assignments", all_assign),
        ("metrics", metrics),
        ("profiles", profiles),
        ("stability", pd.DataFrame(stability)),
    ]:
        data.to_parquet(stage / f"{name}.parquet", index=False)
    meta = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "features": FEATURES,
        "excluded": ["HHI", "concentración", "participación"],
        "kmeans_selected": {
            "k": int(selected.config),
            "silhouette": float(selected.silhouette),
            "min_cluster_size": int(selected.min_cluster_size),
        },
        "seed": args.seed,
        "stability": stability,
    }
    (stage / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"Clustering de compradores publicado: {output}")


if __name__ == "__main__":
    run()
