"""Compara HITS del bipartito de adjudicación bajo pesos por conteo, log1p y binario.

Corre en local con scipy: el bipartito de adjudicación tiene 62 mil aristas.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.models.analyze_links_p2 import _sparse_bipartite, hits_bipartite
from src.processing.build_fact_award_item import publish_output, staging_dir

WEIGHTS = {
    "conteo": lambda counts: counts,
    "log1p": np.log1p,
    "binario": lambda counts: np.ones_like(counts),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market-dir", type=Path, default=Path("data/processed/market_p2"))
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/hits_sensitivity"))
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    market_dir, output_dir = args.market_dir.resolve(), args.output_dir.resolve()
    if not (market_dir / "graph_award_edges" / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta graph_award_edges publicado.")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    edges = pd.read_parquet(market_dir / "graph_award_edges")
    buyers = pd.read_parquet(
        args.participation_dir.resolve() / "dim_buyer",
        columns=["buyer_id", "buyer_name", "department"],
    ).set_index("buyer_id")
    degree = edges.groupby("supplier_id").buyer_id.nunique()

    tops, summary, hub_scores = [], [], {}
    for name, transform in WEIGHTS.items():
        weighted = edges.assign(award_count=transform(edges.award_count.to_numpy(float)))
        matrix, buyer_index, supplier_index = _sparse_bipartite(weighted)
        hubs, authorities, iterations = hits_bipartite(matrix, 1e-10, 5000)
        hub_scores[name] = pd.Series(hubs, index=buyer_index)
        order = np.argsort(-authorities)
        mass = authorities**2
        summary.append(
            {
                "weight": name,
                "iterations": iterations,
                "top_authority_mass": float(mass[order[0]]),
                "top10_authority_mass": float(mass[order[:10]].sum()),
                "top_authority_buyers": int(degree[supplier_index[order[0]]]),
            }
        )
        for rank, index in enumerate(np.argsort(-hubs)[: args.top], start=1):
            buyer = buyer_index[index]
            tops.append(
                {
                    "weight": name,
                    "rank": rank,
                    "buyer_name": buyers.buyer_name.get(buyer),
                    "department": buyers.department.get(buyer),
                    "hub_score": float(hubs[index]),
                }
            )
    agreement = [
        {
            "left": left,
            "right": right,
            "spearman_hub": float(spearmanr(hub_scores[left], hub_scores[right]).statistic),
        }
        for i, left in enumerate(WEIGHTS)
        for right in list(WEIGHTS)[i + 1 :]
    ]
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(tops).to_csv(stage / "top_hubs.csv", index=False)
    pd.DataFrame(summary).to_csv(stage / "summary.csv", index=False)
    pd.DataFrame(agreement).to_csv(stage / "agreement.csv", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "weights": list(WEIGHTS),
        "top_authority_mass": "fracción de la norma cuadrática del vector de authorities",
    }
    (stage / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Sensibilidad HITS publicada: {output_dir}")


if __name__ == "__main__":
    run()
