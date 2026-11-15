"""Selecciona compradores atípicos respecto de su perfil para revisión contextual."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import hdbscan
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clustering-dir", type=Path, default=Path("artifacts/buyer_clustering"))
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/buyer_outliers"))
    parser.add_argument("--min-cluster-size", type=int, default=30)
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--quantile", type=float, default=0.98)
    parser.add_argument("--min-processes", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def dominant_reason(deviation: pd.Series) -> str:
    feature = deviation.abs().idxmax()
    return f"{feature} {'alto' if deviation[feature] > 0 else 'bajo'}"


def run() -> None:
    args = parse_args()
    clustering_dir, output_dir = args.clustering_dir.resolve(), args.output_dir.resolve()
    if not (clustering_dir / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta el clustering de compradores publicado.")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    meta = json.loads((clustering_dir / "metadata.json").read_text(encoding="utf-8"))
    features = meta["features"]
    frame = pd.read_parquet(clustering_dir / "features.parquet").sort_values("buyer_id")
    frame = frame.reset_index(drop=True)
    matrix = StandardScaler().fit_transform(frame[features].to_numpy(float))
    model = hdbscan.HDBSCAN(
        min_cluster_size=args.min_cluster_size, min_samples=args.min_samples, core_dist_n_jobs=1
    ).fit(matrix)
    frame["hdbscan_label"] = model.labels_
    frame["outlier_score"] = model.outlier_scores_
    assignments = pd.read_parquet(clustering_dir / "assignments.parquet")
    profile = assignments.loc[assignments.selected, ["buyer_id", "label"]].rename(
        columns={"label": "profile"}
    )
    frame = frame.merge(profile, on="buyer_id", how="left", validate="one_to_one")
    buyers = pd.read_parquet(
        args.participation_dir.resolve() / "dim_buyer",
        columns=["buyer_id", "buyer_name", "department"],
    )
    frame = frame.merge(buyers, on="buyer_id", how="left", validate="one_to_one")
    labels = frame.profile.to_numpy()
    centroids = np.vstack([matrix[labels == g].mean(axis=0) for g in range(labels.max() + 1)])
    frame["profile_distance"] = np.linalg.norm(matrix - centroids[labels], axis=1)
    eligible = frame.process_count >= args.min_processes
    threshold = float(frame.loc[eligible, "profile_distance"].quantile(args.quantile))
    candidates = frame.loc[eligible & (frame.profile_distance >= threshold)].copy()
    deviations = pd.DataFrame(matrix - centroids[labels], columns=features, index=frame.index)
    candidates["reason"] = [dominant_reason(deviations.loc[i]) for i in candidates.index]
    candidates = candidates.sort_values("profile_distance", ascending=False)
    by_profile = (
        frame.assign(candidate=eligible & (frame.profile_distance >= threshold))
        .groupby("profile")
        .agg(
            buyers=("buyer_id", "size"),
            noise_share=("hdbscan_label", lambda x: float((x == -1).mean())),
            candidates=("candidate", "sum"),
            median_distance=("profile_distance", "median"),
        )
        .reset_index()
    )
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    columns = [
        "buyer_id",
        "buyer_name",
        "department",
        "profile",
        "profile_distance",
        "hdbscan_label",
        "outlier_score",
        "reason",
        "process_count",
        "pen_amount_total",
        "distinct_suppliers",
        "noncompetitive_fraction",
        "cubso_entropy",
    ]
    candidates[columns].to_csv(stage / "candidates.csv", index=False)
    by_profile.to_csv(stage / "by_profile.csv", index=False)
    frame[["buyer_id", "profile_distance", "hdbscan_label", "outlier_score"]].to_parquet(
        stage / "scores.parquet", index=False
    )
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": (
            "distancia estandarizada al centroide de su perfil KMeans; "
            "GLOSH y ruido de HDBSCAN se reportan como contraste"
        ),
        "min_cluster_size": args.min_cluster_size,
        "min_samples": args.min_samples,
        "quantile": args.quantile,
        "min_processes": args.min_processes,
        "eligible_buyers": int(eligible.sum()),
        "threshold": threshold,
        "candidates": len(candidates),
        "noise_share": float((frame.hdbscan_label == -1).mean()),
        "candidates_in_noise": int((candidates.hdbscan_label == -1).sum()),
        "spearman_distance_glosh": float(
            frame.profile_distance.corr(frame.outlier_score, method="spearman")
        ),
        "reason": "variable con mayor desviación estandarizada respecto del centroide del perfil",
        "reading": "candidatos para revisión contextual; no indican irregularidad",
    }
    (stage / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Atípicos de compradores publicados: {output_dir}")


if __name__ == "__main__":
    run()
