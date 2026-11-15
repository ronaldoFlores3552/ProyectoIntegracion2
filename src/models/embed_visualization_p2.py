"""Usa el SVD de compradores en t-SNE y clustering, y lo contrasta con perfiles y comunidades."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.manifold import TSNE
from sklearn.metrics import (
    adjusted_mutual_info_score,
    normalized_mutual_info_score,
    silhouette_score,
)
from sklearn.preprocessing import normalize

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--svd-dir", type=Path, default=Path("artifacts/p2/svd_participation"))
    parser.add_argument("--convergence-dir", type=Path, default=Path("artifacts/p2/convergence"))
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/embedding"))
    parser.add_argument("--k", type=int, nargs="+", default=list(range(2, 11)))
    parser.add_argument("--perplexity", type=float, default=30.0)
    parser.add_argument("--min-energy", type=float, default=0.05)
    parser.add_argument("--energy-sensitivity", type=float, nargs="+", default=[0.02, 0.05, 0.1])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def nmi(left: pd.Series, right: pd.Series) -> float:
    mask = left.notna() & right.notna()
    return float(normalized_mutual_info_score(left[mask].astype(str), right[mask].astype(str)))


def ami(left: pd.Series, right: pd.Series) -> float:
    mask = left.notna() & right.notna()
    return float(adjusted_mutual_info_score(left[mask].astype(str), right[mask].astype(str)))


def run() -> None:
    args = parse_args()
    svd_dir, convergence_dir = args.svd_dir.resolve(), args.convergence_dir.resolve()
    participation_dir, output_dir = args.participation_dir.resolve(), args.output_dir.resolve()
    for path in (svd_dir, convergence_dir):
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta un artefacto publicado: {path}")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")

    full = pd.read_parquet(svd_dir / "buyer_coordinates.parquet").sort_values("buyer_id")
    columns = [c for c in full.columns if c.startswith("svd_")]
    convergence = pd.read_parquet(
        convergence_dir / "buyer_convergence.parquet",
        columns=["buyer_id", "profile_cluster", "dominant_community", "process_count"],
    )
    buyers = pd.read_parquet(
        participation_dir / "dim_buyer", columns=["buyer_id", "buyer_name", "department"]
    )
    context = (
        full[["buyer_id", "captured_energy"]]
        .merge(convergence, on="buyer_id", how="left")
        .merge(buyers, on="buyer_id", how="left")
    )
    sensitivity = []
    for threshold in sorted(set(args.energy_sensitivity) | {args.min_energy}):
        kept = context.captured_energy.to_numpy() >= threshold
        vectors = normalize(full.loc[kept, columns].to_numpy(float))
        labels = pd.Series(
            KMeans(n_clusters=10, n_init=20, random_state=args.seed).fit_predict(vectors),
            index=context.index[kept],
        )
        sub = context.loc[kept]
        sensitivity.append(
            {
                "min_energy": threshold,
                "buyers": int(kept.sum()),
                "ami_department_k10": ami(labels, sub.department),
                "ami_profile_k10": ami(labels, sub.profile_cluster),
                "ami_community_k10": ami(labels, sub.dominant_community),
            }
        )
    keep = full.captured_energy.to_numpy() >= args.min_energy
    excluded = int((~keep).sum())
    retention = (
        context.assign(kept=keep)
        .groupby("profile_cluster")
        .kept.agg(["size", "mean"])
        .rename(columns={"size": "buyers", "mean": "share_kept"})
        .reset_index()
    )
    svd = full.loc[keep].reset_index(drop=True)
    values = svd[columns].to_numpy(float)
    matrix = normalize(values)
    frame = (
        svd[["buyer_id"]]
        .merge(convergence, on="buyer_id", how="left")
        .merge(buyers, on="buyer_id", how="left", validate="one_to_one")
    )

    selection = []
    labels_by_k = {}
    for k in sorted(set(args.k)):
        labels = KMeans(n_clusters=k, n_init=20, random_state=args.seed).fit_predict(matrix)
        labels_by_k[k] = labels
        series = pd.Series(labels, index=frame.index)
        selection.append(
            {
                "k": k,
                "silhouette": float(
                    silhouette_score(matrix, labels, sample_size=2000, random_state=args.seed)
                ),
                "nmi_department": nmi(series, frame.department),
                "nmi_profile_cluster": nmi(series, frame.profile_cluster),
                "nmi_dominant_community": nmi(series, frame.dominant_community),
                "ami_department": ami(series, frame.department),
                "ami_profile_cluster": ami(series, frame.profile_cluster),
                "ami_dominant_community": ami(series, frame.dominant_community),
            }
        )
    selection = pd.DataFrame(selection)
    best_k = int(selection.sort_values(["silhouette", "k"], ascending=[False, True]).iloc[0].k)

    coordinates = TSNE(
        n_components=2,
        perplexity=args.perplexity,
        init="pca",
        learning_rate="auto",
        random_state=args.seed,
    ).fit_transform(matrix)
    frame["tsne_x"], frame["tsne_y"] = coordinates[:, 0], coordinates[:, 1]
    for k, labels in labels_by_k.items():
        frame[f"svd_kmeans_{k}"] = labels

    baseline = {
        "nmi_profile_vs_department": nmi(frame.profile_cluster, frame.department),
        "nmi_community_vs_department": nmi(frame.dominant_community, frame.department),
        "nmi_profile_vs_community": nmi(frame.profile_cluster, frame.dominant_community),
    }
    cluster_department = (
        frame.groupby(f"svd_kmeans_{best_k}")
        .agg(
            buyers=("buyer_id", "size"),
            top_department=("department", lambda x: x.mode().iloc[0] if x.notna().any() else None),
            top_department_share=(
                "department",
                lambda x: float(x.value_counts(normalize=True).iloc[0]),
            ),
            median_processes=("process_count", "median"),
        )
        .reset_index()
        .rename(columns={f"svd_kmeans_{best_k}": "cluster"})
    )

    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(stage / "buyer_embedding.parquet", index=False)
    selection.to_csv(stage / "kmeans_selection.csv", index=False)
    cluster_department.to_csv(stage / "clusters.csv", index=False)
    pd.DataFrame(sensitivity).to_csv(stage / "energy_sensitivity.csv", index=False)
    retention.to_csv(stage / "retention_by_profile.csv", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "buyers": len(frame),
        "excluded_low_energy": excluded,
        "buyers_without_matrix_row": int(len(buyers) - len(full)),
        "label_agreement_population": "compradores conservados en el embedding",
        "best_k_rule": "máxima silueta dentro del rango explorado; no hay óptimo interior",
        "min_energy": args.min_energy,
        "input": "coordenadas SVD de compradores con energía capturada suficiente, norma 1",
        "tsne": {"perplexity": args.perplexity, "init": "pca", "seed": args.seed},
        "kmeans_best_k": best_k,
        "label_agreement": baseline,
    }
    (stage / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Embeddings P2 publicados: {output_dir}")


if __name__ == "__main__":
    run()
