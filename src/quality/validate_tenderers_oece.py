"""Contrasta los participantes reportados en OCDS con el Listado de ofertantes de OECE.

Corre en local con pandas: los listados de OECE suman unas 850 mil filas y se cruzan por proceso
con las tablas de participación ya publicadas.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.processing.build_fact_award_item import publish_output, staging_dir

OCDS_PREFIX = "PE-RUC-"
OECE_COLUMNS = {
    "CODIGO_CONVOCATORIA": "tender_id",
    "RUC_CODIGO_POSTOR": "code",
    "POSTOR": "participant_name",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oece-dir", type=Path, default=Path("data/raw/oece"))
    parser.add_argument("--years", nargs="+", type=int, default=[2021, 2022, 2023, 2024])
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument(
        "--participation-output", type=Path, default=Path("data/processed/participation_oece")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/oece_validation"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_bidders(oece_dir: Path, years: list[int]) -> pd.DataFrame:
    frames = []
    for year in years:
        path = oece_dir / f"POSTOR{year}_0.xlsx"
        if not path.is_file():
            raise FileNotFoundError(f"Falta {path}; use python -m scripts.download_oece.")
        frames.append(pd.read_excel(path, dtype=str, usecols=list(OECE_COLUMNS)))
    bidders = pd.concat(frames, ignore_index=True).rename(columns=OECE_COLUMNS)
    bidders = bidders.dropna(subset=["tender_id", "code"])
    bidders["tender_id"] = bidders["tender_id"].str.strip()
    bidders["code"] = bidders["code"].str.strip()
    return bidders.drop_duplicates(["tender_id", "code"]).reset_index(drop=True)


def matched_tenders(tenders: pd.DataFrame, bidders: pd.DataFrame) -> pd.DataFrame:
    keyed = tenders.assign(tender_id=tenders["tender_id"].astype(str).str.strip())
    return keyed.loc[keyed["tender_id"].isin(set(bidders["tender_id"]))].copy()


def compare_sets(
    tenders: pd.DataFrame, tenderers: pd.DataFrame, bidders: pd.DataFrame
) -> pd.DataFrame:
    """Count, per matched process, reported participants, OECE bidders and their overlap."""
    matched = matched_tenders(tenders, bidders)
    reported = tenderers[["process_ocid", "participant_id"]].drop_duplicates()
    reported = reported.assign(code=reported["participant_id"].str.removeprefix(OCDS_PREFIX))
    reported = reported.loc[
        reported["process_ocid"].isin(matched["process_ocid"]), ["process_ocid", "code"]
    ]
    offered = matched[["process_ocid", "tender_id"]].merge(
        bidders[["tender_id", "code"]], on="tender_id"
    )
    joined = reported.merge(
        offered[["process_ocid", "code"]], on=["process_ocid", "code"], how="outer", indicator=True
    )
    counts = (
        joined.groupby("process_ocid")["_merge"]
        .value_counts()
        .unstack(fill_value=0)
        .reindex(columns=["left_only", "right_only", "both"], fill_value=0)
    )
    counts.columns = counts.columns.astype(str)
    per_process = matched.set_index("process_ocid")[
        ["source_year", "procurement_method_details", "number_of_tenderers"]
    ].join(counts)
    per_process[["left_only", "right_only", "both"]] = (
        per_process[["left_only", "right_only", "both"]].fillna(0).astype(int)
    )
    per_process["reported"] = per_process["left_only"] + per_process["both"]
    per_process["bidders"] = per_process["right_only"] + per_process["both"]
    per_process["shared"] = per_process["both"]
    per_process["identical"] = (per_process["left_only"] == 0) & (per_process["right_only"] == 0)
    return per_process.drop(columns=["left_only", "right_only", "both"]).reset_index()


def summarize(per_process: pd.DataFrame, by: str | None) -> pd.DataFrame:
    keys = per_process[by] if by else pd.Series("total", index=per_process.index)
    result = per_process.groupby(keys.astype(str).rename("group")).agg(
        processes=("process_ocid", "size"),
        reported=("reported", "sum"),
        bidders=("bidders", "sum"),
        shared=("shared", "sum"),
        reported_median=("reported", "median"),
        bidders_median=("bidders", "median"),
        identical_share=("identical", "mean"),
    )
    result["reported_that_bid"] = result["shared"] / result["reported"]
    result["bidders_in_reported"] = result["shared"] / result["bidders"]
    return result.reset_index().assign(level=by or "total")


def bidder_participation(
    tenders: pd.DataFrame, tenderers: pd.DataFrame, bidders: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rebuild fact_tender and fact_tenderer with OECE bidders as participants."""
    matched = matched_tenders(tenders, bidders)
    rows = matched[["source_year", "process_ocid", "buyer_id", "tender_id"]].merge(
        bidders, on="tender_id"
    )
    fact_tenderer = pd.DataFrame(
        {
            "source_year": rows["source_year"].astype(tenderers["source_year"].dtype),
            "process_ocid": rows["process_ocid"],
            "buyer_id": rows["buyer_id"],
            "participant_id": OCDS_PREFIX + rows["code"],
            "participant_name": rows["participant_name"],
            "first_participant_position": pd.array([pd.NA] * len(rows), dtype="Int32"),
            "duplicate_rows_in_source": pd.array([1] * len(rows), dtype="Int32"),
        }
    )
    counts = fact_tenderer.groupby("process_ocid").size()
    fact_tender = tenders.loc[tenders["process_ocid"].isin(matched["process_ocid"])].copy()
    fact_tender["tenderer_list_count"] = (
        fact_tender["process_ocid"].map(counts).astype(tenders["tenderer_list_count"].dtype)
    )
    return fact_tender.reset_index(drop=True), fact_tenderer


def join_coverage(tenders: pd.DataFrame, bidders: pd.DataFrame) -> dict:
    """Describe how process ids map to OECE call codes and which processes stay unmatched."""
    keyed = tenders.assign(tender_id=tenders["tender_id"].astype(str).str.strip())
    matched = keyed["tender_id"].isin(set(bidders["tender_id"]))
    per_code = keyed.loc[matched].groupby("tender_id")["process_ocid"].nunique()
    unmatched = keyed.loc[~matched]
    return {
        "matched_call_codes": int(per_code.size),
        "call_codes_with_several_processes": int((per_code > 1).sum()),
        "processes_sharing_a_call_code": int(per_code[per_code > 1].sum()),
        "unmatched_processes": int(len(unmatched)),
        "unmatched_by_source_year": {
            str(k): int(v) for k, v in unmatched["source_year"].value_counts().items()
        },
        "unmatched_by_method": {
            str(k): int(v)
            for k, v in unmatched["procurement_method_details"].value_counts().items()
        },
    }


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.mkdir(parents=True)
    frame.to_parquet(
        path / "part-00000.parquet",
        index=False,
        coerce_timestamps="us",
        allow_truncated_timestamps=True,
    )
    (path / "_SUCCESS").touch()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run() -> None:
    args = parse_args()
    participation_dir = args.participation_dir.resolve()
    participation_output = args.participation_output.resolve()
    output_dir = args.output_dir.resolve()
    for child in ("fact_tender", "fact_tenderer", "dim_buyer"):
        if not (participation_dir / child / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Falta la tabla de participación completa: {child}")
    for target in (participation_output, output_dir):
        if target.exists() and not args.overwrite:
            raise FileExistsError(f"Ya existe {target}; use --overwrite para regenerar.")

    bidders = load_bidders(args.oece_dir.resolve(), args.years)
    tenders = pd.read_parquet(participation_dir / "fact_tender")
    tenderers = pd.read_parquet(participation_dir / "fact_tenderer")
    buyers = pd.read_parquet(participation_dir / "dim_buyer")

    per_process = compare_sets(tenders, tenderers, bidders)
    comparison = pd.concat(
        [
            summarize(per_process, None),
            summarize(per_process, "source_year"),
            summarize(per_process, "procurement_method_details"),
        ],
        ignore_index=True,
    )
    fact_tender, fact_tenderer = bidder_participation(tenders, tenderers, bidders)

    stage = staging_dir(participation_output)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    write_table(fact_tender, stage / "fact_tender")
    write_table(fact_tenderer, stage / "fact_tenderer")
    write_table(buyers, stage / "dim_buyer")
    write_json(
        stage / "_metadata.json",
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "Listado de ofertantes OECE (CONOSCE)",
            "years": args.years,
            "rule": "Participantes = ofertantes OECE del mismo tender_id; solo procesos cruzados.",
            "tenderer_list_count": "número de ofertantes OECE del proceso",
            "number_of_tenderers": "valor OCDS original, sin reemplazar",
            "shared_call_codes": "una convocatoria con varios OCID repite sus ofertantes",
            "processes": len(fact_tender),
            "participant_rows": len(fact_tenderer),
        },
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, participation_output)

    total = comparison.loc[comparison["level"] == "total"].iloc[0]
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    comparison.to_csv(stage / "comparison.csv", index=False)
    per_process.to_parquet(stage / "per_process.parquet", index=False)
    write_json(
        stage / "summary.json",
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "oece_years": args.years,
            "oece_bidder_rows": len(bidders),
            "ocds_processes": len(tenders),
            "matched_processes": int(total["processes"]),
            "matched_share": float(total["processes"] / len(tenders)),
            "reported_rows": int(total["reported"]),
            "bidder_rows": int(total["bidders"]),
            "shared_rows": int(total["shared"]),
            "reported_that_bid": float(total["reported_that_bid"]),
            "bidders_in_reported": float(total["bidders_in_reported"]),
            "identical_share": float(total["identical_share"]),
            "number_of_tenderers_equals_bidders": float(
                (per_process["number_of_tenderers"] == per_process["bidders"]).mean()
            ),
            "join_key": "fact_tender.tender_id = CODIGO_CONVOCATORIA",
            "row_unit": "participaciones proceso × participante en los procesos cruzados",
            **join_coverage(tenders, bidders),
        },
    )
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(
        json.dumps(
            {k: total[k] for k in ("processes", "reported_that_bid", "bidders_in_reported")},
            default=float,
        )
    )


if __name__ == "__main__":
    run()
