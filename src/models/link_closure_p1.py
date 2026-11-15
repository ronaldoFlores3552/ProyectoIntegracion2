"""Relaciona el cierre comunitario de cada mercado de P1 con su concentración.

Corre en local: combina los mercados agregados de P1 con etiquetas de comunidad ya calculadas.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.analyze_market_p1 import (
    UNIT_KEYS,
    association,
    bootstrap_by_buyer,
    null_associations,
)
from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market-dir", type=Path, default=Path("data/processed/market_p1"))
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument(
        "--awards-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument("--communities-dir", type=Path, default=Path("artifacts/p2/communities"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/closure"))
    parser.add_argument("--resolution", type=float, default=1.0)
    parser.add_argument("--community-seed", type=int, default=42)
    parser.add_argument("--min-processes", type=int, nargs="+", default=[10, 20])
    parser.add_argument("--min-labeled", type=int, default=20)
    parser.add_argument("--bootstrap-replicates", type=int, default=1000)
    parser.add_argument("--null-replicates", type=int, default=200)
    parser.add_argument("--start-award-year", type=int, default=2023)
    parser.add_argument("--end-award-year", type=int, default=2024)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def unit_closure(
    processes: pd.DataFrame, tenderers: pd.DataFrame, communities: pd.DataFrame
) -> pd.DataFrame:
    participations = processes[UNIT_KEYS + ["process_ocid"]].merge(
        tenderers, on="process_ocid", how="inner"
    )
    total = participations.groupby(UNIT_KEYS, dropna=False).size().rename("participations")
    labeled = participations.merge(communities, on="participant_id", how="inner")
    mix = labeled.groupby(UNIT_KEYS + ["community"], dropna=False).size().rename("n").reset_index()
    mix["share"] = mix.n / mix.groupby(UNIT_KEYS, dropna=False).n.transform("sum")
    summary = mix.groupby(UNIT_KEYS, dropna=False).agg(
        labeled_participations=("n", "sum"),
        closure=("share", "max"),
        community_count=("community", "nunique"),
        community_entropy=("share", lambda x: float(-(x * np.log(x)).sum())),
    )
    result = summary.join(total, how="left").reset_index()
    result["labeled_share"] = result.labeled_participations / result.participations
    return result


def expected_hhi(events: pd.DataFrame, candidate_ids: dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    for process, award, unit in zip(
        events.process_ocid, events.award_id, events[UNIT_KEYS].itertuples(index=False), strict=True
    ):
        candidates = candidate_ids.get(process)
        if candidates is None or len(candidates) == 0:
            continue
        p = 1.0 / len(candidates)
        for supplier in candidates:
            rows.append((*unit, process, award, supplier, p))
    table = pd.DataFrame(rows, columns=[*UNIT_KEYS, "process_ocid", "award_id", "supplier_id", "p"])
    events_per_unit = (
        table[[*UNIT_KEYS, "process_ocid", "award_id"]]
        .drop_duplicates()
        .groupby(UNIT_KEYS, dropna=False)
        .size()
    )
    moments = (
        table.assign(variance=table.p * (1 - table.p))
        .groupby([*UNIT_KEYS, "supplier_id"], dropna=False)[["p", "variance"]]
        .sum()
    )
    second = (moments.variance + moments.p**2).groupby(level=list(range(len(UNIT_KEYS)))).sum()
    expected = second / events_per_unit.reindex(second.index) ** 2
    return expected.rename("expected_hhi").reset_index()


def observed_hhi(events: pd.DataFrame, candidate_ids: dict[str, np.ndarray]) -> pd.DataFrame:
    usable = events.loc[events.process_ocid.isin(candidate_ids)]
    counts = usable.groupby([*UNIT_KEYS, "supplier_id"], dropna=False).size().rename("n")
    shares = counts / counts.groupby(level=list(range(len(UNIT_KEYS)))).transform("sum")
    return (
        (shares**2)
        .groupby(level=list(range(len(UNIT_KEYS))))
        .sum()
        .rename("observed_hhi")
        .reset_index()
    )


def run() -> None:
    args = parse_args()
    market_dir, participation_dir = args.market_dir.resolve(), args.participation_dir.resolve()
    awards_dir, communities_dir = args.awards_dir.resolve(), args.communities_dir.resolve()
    output_dir = args.output_dir.resolve()
    for path in (market_dir, participation_dir, awards_dir, communities_dir):
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta un artefacto publicado: {path}")
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")

    units = pd.read_parquet(market_dir / "buyer_segment_method")
    processes = pd.read_parquet(market_dir / "p1_processes")
    tenderers = (
        pd.read_parquet(
            participation_dir / "fact_tenderer", columns=["process_ocid", "participant_id"]
        )
        .dropna()
        .drop_duplicates()
    )
    tenderers = tenderers.loc[tenderers.process_ocid.isin(processes.process_ocid)]
    memberships = pd.read_parquet(communities_dir / "memberships.parquet")
    communities = memberships.loc[
        (memberships.resolution == args.resolution) & (memberships.seed == args.community_seed),
        ["participant_id", "community"],
    ]
    if communities.empty:
        raise ValueError("No hay comunidades para la resolución y semilla pedidas.")

    closure = unit_closure(processes, tenderers, communities)
    frame = units.merge(closure, on=UNIT_KEYS, how="inner", validate="one_to_one")
    frame = frame.loc[frame.labeled_participations >= args.min_labeled].reset_index(drop=True)

    awards = pd.read_parquet(awards_dir)
    awards = awards.loc[awards.award_year.between(args.start_award_year, args.end_award_year)]
    events = (
        processes[UNIT_KEYS + ["process_ocid"]]
        .merge(
            awards[["process_ocid", "award_id", "supplier_id"]],
            on="process_ocid",
            how="inner",
            validate="one_to_many",
        )
        .drop_duplicates(UNIT_KEYS + ["process_ocid", "award_id", "supplier_id"])
    )
    events = events.merge(frame[UNIT_KEYS], on=UNIT_KEYS, how="inner")
    candidate_ids = {
        process: np.sort(group.participant_id.astype(str).unique())
        for process, group in tenderers.loc[
            tenderers.process_ocid.isin(events.process_ocid)
        ].groupby("process_ocid", sort=True)
    }

    rows = []
    for threshold in sorted(set(args.min_processes)):
        for adjusted in (False, True):
            seed = args.seed + threshold + int(adjusted)
            rows.append(
                {
                    "minimum_processes": threshold,
                    "adjustment": "stratum_centered" if adjusted else "raw",
                    **association(frame, "closure", threshold, adjusted),
                    **bootstrap_by_buyer(
                        frame, "closure", threshold, adjusted, args.bootstrap_replicates, seed
                    ),
                }
            )
    results = pd.DataFrame(rows)

    excess = observed_hhi(events, candidate_ids).merge(
        expected_hhi(events, candidate_ids), on=UNIT_KEYS, how="inner"
    )
    excess["excess_hhi"] = excess.observed_hhi - excess.expected_hhi
    frame = frame.merge(excess, on=UNIT_KEYS, how="left", validate="one_to_one")
    excess_frame = frame.dropna(subset=["excess_hhi"]).assign(hhi=lambda x: x.excess_hhi)
    excess_rows = []
    for threshold in sorted(set(args.min_processes)):
        chosen = excess_frame.loc[excess_frame.process_count >= threshold]
        for adjusted in (False, True):
            seed = args.seed + threshold + int(adjusted)
            excess_rows.append(
                {
                    "minimum_processes": threshold,
                    "adjustment": "stratum_centered" if adjusted else "raw",
                    "units_level": len(chosen),
                    "mean_observed_hhi": float(chosen.observed_hhi.mean()),
                    "mean_expected_hhi": float(chosen.expected_hhi.mean()),
                    "mean_excess_hhi": float(chosen.excess_hhi.mean()),
                    "share_positive_excess": float((chosen.excess_hhi > 0).mean()),
                    "closure_excess_correlation": (
                        estimate := association(excess_frame, "closure", threshold, adjusted)
                    )["correlation"],
                    "units_correlation": estimate["units"],
                    **{
                        f"closure_excess_{key}": value
                        for key, value in bootstrap_by_buyer(
                            excess_frame,
                            "closure",
                            threshold,
                            adjusted,
                            args.bootstrap_replicates,
                            seed,
                        ).items()
                        if key in ("ci_low", "ci_high")
                    },
                }
            )
    null, coverage = null_associations(
        events,
        candidate_ids,
        frame,
        sorted(set(args.min_processes)),
        args.null_replicates,
        args.seed,
        measure="closure",
    )
    null_summary = (
        null.groupby(["minimum_processes", "adjustment"])
        .correlation.agg(
            null_mean="mean",
            null_p025=lambda x: x.quantile(0.025),
            null_p975=lambda x: x.quantile(0.975),
        )
        .reset_index()
        .merge(results[["minimum_processes", "adjustment", "correlation"]])
    )
    null_summary["share_null_at_or_above_observed"] = [
        float(
            (
                null.loc[
                    (null.minimum_processes == r.minimum_processes)
                    & (null.adjustment == r.adjustment),
                    "correlation",
                ]
                >= r.correlation
            ).mean()
        )
        for r in null_summary.itertuples()
    ]

    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(stage / "unit_closure.parquet", index=False)
    results.to_csv(stage / "association_results.csv", index=False)
    null_summary.to_csv(stage / "null_summary.csv", index=False)
    pd.DataFrame(excess_rows).to_csv(stage / "excess_hhi.csv", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "communities": {"resolution": args.resolution, "seed": args.community_seed},
        "closure": (
            "proporción de participaciones proceso-participante de la unidad que pertenece "
            "a su comunidad más frecuente; solo participantes recurrentes tienen comunidad"
        ),
        "min_labeled_participations": args.min_labeled,
        "units": len(frame),
        "median_labeled_share": float(frame.labeled_share.median()),
        "median_labeled_share_by_threshold": {
            str(t): float(frame.loc[frame.process_count >= t, "labeled_share"].median())
            for t in sorted(set(args.min_processes))
        },
        "excess_hhi": "HHI observado menos su esperanza exacta con ganador uniforme",
        "null": "ganador sorteado entre participantes reportados; el cierre queda fijo",
        "null_replicates": args.null_replicates,
        "coverage": coverage,
    }
    (stage / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Cierre y concentración publicados: {output_dir}")


if __name__ == "__main__":
    run()
