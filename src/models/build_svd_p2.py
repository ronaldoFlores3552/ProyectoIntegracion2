"""Publica SVD de la matriz comprador-proveedor adjudicado o comprador-participante de P2.

Corre en local con scipy y scikit-learn: la matriz tiene 2 756 compradores en filas y es dispersa.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize

from src.processing.build_fact_award_item import publish_output, staging_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market-dir", type=Path, default=Path("data/processed/market_p2"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2/svd"))
    parser.add_argument("--matrix", choices=["award", "participation"], default="award")
    parser.add_argument("--min-processes", type=int, default=5)
    parser.add_argument("--components", type=int, default=8)
    parser.add_argument(
        "--participation-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def build_matrix(edges: pd.DataFrame) -> tuple[sparse.csr_matrix, pd.Index, pd.Index]:
    buyer_codes, buyers = pd.factorize(edges.buyer_id, sort=True)
    supplier_codes, suppliers = pd.factorize(edges.supplier_id, sort=True)
    matrix = sparse.coo_matrix(
        (edges.award_count.to_numpy(float), (buyer_codes, supplier_codes)),
        shape=(len(buyers), len(suppliers)),
    ).tocsr()
    return matrix, buyers, suppliers


def build_participation_matrix(
    edges: pd.DataFrame, recurrence: pd.Series, min_processes: int
) -> tuple[sparse.csr_matrix, pd.Index, pd.Index]:
    edges = edges.loc[edges.participant_id.isin(recurrence[recurrence >= min_processes].index)]
    buyer_codes, buyers = pd.factorize(edges.buyer_id, sort=True)
    participant_codes, participants = pd.factorize(edges.participant_id, sort=True)
    counts = sparse.coo_matrix(
        (np.log1p(edges.process_count.to_numpy(float)), (buyer_codes, participant_codes)),
        shape=(len(buyers), len(participants)),
    ).tocsr()
    document_frequency = np.asarray((counts > 0).sum(axis=0)).ravel()
    idf = np.log(len(buyers) / document_frequency)
    return normalize(counts @ sparse.diags(idf)).tocsr(), buyers, participants


def run() -> None:
    args = parse_args()
    market_dir, output_dir = args.market_dir.resolve(), args.output_dir.resolve()
    if (
        not (market_dir / "_SUCCESS").is_file()
        or not (market_dir / "graph_award_edges" / "_SUCCESS").is_file()
    ):
        raise FileNotFoundError("Falta graph_award_edges publicado.")
    if args.components < 2 or output_dir.exists() and not args.overwrite:
        raise ValueError("Componentes inválidos o salida existente sin --overwrite.")
    if args.matrix == "award":
        matrix, buyers, suppliers = build_matrix(pd.read_parquet(market_dir / "graph_award_edges"))
        weight = "award_count"
    else:
        edges = pd.read_parquet(market_dir / "graph_participation_edges")
        recurrence = (
            pd.read_parquet(
                args.participation_dir / "fact_tenderer",
                columns=["participant_id", "process_ocid"],
            )
            .drop_duplicates()
            .groupby("participant_id")
            .size()
        )
        matrix, buyers, suppliers = build_participation_matrix(
            edges, recurrence, args.min_processes
        )
        weight = "log1p(process_count) por idf de participante, filas con norma 1"
    if args.components >= min(matrix.shape):
        raise ValueError("El número de componentes debe ser menor que ambas dimensiones.")
    model = TruncatedSVD(n_components=args.components, n_iter=10, random_state=args.seed)
    buyer_coordinates = model.fit_transform(matrix)
    row_energy = np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel()
    captured = (buyer_coordinates**2).sum(axis=1) / np.where(row_energy > 0, row_energy, 1.0)
    supplier_coordinates = model.components_.T
    stage = staging_dir(output_dir)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "buyer_id": buyers,
            **{f"svd_{i + 1}": buyer_coordinates[:, i] for i in range(args.components)},
            "captured_energy": captured,
        }
    ).to_parquet(stage / "buyer_coordinates.parquet", index=False)
    pd.DataFrame(
        {
            ("supplier_id" if args.matrix == "award" else "participant_id"): suppliers,
            **{f"svd_{i + 1}": supplier_coordinates[:, i] for i in range(args.components)},
        }
    ).to_parquet(stage / "supplier_coordinates.parquet", index=False)
    metadata = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix": {
            "rows_buyers": matrix.shape[0],
            "columns_suppliers": matrix.shape[1],
            "nonzero": int(matrix.nnz),
            "matrix": args.matrix,
            "weight": weight,
        },
        "components": args.components,
        "seed": args.seed,
        "explained_variance_ratio": model.explained_variance_ratio_.tolist(),
        "explained_variance_ratio_sum": float(model.explained_variance_ratio_.sum()),
        "captured_energy_quantiles": {
            str(q): float(np.quantile(captured, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)
        },
        "files": ["buyer_coordinates.parquet", "supplier_coordinates.parquet"],
    }
    (stage / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (stage / "_SUCCESS").touch()
    publish_output(stage, output_dir)
    print(f"SVD P2 publicado: {output_dir}")


if __name__ == "__main__":
    run()
