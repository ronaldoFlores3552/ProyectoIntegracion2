"""Analiza P1 con asociación, bootstrap por comprador, nulo y sensibilidades."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.processing.build_fact_award_item import publish_output, staging_dir

UNIT_KEYS = ["buyer_id", "department", "cubso_segment", "procurement_method_details"]
PRIMARY_PARTICIPATION = "reported_participants_median"
ALTERNATIVE_PARTICIPATION = "number_of_tenderers_median"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market-dir", type=Path, default=Path("data/processed/market_p1"))
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument(
        "--awards-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p1/analysis"))
    parser.add_argument("--start-award-year", type=int, default=2023)
    parser.add_argument("--end-award-year", type=int, default=2024)
    parser.add_argument("--min-processes", type=int, nargs="+", default=[10, 20])
    parser.add_argument("--bootstrap-replicates", type=int, default=1000)
    parser.add_argument("--null-replicates", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _require_published(path: Path, children: tuple[str, ...] = ()) -> None:
    if not (path / "_SUCCESS").is_file():
        raise FileNotFoundError(f"Falta una entrada publicada con _SUCCESS: {path}")
    for child in children:
        if not (path / child / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta la tabla publicada: {path / child}")


def size_band(process_count: pd.Series) -> pd.Series:
    """Use pre-specified competitive-process bands for the P1 adjustment."""
    return pd.cut(
        process_count,
        bins=[-np.inf, 19, 49, np.inf],
        labels=["10-19", "20-49", "50+"],
    ).astype("string")


def _finite_spearman(left: pd.Series, right: pd.Series) -> float:
    valid = pd.DataFrame({"left": left, "right": right}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) < 3 or valid["left"].nunique() < 2 or valid["right"].nunique() < 2:
        return float("nan")
    return float(spearmanr(valid["left"], valid["right"]).statistic)


def association(
    metrics: pd.DataFrame,
    participation_column: str,
    minimum_processes: int,
    adjusted: bool,
) -> dict[str, float | int]:
    """Compute raw or stratum-centred Spearman association for one P1 definition."""
    columns = ["hhi", "process_count", participation_column, *UNIT_KEYS]
    frame = metrics.loc[metrics["process_count"] >= minimum_processes, columns].copy()
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "hhi",
            participation_column,
            "department",
            "cubso_segment",
            "procurement_method_details",
        ]
    )
    if not adjusted:
        return {
            "correlation": _finite_spearman(frame["hhi"], frame[participation_column]),
            "units": len(frame),
            "strata": 0,
        }

    frame["size_band"] = size_band(frame["process_count"])
    stratum = ["department", "cubso_segment", "procurement_method_details", "size_band"]
    frame["_stratum_count"] = frame.groupby(stratum, dropna=False)["hhi"].transform("size")
    frame = frame.loc[frame["_stratum_count"] >= 3].copy()
    if frame.empty:
        return {"correlation": float("nan"), "units": 0, "strata": 0}
    frame["_hhi_centered"] = frame["hhi"] - frame.groupby(stratum, dropna=False)["hhi"].transform(
        "median"
    )
    frame["_participation_centered"] = frame[participation_column] - frame.groupby(
        stratum, dropna=False
    )[participation_column].transform("median")
    return {
        "correlation": _finite_spearman(frame["_hhi_centered"], frame["_participation_centered"]),
        "units": len(frame),
        "strata": int(frame[stratum].drop_duplicates().shape[0]),
    }


def bootstrap_by_buyer(
    metrics: pd.DataFrame,
    participation_column: str,
    minimum_processes: int,
    adjusted: bool,
    replicates: int,
    seed: int,
) -> dict[str, float | int]:
    """Resample whole buyers because each buyer can contribute several P1 units."""
    buyer_code, buyers = pd.factorize(metrics["buyer_id"], sort=False)
    valid_rows = buyer_code >= 0
    base = metrics.loc[valid_rows].reset_index(drop=True)
    buyer_code = buyer_code[valid_rows]
    rng = np.random.default_rng(seed)
    samples: list[float] = []
    for _ in range(replicates):
        multiplicity = np.bincount(
            rng.integers(len(buyers), size=len(buyers)), minlength=len(buyers)
        )
        rows = np.repeat(np.arange(len(base)), multiplicity[buyer_code])
        sample = base.iloc[rows]
        value = association(sample, participation_column, minimum_processes, adjusted)[
            "correlation"
        ]
        if np.isfinite(value):
            samples.append(float(value))
    if not samples:
        return {
            "replicates": replicates,
            "valid_replicates": 0,
            "ci_low": float("nan"),
            "ci_high": float("nan"),
        }
    interval = np.quantile(samples, [0.025, 0.975])
    return {
        "replicates": replicates,
        "valid_replicates": len(samples),
        "ci_low": float(interval[0]),
        "ci_high": float(interval[1]),
    }


def hhi_from_events(
    events: pd.DataFrame, units: pd.DataFrame, weight_column: str | None = None
) -> pd.DataFrame:
    """Rebuild concentration from events, optionally weighting each award by amount."""
    events = events.copy()
    if weight_column is None:
        events["_weight"] = 1.0
    else:
        events["_weight"] = pd.to_numeric(events[weight_column], errors="raise")
    counts = (
        events.groupby(UNIT_KEYS + ["supplier_id"], dropna=False)
        .agg(supplier_weight=("_weight", "sum"), supplier_award_count=("_weight", "size"))
        .reset_index()
    )
    counts["total_weight"] = counts.groupby(UNIT_KEYS, dropna=False)["supplier_weight"].transform(
        "sum"
    )
    counts["supplier_share"] = counts["supplier_weight"] / counts["total_weight"]
    concentration = (
        counts.assign(_square=counts["supplier_share"].pow(2))
        .groupby(UNIT_KEYS, dropna=False)
        .agg(
            hhi=("_square", "sum"),
            award_count=("supplier_award_count", "sum"),
            concentration_weight_total=("total_weight", "first"),
        )
        .reset_index()
    )
    return units.drop(columns=["hhi", "award_count"], errors="ignore").merge(
        concentration, on=UNIT_KEYS, how="inner", validate="one_to_one"
    )


def consortium_mask(supplier_name: pd.Series) -> pd.Series:
    return supplier_name.fillna("").str.contains(r"\bCONSORCIO\b", case=False, regex=True)


def null_associations(
    events: pd.DataFrame,
    candidate_ids: dict[str, np.ndarray],
    units: pd.DataFrame,
    minimum_processes: list[int],
    replicates: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Draw each award winner uniformly from its reported process participants."""
    usable = events.loc[events["process_ocid"].isin(candidate_ids)].copy()
    candidate_codes, _ = pd.factorize(
        pd.concat([pd.Series(values) for values in candidate_ids.values()], ignore_index=True),
        sort=True,
    )
    unique_ids = pd.Index(
        pd.concat(
            [pd.Series(values) for values in candidate_ids.values()], ignore_index=True
        ).unique()
    )
    code_by_id = pd.Series(np.arange(len(unique_ids), dtype=np.int64), index=unique_ids)
    process_candidates = {
        process: code_by_id.loc[values].to_numpy(dtype=np.int64)
        for process, values in candidate_ids.items()
    }
    del candidate_codes
    usable["_unit_code"], unique_units = pd.factorize(
        pd.MultiIndex.from_frame(usable[UNIT_KEYS]), sort=True
    )
    unit_codes = usable["_unit_code"].to_numpy(dtype=np.int64)
    event_candidates = [process_candidates[process] for process in usable["process_ocid"]]
    total_by_unit = np.bincount(unit_codes, minlength=len(unique_units))
    multiplier = len(unique_ids) + 1
    unit_frame = (
        units.set_index(pd.MultiIndex.from_frame(units[UNIT_KEYS]))
        .reindex(unique_units)
        .reset_index(drop=True)
    )
    rng = np.random.default_rng(seed)
    rows: list[dict[str, float | int | str]] = []
    for replicate in range(replicates):
        simulated_supplier = np.fromiter(
            (choices[rng.integers(len(choices))] for choices in event_candidates), dtype=np.int64
        )
        pair_code = unit_codes * multiplier + simulated_supplier
        unique_pair, supplier_counts = np.unique(pair_code, return_counts=True)
        pair_units = unique_pair // multiplier
        shares = supplier_counts / total_by_unit[pair_units]
        simulated_hhi = np.bincount(pair_units, weights=shares**2, minlength=len(unique_units))
        frame = unit_frame.copy()
        frame["hhi"] = simulated_hhi
        for threshold in minimum_processes:
            for adjusted in (False, True):
                statistic = association(frame, PRIMARY_PARTICIPATION, threshold, adjusted)
                rows.append(
                    {
                        "replicate": replicate,
                        "minimum_processes": threshold,
                        "adjustment": "stratum_centered" if adjusted else "raw",
                        "correlation": statistic["correlation"],
                    }
                )
    coverage = {
        "award_events_selected": int(len(events)),
        "award_events_with_candidate_list": int(len(usable)),
        "units_with_candidate_list": int(len(unique_units)),
    }
    return pd.DataFrame(rows), coverage


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(_json_ready(value), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def run() -> None:
    args = parse_args()
    if args.start_award_year > args.end_award_year:
        raise ValueError("La ventana de adjudicación es inválida.")
    if any(value < 1 for value in args.min_processes):
        raise ValueError("Los umbrales deben ser positivos.")
    if args.bootstrap_replicates < 1 or args.null_replicates < 1:
        raise ValueError("Las réplicas deben ser positivas.")
    market_dir = args.market_dir.resolve()
    participation_dir = args.participation_dir.resolve()
    awards_dir = args.awards_dir.resolve()
    output_dir = args.output_dir.resolve()
    _require_published(market_dir, ("p1_processes", "buyer_segment_method"))
    _require_published(participation_dir, ("fact_tenderer",))
    _require_published(awards_dir)
    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output_dir}; use --overwrite para regenerar.")

    units = pd.read_parquet(market_dir / "buyer_segment_method")
    processes = pd.read_parquet(market_dir / "p1_processes")
    awards = pd.read_parquet(awards_dir)
    awards = awards.loc[
        awards["award_year"].between(args.start_award_year, args.end_award_year)
    ].copy()
    events = processes[UNIT_KEYS + ["process_ocid"]].merge(
        awards[
            [
                "process_ocid",
                "award_id",
                "supplier_id",
                "supplier_name",
                "award_amount_single_supplier",
                "award_currency",
            ]
        ],
        on="process_ocid",
        how="inner",
        validate="one_to_many",
    )
    events = events.drop_duplicates(UNIT_KEYS + ["process_ocid", "award_id", "supplier_id"])

    tenderers = pd.read_parquet(
        participation_dir / "fact_tenderer", columns=["process_ocid", "participant_id"]
    )
    tenderers = tenderers.loc[tenderers["process_ocid"].isin(processes["process_ocid"])].dropna()
    candidate_ids = {
        process: np.sort(group["participant_id"].astype(str).unique())
        for process, group in tenderers.groupby("process_ocid", sort=False)
        if len(group)
    }
    winner_reported = events.merge(
        tenderers.rename(columns={"participant_id": "supplier_id"}),
        on=["process_ocid", "supplier_id"],
        how="left",
        indicator=True,
    )

    result_rows: list[dict[str, object]] = []
    for threshold in sorted(set(args.min_processes)):
        for measure in (PRIMARY_PARTICIPATION, ALTERNATIVE_PARTICIPATION):
            for adjusted in (False, True):
                estimate = association(units, measure, threshold, adjusted)
                row: dict[str, object] = {
                    "scenario": "all_awards",
                    "participation_measure": measure,
                    "minimum_processes": threshold,
                    "adjustment": "stratum_centered" if adjusted else "raw",
                    **estimate,
                }
                if measure == PRIMARY_PARTICIPATION:
                    row.update(
                        bootstrap_by_buyer(
                            units,
                            measure,
                            threshold,
                            adjusted,
                            args.bootstrap_replicates,
                            args.seed + threshold + int(adjusted),
                        )
                    )
                result_rows.append(row)

    without_consortia = hhi_from_events(
        events.loc[~consortium_mask(events["supplier_name"])], units
    )
    for threshold in sorted(set(args.min_processes)):
        for measure in (PRIMARY_PARTICIPATION, ALTERNATIVE_PARTICIPATION):
            for adjusted in (False, True):
                result_rows.append(
                    {
                        "scenario": "without_consortia_name",
                        "participation_measure": measure,
                        "minimum_processes": threshold,
                        "adjustment": "stratum_centered" if adjusted else "raw",
                        **association(without_consortia, measure, threshold, adjusted),
                    }
                )
    monetary_events = events.loc[
        (events["award_currency"] == "PEN") & (events["award_amount_single_supplier"] > 0)
    ]
    monetary_hhi = hhi_from_events(monetary_events, units, "award_amount_single_supplier")
    for threshold in sorted(set(args.min_processes)):
        for measure in (PRIMARY_PARTICIPATION, ALTERNATIVE_PARTICIPATION):
            for adjusted in (False, True):
                row = {
                    "scenario": "amount_hhi_pen",
                    "participation_measure": measure,
                    "minimum_processes": threshold,
                    "adjustment": "stratum_centered" if adjusted else "raw",
                    **association(monetary_hhi, measure, threshold, adjusted),
                }
                if measure == PRIMARY_PARTICIPATION:
                    row.update(
                        bootstrap_by_buyer(
                            monetary_hhi,
                            measure,
                            threshold,
                            adjusted,
                            args.bootstrap_replicates,
                            args.seed + 100 + threshold + int(adjusted),
                        )
                    )
                result_rows.append(row)
    results = pd.DataFrame(result_rows)

    null_draws, null_coverage = null_associations(
        events,
        candidate_ids,
        units,
        sorted(set(args.min_processes)),
        args.null_replicates,
        args.seed,
    )
    null_summary = null_draws.groupby(["minimum_processes", "adjustment"], as_index=False)[
        "correlation"
    ].agg(
        null_mean="mean",
        null_ci_low=lambda values: values.quantile(0.025),
        null_ci_high=lambda values: values.quantile(0.975),
    )
    actual_primary = results.loc[
        (results["scenario"] == "all_awards")
        & (results["participation_measure"] == PRIMARY_PARTICIPATION),
        ["minimum_processes", "adjustment", "correlation"],
    ].rename(columns={"correlation": "actual_correlation"})
    null_summary = actual_primary.merge(
        null_summary, on=["minimum_processes", "adjustment"], how="inner", validate="one_to_one"
    )
    null_summary["share_null_at_or_below_actual"] = null_summary.apply(
        lambda row: float(
            (
                null_draws.loc[
                    (null_draws["minimum_processes"] == row["minimum_processes"])
                    & (null_draws["adjustment"] == row["adjustment"]),
                    "correlation",
                ]
                <= row["actual_correlation"]
            ).mean()
        ),
        axis=1,
    )

    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    results.to_csv(stage / "association_results.csv", index=False)
    null_summary.to_csv(stage / "null_summary.csv", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "market_dir": str(market_dir),
            "participation_dir": str(participation_dir),
            "awards_dir": str(awards_dir),
            "award_window": [args.start_award_year, args.end_award_year],
        },
        "design": {
            "unit": UNIT_KEYS,
            "minimum_processes": sorted(set(args.min_processes)),
            "primary_participation": PRIMARY_PARTICIPATION,
            "alternative_participation": ALTERNATIVE_PARTICIPATION,
            "adjustment": (
                "Centra HHI y participación en la mediana del estrato "
                "departamento×CUBSO×modalidad×tramo de procesos; conserva "
                "estratos con al menos 3 unidades."
            ),
            "bootstrap": {
                "cluster": "buyer_id",
                "replicates": args.bootstrap_replicates,
                "seed": args.seed,
            },
            "null": {
                "description": (
                    "Para cada evento de adjudicación, sortea uniformemente un ganador "
                    "entre participantes reportados del proceso."
                ),
                "replicates": args.null_replicates,
                "seed": args.seed,
            },
            "consortium_sensitivity": (
                "Excluye eventos cuyo supplier_name contiene la palabra CONSORCIO; "
                "es una heurística por nombre, no una desagregación legal."
            ),
            "amount_sensitivity": (
                "Recalcula HHI con award_amount_single_supplier solo cuando la moneda es PEN "
                "y el monto es positivo; no convierte USD ni EUR."
            ),
        },
        "coverage": {
            "market_units": int(len(units)),
            "selected_processes": int(processes["process_ocid"].nunique()),
            "award_events": int(len(events)),
            "award_events_positive_pen": int(len(monetary_events)),
            "award_events_winner_in_reported_participants": int(
                (winner_reported["_merge"] == "both").sum()
            ),
            **null_coverage,
        },
        "files": ["association_results.csv", "null_summary.csv"],
    }
    _write_json(stage / "metadata.json", metadata)
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"Análisis P1 publicado: {output_dir}")


if __name__ == "__main__":
    run()
