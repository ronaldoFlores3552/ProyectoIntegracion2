"""Evalúa un híbrido ALS--TF-IDF por fusión recíproca de rankings."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.models.recommendation_baseline import read_table, score_rankings
from src.processing.build_fact_award_item import publish_output, staging_dir


def read_metadata(directory: Path) -> dict:
    """Lee y valida el contrato mínimo compartido por los dos rankings."""
    return json.loads((directory / "_metadata.json").read_text(encoding="utf-8"))


def validate_compatible_metadata(als_meta: dict, content_meta: dict) -> None:
    """Impide fusionar rankings construidos sobre cortes o fuentes distintas."""
    for field in ("cut", "input_sha256"):
        if als_meta.get(field) != content_meta.get(field):
            raise ValueError(
                f"Los rankings no son comparables: {field} difiere entre ALS y contenido."
            )


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--als-dir", type=Path, default=Path("artifacts/recommendation_als"))
    parser.add_argument(
        "--content-dir", type=Path, default=Path("artifacts/recommendation_content")
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed/recommendation"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/recommendation_hybrid"))
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    als, content, source, output = (
        p.resolve() for p in (args.als_dir, args.content_dir, args.input_dir, args.output_dir)
    )
    if any(not (p / "_SUCCESS").is_file() for p in (als, content, source)):
        raise FileNotFoundError("Falta entrada publicada.")
    if output.exists() and not args.overwrite:
        raise FileExistsError("Salida existente; use --overwrite.")
    als_meta, content_meta = read_metadata(als), read_metadata(content)
    validate_compatible_metadata(als_meta, content_meta)
    a = pd.read_parquet(als / "rankings.parquet")
    c = pd.read_parquet(content / "rankings.parquet")
    ranks = pd.concat([a.assign(method="als"), c.assign(method="content")])
    ranks["rrf"] = 1 / (args.rrf_k + ranks["rank"])
    fused = (
        ranks.groupby(["entity_id", "supplier_id"], as_index=False)
        .rrf.sum()
        .sort_values(["entity_id", "rrf", "supplier_id"], ascending=[True, False, True])
    )
    fused["rank"] = fused.groupby("entity_id").cumcount() + 1
    train = read_table(source / "2023" / "train", ["entity_id", "supplier_id"])
    future = read_table(
        source / "2023" / "future_pairs", ["entity_id", "supplier_id", "eligible_positive"]
    )
    positives = defaultdict(set)
    for row in future[future.eligible_positive].itertuples(index=False):
        positives[row.entity_id].add(row.supplier_id)
    catalog = set(train.supplier_id)
    history = train.groupby("entity_id").supplier_id.nunique().to_dict()
    counts = {e: len(catalog) - history[e] for e in positives}
    ranking = {e: list(g.sort_values("rank").supplier_id) for e, g in fused.groupby("entity_id")}
    metrics = pd.concat([score_rankings(ranking, positives, counts, k) for k in (10, 20)])
    stage = staging_dir(output)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    fused.to_parquet(stage / "rankings.parquet", index=False)
    metrics.to_parquet(stage / "metrics_by_entity.parquet", index=False)
    summary = {
        str(k): {x: float(g[x].mean()) for x in ("recall", "precision", "ndcg")}
        for k, g in metrics.groupby("k")
    }
    meta = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "cut": 2023,
        "input_sha256": als_meta["input_sha256"],
        "source_models": {
            "als_method": als_meta.get("method"),
            "content_method": content_meta.get("method"),
        },
        "method": "Reciprocal Rank Fusion ALS+TF-IDF; unión de rankings truncados",
        "rrf_k": args.rrf_k,
        "entities_evaluated": len(positives),
        "metrics_macro": summary,
        "limitation": (
            "No mezcla puntajes continuos: los modelos de origen publican rankings "
            "truncados."
        ),
    }
    (stage / "_metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"Híbrido publicado: {output}")


if __name__ == "__main__":
    run()
