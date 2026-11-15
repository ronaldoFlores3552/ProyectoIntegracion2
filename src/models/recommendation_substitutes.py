"""Proveedores sustitutos por segmento CUBSO y afinidades inusuales comprador-proveedor."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--items-dir", type=Path, default=Path("data/processed/fact_award_item"))
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/recommendation_substitutes")
    )
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--profile-end-year", type=int, default=2023)
    parser.add_argument("--min-awards", type=int, default=3)
    parser.add_argument("--neighbors", type=int, default=5)
    parser.add_argument("--unusual-quantile", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_items(items_dir: Path, start: int, end: int) -> pd.DataFrame:
    items = pd.read_parquet(
        items_dir,
        columns=[
            "process_ocid",
            "award_id",
            "entity_id",
            "supplier_id",
            "award_date",
            "item_description",
            "item_classification_id",
        ],
    )
    year = pd.to_datetime(items.award_date, utc=True).dt.tz_convert("America/Lima").dt.year
    items = items.assign(award_year=year)
    items = items.loc[year.between(start, end)].dropna(subset=["supplier_id", "entity_id"])
    items["item_description"] = items.item_description.fillna("").str.strip()
    items["segment"] = items.item_classification_id.str[:2]
    return items.loc[items.item_description != ""]


def dominant_segment(items: pd.DataFrame, key: str) -> pd.Series:
    counts = items.dropna(subset=["segment"]).groupby([key, "segment"]).size().reset_index(name="n")
    counts = counts.sort_values([key, "n", "segment"], ascending=[True, False, True])
    return counts.drop_duplicates(key).set_index(key).segment


def profiles(items: pd.DataFrame, key: str, vectorizer: TfidfVectorizer) -> tuple:
    documents = items.groupby(key).item_description.agg(" ".join)
    return documents.index, normalize(vectorizer.transform(documents.to_numpy()))


def segment_neighbors(ids: pd.Index, vectors, segments: pd.Series, k: int) -> pd.DataFrame:
    rows = []
    for segment, members in segments.groupby(segments):
        positions = ids.get_indexer(members.index)
        if len(positions) < 2:
            continue
        block = vectors[positions]
        similarity = (block @ block.T).toarray()
        np.fill_diagonal(similarity, -1.0)
        top = np.argsort(-similarity, axis=1, kind="stable")[:, :k]
        for row, columns in enumerate(top):
            for rank, column in enumerate(columns, start=1):
                if similarity[row, column] <= 0:
                    continue
                rows.append(
                    {
                        "supplier_id": ids[positions[row]],
                        "substitute_id": ids[positions[column]],
                        "segment": segment,
                        "rank": rank,
                        "similarity": float(similarity[row, column]),
                    }
                )
    return pd.DataFrame(rows)


def pair_rates(pairs: pd.DataFrame, process_sets: dict, buyer_sets: dict) -> dict[str, float]:
    empty: set = set()
    shared_process = [
        bool(process_sets.get(a, empty) & process_sets.get(b, empty))
        for a, b in zip(pairs.supplier_id, pairs.substitute_id, strict=True)
    ]
    shared_buyer = [
        bool(buyer_sets.get(a, empty) & buyer_sets.get(b, empty))
        for a, b in zip(pairs.supplier_id, pairs.substitute_id, strict=True)
    ]
    return {
        "pairs": len(pairs),
        "share_coparticipate": float(np.mean(shared_process)) if len(pairs) else 0.0,
        "share_same_buyer": float(np.mean(shared_buyer)) if len(pairs) else 0.0,
    }


def random_pairs(segments: pd.Series, count: int, rng: np.random.Generator) -> pd.DataFrame:
    groups = {s: m.index.to_numpy() for s, m in segments.groupby(segments) if len(m) >= 2}
    weights = np.array([len(v) for v in groups.values()], dtype=float)
    keys = list(groups)
    picks = rng.choice(len(keys), count, p=weights / weights.sum())
    rows = []
    for pick in picks:
        left, right = rng.choice(groups[keys[pick]], 2, replace=False)
        rows.append({"supplier_id": left, "substitute_id": right, "segment": keys[pick]})
    return pd.DataFrame(rows)


def run() -> None:
    args = parse_args()
    items_dir, output_dir = args.items_dir.resolve(), args.output_dir.resolve()
    participation_dir = args.participation_dir.resolve()
    if not (items_dir / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta fact_award_item publicado.")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")
    items = load_items(items_dir, args.start_year, args.end_year)
    history = items.loc[items.award_year <= args.profile_end_year]
    future = items.loc[items.award_year > args.profile_end_year]
    awards = (
        history[["supplier_id", "process_ocid", "award_id"]]
        .drop_duplicates()
        .groupby("supplier_id")
        .size()
    )
    eligible = awards[awards >= args.min_awards].index
    supplier_items = history.loc[history.supplier_id.isin(eligible)]

    vectorizer = TfidfVectorizer(
        strip_accents="unicode",
        lowercase=True,
        ngram_range=(1, 2),
        min_df=3,
        max_df=0.8,
        max_features=30_000,
        sublinear_tf=True,
        dtype=np.float32,
    ).fit(history.item_description)
    supplier_ids, supplier_vectors = profiles(supplier_items, "supplier_id", vectorizer)
    segments = dominant_segment(supplier_items, "supplier_id").reindex(supplier_ids).dropna()
    substitutes = segment_neighbors(supplier_ids, supplier_vectors, segments, args.neighbors)

    tenderers = pd.read_parquet(
        participation_dir / "fact_tenderer", columns=["process_ocid", "participant_id"]
    )
    tenderers = tenderers.loc[
        tenderers.participant_id.isin(segments.index)
        & tenderers.process_ocid.isin(set(future.process_ocid) - set(history.process_ocid))
    ]
    process_sets = tenderers.groupby("participant_id").process_ocid.agg(set).to_dict()
    unseen = future.loc[~future.process_ocid.isin(set(history.process_ocid))]
    buyer_sets = (
        unseen.loc[unseen.supplier_id.isin(segments.index)]
        .groupby("supplier_id")
        .entity_id.agg(set)
        .to_dict()
    )
    rng = np.random.default_rng(args.seed)
    first = substitutes.loc[substitutes["rank"] == 1]
    validation = pd.DataFrame(
        [
            {"set": "sustituto_top1"} | pair_rates(first, process_sets, buyer_sets),
            {"set": f"sustituto_top{args.neighbors}"}
            | pair_rates(substitutes, process_sets, buyer_sets),
            {"set": "aleatorio_mismo_segmento"}
            | pair_rates(random_pairs(segments, len(first), rng), process_sets, buyer_sets),
        ]
    )

    entity_ids, entity_vectors = profiles(items, "entity_id", vectorizer)
    all_ids, all_vectors = profiles(items, "supplier_id", vectorizer)
    pairs = items[["entity_id", "supplier_id"]].drop_duplicates().reset_index(drop=True)
    left = entity_vectors[entity_ids.get_indexer(pairs.entity_id)]
    right = all_vectors[all_ids.get_indexer(pairs.supplier_id)]
    pairs["similarity"] = np.asarray(left.multiply(right).sum(axis=1)).ravel()
    pairs["supplier_segment"] = pairs.supplier_id.map(dominant_segment(items, "supplier_id"))
    pairs["buyer_segment"] = pairs.entity_id.map(dominant_segment(items, "entity_id"))
    threshold = float(pairs.similarity.quantile(args.unusual_quantile))
    pairs["unusual"] = pairs.similarity <= threshold
    unusual_by_segment = (
        pairs.groupby("supplier_segment")
        .agg(pairs=("unusual", "size"), unusual=("unusual", "sum"))
        .assign(unusual_share=lambda x: x.unusual / x.pairs)
        .reset_index()
        .sort_values("pairs", ascending=False)
    )

    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    substitutes.to_parquet(stage / "substitutes.parquet", index=False)
    validation.to_csv(stage / "validation.csv", index=False)
    pairs.to_parquet(stage / "affinity_pairs.parquet", index=False)
    unusual_by_segment.to_csv(stage / "unusual_by_segment.csv", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "window": [args.start_year, args.end_year],
        "profile_window": [args.start_year, args.profile_end_year],
        "validation": (
            "coincidencia en procesos y compradores comunes de adjudicaciones posteriores a "
            "profile_end_year, excluidos los procesos con adjudicaciones en ambos periodos"
        ),
        "suppliers_with_profile": len(supplier_ids),
        "suppliers_with_segment": int(len(segments)),
        "min_awards": args.min_awards,
        "neighbors": args.neighbors,
        "terms": len(vectorizer.vocabulary_),
        "pairs_scored": len(pairs),
        "unusual_quantile": args.unusual_quantile,
        "unusual_threshold": threshold,
        "reading": (
            "sustituto significa perfil de ítems parecido dentro del segmento; "
            "afinidad inusual significa poca similitud textual entre lo que compra la "
            "entidad y lo que vende el proveedor. Son señales descriptivas."
        ),
    }
    (stage / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Sustitutos publicados: {output_dir}")


if __name__ == "__main__":
    run()
