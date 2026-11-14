"""Relaciona perfiles de comprador, SVD y comunidades P2 sin forzar convergencia."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import normalized_mutual_info_score

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profiles-dir", type=Path, default=Path("data/processed/buyer_profiles"))
    parser.add_argument("--clustering-dir", type=Path, default=Path("artifacts/buyer_clustering"))
    parser.add_argument("--svd-dir", type=Path, default=Path("artifacts/p2/svd"))
    parser.add_argument("--market-dir", type=Path, default=Path("data/processed/market_p2"))
    parser.add_argument("--communities-dir", type=Path, default=Path("artifacts/p2/communities"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/convergence"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    paths = [
        args.profiles_dir.resolve(),
        args.clustering_dir.resolve(),
        args.svd_dir.resolve(),
        args.market_dir.resolve(),
        args.communities_dir.resolve(),
    ]
    if any(not (path / "_SUCCESS").is_file() for path in paths):
        raise FileNotFoundError("Falta un artefacto publicado para convergencia.")
    output = args.output_dir.resolve()
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite.")
    profiles = pd.read_parquet(paths[0] / "buyer_features")
    meta = json.loads((paths[1] / "metadata.json").read_text(encoding="utf-8"))
    k = str(meta["kmeans_selected"]["k"])
    labels = pd.read_parquet(paths[1] / "assignments.parquet")
    labels = labels[(labels.method == "kmeans") & (labels.config == k)][
        ["buyer_id", "label"]
    ].rename(columns={"label": "profile_cluster"})
    svd = pd.read_parquet(paths[2] / "buyer_coordinates.parquet")
    edges = pd.read_parquet(paths[3] / "graph_participation_edges")
    communities = pd.read_parquet(paths[4] / "memberships.parquet")
    communities = communities[(communities.resolution == 1.5) & (communities.seed == 42)][
        ["participant_id", "community"]
    ]
    mix = edges.merge(communities, on="participant_id", how="inner")
    mix["share"] = mix.process_count / mix.groupby("buyer_id").process_count.transform("sum")
    community = mix.groupby("buyer_id").agg(
        community_count=("community", "nunique"),
        community_entropy=("share", lambda x: float(-(x * np.log(x)).sum())),
    )
    dominant = (
        mix.sort_values(["buyer_id", "share", "community"], ascending=[True, False, True])
        .drop_duplicates("buyer_id")[["buyer_id", "community", "share"]]
        .rename(columns={"community": "dominant_community", "share": "dominant_community_share"})
    )
    result = (
        profiles.merge(labels, on="buyer_id", validate="one_to_one")
        .merge(svd, on="buyer_id", validate="one_to_one")
        .merge(community, on="buyer_id", how="left")
        .merge(dominant, on="buyer_id", how="left")
        .fillna({"community_count": 0, "community_entropy": 0, "dominant_community_share": 0})
    )
    evaluable = result.dominant_community.notna()
    nmi = float(
        normalized_mutual_info_score(
            result.loc[evaluable, "profile_cluster"], result.loc[evaluable, "dominant_community"]
        )
    )
    cluster_svd = (
        result.groupby("profile_cluster")
        .agg(
            buyers=("buyer_id", "size"),
            median_svd_1=("svd_1", "median"),
            median_svd_2=("svd_2", "median"),
            median_community_entropy=("community_entropy", "median"),
            median_dominant_community_share=("dominant_community_share", "median"),
        )
        .reset_index()
    )
    stage = staging_dir(output)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    result.to_parquet(stage / "buyer_convergence.parquet", index=False)
    cluster_svd.to_parquet(stage / "cluster_convergence.parquet", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "profile_kmeans": int(k),
        "community_reference": {"resolution": 1.5, "seed": 42},
        "buyers": len(result),
        "buyers_with_community": int(evaluable.sum()),
        "nmi_profile_cluster_dominant_community": nmi,
        "interpretation": (
            "NMI mide asociación entre etiquetas, no verdad ni causalidad; "
            "SVD, comunidades y perfiles pueden divergir."
        ),
    }
    (stage / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"Convergencia P2 publicada: {output}")


if __name__ == "__main__":
    run()
