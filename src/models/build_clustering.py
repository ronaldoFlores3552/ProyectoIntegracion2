"""Evalúa KMeans++ y HDBSCAN sobre perfiles descriptivos de entidades."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path

import hdbscan
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from src.features.build_part1 import directory_fingerprint
from src.processing.build_fact_award_item import publish_output, staging_dir
from src.quality.profile_fact_award_item import write_json_atomically

SEED = 42
MAX_BYTES = 256 * 1024 * 1024


def read_input(part1: Path, suppliers: Path, categories: Path, max_rows: int):
    if not (part1 / "_SUCCESS").is_file() or not (part1 / "entity_features" / "_SUCCESS").is_file():
        raise FileNotFoundError("Falta la publicación completa de vectores de la Parte I.")
    meta = json.loads((part1 / "_metadata.json").read_text(encoding="utf-8"))
    if meta.get("window") != {"start_award_year": 2023, "end_award_year": 2024}:
        raise ValueError("Se requiere la ventana descriptiva de adjudicación 2023–2024.")
    for path, key in ((suppliers, "supplier_sha256"), (categories, "category_sha256")):
        if not (path / "_SUCCESS").is_file():
            raise FileNotFoundError(f"Entrada de interacciones incompleta: {path}")
        info = json.loads((path / "_metadata.json").read_text(encoding="utf-8"))
        if (
            info.get("run_id") != meta["lineage"]["run_id"]
            or directory_fingerprint(path) != meta["lineage"][key]
        ):
            raise ValueError(f"Las interacciones cambiaron desde la Parte I: {path}")
    names = meta.get("category_names")
    if names != ["goods", "services", "works"]:
        raise ValueError(f"Categorías distintas a las evaluadas; revisar el diseño: {names}")
    folder = part1 / "entity_features"
    size = sum(path.stat().st_size for path in folder.rglob("*.parquet"))
    if size > MAX_BYTES:
        raise ValueError(f"Los archivos exceden el límite local de {MAX_BYTES} bytes.")
    dataset = ds.dataset(folder, format="parquet", exclude_invalid_files=True)
    n = dataset.count_rows()
    if n > max_rows or n < 9 or n != meta.get("features"):
        raise ValueError(f"Número de filas inválido o superior al límite: {n}.")
    cols = ["entity_id", "award_count", "log_award_count"] + [f"fraction_{i}" for i in range(3)]
    frame = (
        dataset.to_table(columns=cols).to_pandas().sort_values("entity_id").reset_index(drop=True)
    )
    if (
        frame.entity_id.isna().any()
        or frame.entity_id.str.strip().eq("").any()
        or frame.entity_id.duplicated().any()
    ):
        raise ValueError("Identificadores ausentes o duplicados.")
    values = frame[cols[1:]].to_numpy(dtype=float)
    if (
        not np.isfinite(values).all()
        or (values[:, 0] <= 0).any()
        or not np.allclose(values[:, 1], np.log1p(values[:, 0]))
        or (values[:, 2:] < 0).any()
        or (values[:, 2:] > 1).any()
        or not np.allclose(values[:, 2:].sum(axis=1), 1)
    ):
        raise ValueError("Valores de características inválidos.")
    if int(frame.award_count.sum()) != meta["category_count_eligible"]:
        raise ValueError("El conteo de adjudicaciones no concilia con los metadatos.")
    return frame, meta, size


def prepare(frame: pd.DataFrame):
    columns = ["log_award_count", "fraction_0", "fraction_1", "fraction_2"]
    scaler = StandardScaler().fit(frame[columns])
    standard = scaler.transform(frame[columns])
    weighted = standard.copy()
    weighted[:, 1:] /= math.sqrt(3)
    return {"standard": standard, "weighted": weighted}, {
        "columns": columns,
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "variance": scaler.var_.tolist(),
        "weighted_category_factor": 1 / math.sqrt(3),
        "fit_population": "ventana descriptiva completa; no apto para evaluación temporal",
    }


def valid_silhouette(x: np.ndarray, labels: np.ndarray, *, ignore_noise: bool = False):
    selected = labels != -1 if ignore_noise else np.ones(len(labels), dtype=bool)
    y = labels[selected]
    if len(y) < 3 or not 1 < len(np.unique(y)) < len(y):
        return None
    return float(silhouette_score(x[selected], y, sample_size=min(1500, len(y)), random_state=SEED))


def fit_experiments(frame: pd.DataFrame, matrices: dict):
    n = len(frame)
    all_assignments, kmetrics, hmetrics = [], [], []
    models = {}
    for variant, x in matrices.items():
        for k in range(2, min(8, n - 1) + 1):
            model = KMeans(n_clusters=k, init="k-means++", n_init=20, random_state=SEED)
            labels = model.fit_predict(x)
            distances = model.transform(x)[np.arange(n), labels]
            counts = np.bincount(labels, minlength=k)
            kmetrics.append(
                {
                    "variant": variant,
                    "k": k,
                    "inertia": float(model.inertia_),
                    "silhouette": valid_silhouette(x, labels),
                    "min_cluster_size": int(counts.min()),
                    "max_cluster_size": int(counts.max()),
                }
            )
            models[("kmeans", variant, k)] = labels
            all_assignments.append(
                pd.DataFrame(
                    {
                        "entity_id": frame.entity_id,
                        "method": "kmeans",
                        "variant": variant,
                        "config": str(k),
                        "label": labels,
                        "distance": distances,
                        "probability": np.nan,
                    }
                )
            )
        for size in (15, 30, 60):
            for samples in (5, 10):
                if size >= n:
                    continue
                model = hdbscan.HDBSCAN(
                    min_cluster_size=size, min_samples=samples, core_dist_n_jobs=1
                )
                labels = model.fit_predict(x)
                assigned = labels != -1
                groups = len(set(labels) - {-1})
                config = f"{size}:{samples}"
                hmetrics.append(
                    {
                        "variant": variant,
                        "min_cluster_size": size,
                        "min_samples": samples,
                        "groups": groups,
                        "noise_count": int((~assigned).sum()),
                        "noise_fraction": float((~assigned).mean()),
                        "coverage": float(assigned.mean()),
                        "silhouette_assigned": valid_silhouette(x, labels, ignore_noise=True),
                        "mean_cluster_persistence": float(np.mean(model.cluster_persistence_))
                        if groups
                        else None,
                    }
                )
                models[("hdbscan", variant, config)] = labels
                all_assignments.append(
                    pd.DataFrame(
                        {
                            "entity_id": frame.entity_id,
                            "method": "hdbscan",
                            "variant": variant,
                            "config": config,
                            "label": labels,
                            "distance": np.nan,
                            "probability": model.probabilities_,
                        }
                    )
                )
    return (
        pd.concat(all_assignments, ignore_index=True),
        pd.DataFrame(kmetrics),
        pd.DataFrame(hmetrics),
        models,
    )


def choose_models(kmetrics: pd.DataFrame, hmetrics: pd.DataFrame, n: int):
    # Reglas declaradas antes de la ejecución: evitar grupos demasiado pequeños o ruido mayoritario.
    keligible = kmetrics[
        (kmetrics.variant == "weighted")
        & (kmetrics.min_cluster_size >= max(15, math.ceil(n * 0.01)))
    ].dropna(subset=["silhouette"])
    h_eligible = hmetrics[
        (hmetrics.variant == "weighted") & (hmetrics.groups >= 2) & (hmetrics.coverage >= 0.5)
    ].dropna(subset=["silhouette_assigned"])
    kbest = (
        keligible.sort_values(["silhouette", "k"], ascending=[False, True]).iloc[0].to_dict()
        if len(keligible)
        else None
    )
    hbest = (
        h_eligible.sort_values(
            ["silhouette_assigned", "coverage", "min_cluster_size", "min_samples"],
            ascending=[False, False, True, True],
        )
        .iloc[0]
        .to_dict()
        if len(h_eligible)
        else None
    )
    return kbest, hbest


def add_flags(assignments: pd.DataFrame, kbest, hbest):
    assignments = assignments.copy()
    assignments["selected"] = False
    if kbest:
        mask = (
            (assignments.method == "kmeans")
            & (assignments.variant == "weighted")
            & (assignments.config == str(int(kbest["k"])))
        )
        assignments.loc[mask, "selected"] = True
    if hbest:
        config = f"{int(hbest['min_cluster_size'])}:{int(hbest['min_samples'])}"
        mask = (
            (assignments.method == "hdbscan")
            & (assignments.variant == "weighted")
            & (assignments.config == config)
        )
        assignments.loc[mask, "selected"] = True
    assignments["outlier_candidate"] = False
    hmask = (assignments.method == "hdbscan") & assignments.selected & (assignments.label == -1)
    assignments.loc[hmask, "outlier_candidate"] = True
    kmask = (assignments.method == "kmeans") & assignments.selected
    for _, group in assignments[kmask].groupby("label"):
        if len(group) >= 100:
            ordered = group.sort_values(["distance", "entity_id"], ascending=[False, True])
            assignments.loc[
                ordered.head(math.ceil(len(group) * 0.01)).index, "outlier_candidate"
            ] = True
    return assignments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part1-dir", type=Path, default=Path("data/processed/part1"))
    parser.add_argument(
        "--suppliers-dir", type=Path, default=Path("data/processed/entity_supplier_year")
    )
    parser.add_argument(
        "--categories-dir", type=Path, default=Path("data/processed/entity_category_year")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/clustering"))
    parser.add_argument("--max-rows", type=int, default=10000)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    part1, suppliers, categories, output = [
        p.resolve()
        for p in (args.part1_dir, args.suppliers_dir, args.categories_dir, args.output_dir)
    ]
    for target in (output, staging_dir(output), output.with_name(output.name + ".previous")):
        for source in (part1, suppliers, categories):
            if target == source or target in source.parents or source in target.parents:
                raise ValueError(f"Salida solapada con una entrada: {target}")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite.")
    frame, source_meta, input_bytes = read_input(part1, suppliers, categories, args.max_rows)
    fingerprints = {"part1_sha256": directory_fingerprint(part1), **source_meta["lineage"]}
    with threadpool_limits(limits=1):
        matrices, scaling = prepare(frame)
        assignments, kmetrics, hmetrics, models = fit_experiments(frame, matrices)
        kbest, hbest = choose_models(kmetrics, hmetrics, len(frame))
        assignments = add_flags(assignments, kbest, hbest)
        stability = []
        if kbest:
            k = int(kbest["k"])
            reference = models[("kmeans", "weighted", k)]
            for seed in (1, 7, 21, 42, 100):
                rng = np.random.default_rng(seed)
                sample = np.sort(rng.choice(len(frame), size=int(0.8 * len(frame)), replace=False))
                x = matrices["weighted"][sample]
                labels = KMeans(
                    n_clusters=k, init="k-means++", n_init=20, random_state=seed
                ).fit_predict(x)
                stability.append(
                    {
                        "method": "kmeans",
                        "seed": seed,
                        "sample_size": len(sample),
                        "ari_vs_full_on_sample": float(
                            adjusted_rand_score(reference[sample], labels)
                        ),
                    }
                )
        comparisons = []
        if kbest:
            k = int(kbest["k"])
            comparisons.append(
                {
                    "method": "kmeans",
                    "config": str(k),
                    "ari_between_scalings": float(
                        adjusted_rand_score(
                            models[("kmeans", "weighted", k)], models[("kmeans", "standard", k)]
                        )
                    ),
                }
            )
        if hbest:
            config = f"{int(hbest['min_cluster_size'])}:{int(hbest['min_samples'])}"
            a, b = models[("hdbscan", "weighted", config)], models[("hdbscan", "standard", config)]
            both = (a != -1) & (b != -1)
            comparisons.append(
                {
                    "method": "hdbscan",
                    "config": config,
                    "ari_between_scalings": float(adjusted_rand_score(a, b)),
                    "both_assigned_count": int(both.sum()),
                    "ari_both_assigned": float(adjusted_rand_score(a[both], b[both]))
                    if both.sum() > 1
                    else None,
                }
            )
    selected = assignments[assignments.selected].merge(
        frame, on="entity_id", validate="many_to_one"
    )
    profiles = (
        selected.groupby(["method", "label"], dropna=False)
        .agg(
            entities=("entity_id", "size"),
            median_awards=("award_count", "median"),
            median_goods=("fraction_0", "median"),
            median_services=("fraction_1", "median"),
            median_works=("fraction_2", "median"),
        )
        .reset_index()
    )
    summary = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": fingerprints,
        "source_window": source_meta["window"],
        "input_rows": len(frame),
        "input_parquet_bytes": input_bytes,
        "source_awards": int(frame.award_count.sum()),
        "categories": source_meta["category_names"],
        "seed": SEED,
        "scaling": scaling,
        "selection_policy": {
            "variant": "weighted",
            "kmeans": "máxima silueta con grupos >= 1% y 15",
            "hdbscan": "máxima silueta asignada con >= 2 grupos y cobertura >= 50%",
            "silhouette_sample_max": 1500,
            "kmeans_n_init": 20,
        },
        "kmeans_selected": kbest,
        "hdbscan_selected": hbest,
        "stability": stability,
        "scaling_comparison": comparisons,
        "python": platform.python_version(),
        "versions": {
            p: importlib.metadata.version(p)
            for p in ["numpy", "pandas", "scikit-learn", "hdbscan", "pyarrow"]
        },
        "interpretation": "Perfiles descriptivos; ruido y distancia no prueban irregularidades.",
    }
    stage = staging_dir(output)
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    for name, data in [
        ("features", frame),
        ("assignments", assignments),
        ("kmeans_metrics", kmetrics),
        ("hdbscan_metrics", hmetrics),
        ("profiles", profiles),
    ]:
        data.to_parquet(stage / f"{name}.parquet", index=False)
    write_json_atomically(stage / "_metadata.json", summary)
    (stage / "_SUCCESS").touch()
    publish_output(stage, output)
    print(f"Clustering publicado: {output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
