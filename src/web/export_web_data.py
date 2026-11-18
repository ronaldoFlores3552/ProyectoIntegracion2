"""Exporta los artefactos del proyecto a JSON ligeros para el reporte web.

Corre en local: lee artefactos pequeños y escribe JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from src.models.partition_subgraph_p2 import department_graph, department_rows, giant_component

SEGMENTS = {
    "10": "Material vivo vegetal y animal",
    "11": "Minerales, textiles y fibras",
    "12": "Químicos",
    "13": "Resinas y cauchos",
    "14": "Papel",
    "15": "Combustibles y lubricantes",
    "20": "Maquinaria de minería",
    "21": "Maquinaria agrícola",
    "22": "Maquinaria de construcción",
    "23": "Maquinaria industrial",
    "24": "Manejo de materiales",
    "25": "Vehículos y accesorios",
    "26": "Generación eléctrica",
    "27": "Herramientas",
    "30": "Materiales de construcción",
    "31": "Componentes de fabricación",
    "32": "Componentes electrónicos",
    "39": "Iluminación y material eléctrico",
    "40": "Sistemas de distribución y climatización",
    "41": "Laboratorio y medición",
    "42": "Equipo médico",
    "43": "Tecnologías de la información",
    "44": "Equipos y útiles de oficina",
    "45": "Imprenta y audiovisuales",
    "46": "Seguridad y defensa",
    "47": "Limpieza",
    "48": "Equipos para servicios",
    "49": "Deportes y recreación",
    "50": "Alimentos y bebidas",
    "51": "Medicamentos",
    "52": "Artículos para el hogar",
    "53": "Ropa y aseo personal",
    "55": "Publicaciones",
    "56": "Muebles",
    "60": "Material educativo",
    "70": "Servicios agrícolas",
    "71": "Servicios de minería",
    "72": "Construcción y mantenimiento",
    "73": "Producción industrial",
    "76": "Limpieza y descontaminación",
    "77": "Servicios medioambientales",
    "78": "Transporte y almacenaje",
    "80": "Gestión y administración",
    "81": "Ingeniería e investigación",
    "82": "Diseño y publicidad",
    "83": "Servicios públicos",
    "84": "Servicios financieros y seguros",
    "85": "Salud",
    "86": "Educación y formación",
    "90": "Viajes, alimentación y hotelería",
    "91": "Servicios personales",
    "92": "Servicios de seguridad",
    "93": "Asuntos cívicos",
    "94": "Organizaciones",
    "95": "Terrenos y edificios",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/web_data"))
    parser.add_argument("--department", default="PUNO")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rounded(values, digits: int = 4) -> list:
    return [None if pd.isna(v) else round(float(v), digits) for v in values]


def actor_type(identifier: str, name: str | None) -> str:
    if name and "CONSORCIO" in name.upper():
        return "Consorcio"
    if identifier.startswith("PE-RUC-10"):
        return "Persona natural"
    if identifier.startswith("PE-RUC-20"):
        return "Empresa"
    return "Otro"


def write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )


def summary(processed: Path, artifacts: Path) -> dict:
    participation = read_json(processed / "participation" / "_metadata.json")
    diagnostics = read_json(artifacts / "p2" / "diagnostics" / "summary.json")
    links = read_json(artifacts / "p2" / "links" / "metadata.json")
    return {
        "participation": {name: table["rows"] for name, table in participation["tables"].items()},
        "projection": diagnostics["projection"],
        "components": diagnostics["components"],
        "hits": links["hits"],
        "pagerank": {k: links["pagerank"][k] for k in ("nodes", "undirected_edges", "damping")},
    }


def p1_units(market: Path) -> pd.DataFrame:
    units = pd.read_parquet(market / "buyer_segment_method")
    return units.loc[units.process_count >= 5].dropna(
        subset=["hhi", "reported_participants_median"]
    )


def p1_columns(units: pd.DataFrame) -> dict:
    return {
        "department": units.department.tolist(),
        "segment": units.cubso_segment.tolist(),
        "method": units.procurement_method_details.tolist(),
        "processes": units.process_count.astype(int).tolist(),
        "hhi": rounded(units.hhi, 17),
        "top_share": rounded(units.top_supplier_share),
        "participants": rounded(units.reported_participants_median, 6),
    }


def p1(processed: Path, artifacts: Path) -> dict:
    units = p1_units(processed / "market_p1")
    results = pd.read_csv(artifacts / "p1" / "analysis" / "association_results.csv")
    null = pd.read_csv(artifacts / "p1" / "analysis" / "null_summary.csv")
    methods = units.procurement_method_details.value_counts()
    return {
        "units": p1_columns(units),
        "methods": methods.index.tolist(),
        "results": json.loads(results.to_json(orient="records")),
        "null": json.loads(null.to_json(orient="records")),
        "metadata": read_json(artifacts / "p1" / "analysis" / "metadata.json")["coverage"],
    }


def oece(processed: Path, artifacts: Path) -> dict:
    base = artifacts / "oece_validation"
    analysis = artifacts / "p1" / "analysis_oece"
    comparison = pd.read_csv(base / "comparison.csv")
    methods = comparison.loc[
        (comparison.level == "procurement_method_details") & (comparison.processes >= 400)
    ]
    partition = pd.read_csv(artifacts / "p2" / "partition_oece" / "runs.csv")
    louvain = partition.loc[(partition.scope == "giant") & (partition.method == "louvain")]
    return {
        "summary": read_json(base / "summary.json"),
        "methods": json.loads(
            methods[
                [
                    "group",
                    "processes",
                    "reported_median",
                    "bidders_median",
                    "reported_that_bid",
                    "identical_share",
                ]
            ].to_json(orient="records")
        ),
        "p1_units": p1_columns(p1_units(processed / "market_p1_oece")),
        "p1_results": json.loads(
            pd.read_csv(analysis / "association_results.csv").to_json(orient="records")
        ),
        "p1_null": json.loads(pd.read_csv(analysis / "null_summary.csv").to_json(orient="records")),
        "p1_metadata": read_json(analysis / "metadata.json")["coverage"],
        "p2_null": read_json(artifacts / "p2" / "null_oece" / "summary.json"),
        "p2_partition": json.loads(louvain.to_json(orient="records")),
    }


def profiles(processed: Path, artifacts: Path, seed: int) -> dict:
    base = artifacts / "buyer_clustering"
    meta = read_json(base / "metadata.json")
    features = pd.read_parquet(base / "features.parquet").sort_values("buyer_id")
    matrix = StandardScaler().fit_transform(features[meta["features"]].to_numpy(float))
    pca = PCA(n_components=2, random_state=seed).fit(matrix)
    points = pca.transform(matrix)
    assignments = pd.read_parquet(base / "assignments.parquet")
    labels = {}
    for (method, config), group in assignments.groupby(["method", "config"]):
        ordered = group.set_index("buyer_id").label.reindex(features.buyer_id)
        labels.setdefault(method, {})[config] = ordered.astype(int).tolist()
    rng = np.random.default_rng(seed)
    sample = np.sort(rng.choice(len(features), 150, replace=False))
    tree = dendrogram(linkage(matrix[sample], method="ward"), no_plot=True)
    selected = str(meta["kmeans_selected"]["k"])
    leaf_labels = [labels["kmeans"][selected][sample[i]] for i in tree["leaves"]]
    metrics = pd.read_parquet(base / "metrics.parquet")
    chosen = assignments.loc[assignments.selected, ["buyer_id", "label"]]
    units = pd.read_parquet(processed / "market_p1" / "buyer_segment_method")
    units = units.loc[units.process_count >= 10].merge(chosen, on="buyer_id")
    by_profile = (
        units.groupby("label")
        .agg(
            units=("hhi", "size"),
            buyers=("buyer_id", "nunique"),
            hhi=("hhi", "median"),
            top_share=("top_supplier_share", "median"),
            participants=("reported_participants_median", "median"),
        )
        .reset_index()
    )
    return {
        "features": meta["features"],
        "values": {f: rounded(features[f], 3) for f in meta["features"]},
        "raw": {
            "process_count": features.process_count.astype(int).tolist(),
            "pen_amount_total": rounded(features.pen_amount_total, 0),
            "distinct_suppliers": features.distinct_suppliers.astype(int).tolist(),
        },
        "pca": {"x": rounded(points[:, 0], 3), "y": rounded(points[:, 1], 3)},
        "pca_variance": rounded(pca.explained_variance_ratio_),
        "labels": labels,
        "metrics": json.loads(metrics.to_json(orient="records")),
        "selected_k": int(selected),
        "stability": meta["stability"],
        "p1_by_profile": json.loads(by_profile.to_json(orient="records")),
        "dendrogram": {
            "icoord": [rounded(r, 2) for r in tree["icoord"]],
            "dcoord": [rounded(r, 3) for r in tree["dcoord"]],
            "leaf_labels": leaf_labels,
        },
    }


def links(processed: Path, artifacts: Path, department: str) -> dict:
    base = artifacts / "p2" / "links"
    hubs = pd.read_parquet(base / "buyer_hubs.parquet").sort_values("hub_rank").head(15)
    buyers = pd.read_parquet(
        processed / "participation" / "dim_buyer", columns=["buyer_id", "buyer_name", "department"]
    )
    hubs = hubs.merge(buyers, on="buyer_id", how="left")
    authorities = pd.read_parquet(base / "supplier_authorities.parquet")
    top = authorities.sort_values("authority_rank").head(200)
    names = pd.read_parquet(
        processed / "fact_award_supplier", columns=["supplier_id", "supplier_name"]
    ).drop_duplicates("supplier_id")
    top = top.merge(names, on="supplier_id", how="left")
    top["type"] = [
        actor_type(i, n) for i, n in zip(top.supplier_id, top.supplier_name, strict=True)
    ]
    rows = department_rows(processed / "participation", department, 5)
    graph = giant_component(department_graph(rows, 30))
    nodes = sorted(graph.nodes)
    index = {node: i for i, node in enumerate(nodes)}
    names_p = (
        pd.read_parquet(
            processed / "participation" / "fact_tenderer",
            columns=["participant_id", "participant_name"],
        )
        .drop_duplicates("participant_id")
        .set_index("participant_id")
        .participant_name
    )
    edges = [(index[u], index[v], round(d["weight"], 4)) for u, v, d in graph.edges(data=True)]
    return {
        "hubs": json.loads(
            hubs[
                ["buyer_name", "department", "hub_score", "award_strength", "distinct_suppliers"]
            ].to_json(orient="records")
        ),
        "authority_types_top200": top.type.value_counts().to_dict(),
        "authority_buyers_top200": top.distinct_buyers.describe().round(2).to_dict(),
        "correlations": json.loads(
            pd.read_csv(base / "pagerank_correlations.csv").to_json(orient="records")
        ),
        "damping_sensitivity": read_json(base / "metadata.json")["pagerank"][
            "damping_rank_sensitivity"
        ],
        "graph": {
            "department": department,
            "types": [actor_type(n, names_p.get(n)) for n in nodes],
            "source": [e[0] for e in edges],
            "target": [e[1] for e in edges],
            "weight": [e[2] for e in edges],
        },
    }


def communities(artifacts: Path) -> dict:
    full = pd.read_csv(artifacts / "p2" / "communities" / "runs.csv")
    stability = pd.read_csv(artifacts / "p2" / "communities" / "stability.csv")
    part = artifacts / "p2" / "partition"
    layout = pd.read_parquet(part / "core_layout.parquet").sort_values("participant_id")
    order = layout.participant_id.tolist()
    position = {node: i for i, node in enumerate(order)}
    edges = pd.read_parquet(part / "core_edges.parquet")
    memberships = pd.read_parquet(part / "memberships.parquet")
    core = memberships.loc[memberships.scope == "core"]
    methods = {}
    for (method, config), group in core.groupby(["method", "config"]):
        methods[f"{method}:{config}"] = (
            group.set_index("participant_id").community.reindex(order).astype(int).tolist()
        )
    levels = pd.read_parquet(part / "girvan_newman_memberships.parquet")
    gn = {
        int(level): group.set_index("participant_id").community.reindex(order).astype(int).tolist()
        for level, group in levels.groupby("level")
    }
    bigclam = pd.read_parquet(artifacts / "p2" / "bigclam" / "memberships.parquet")
    bigclam = bigclam.loc[bigclam.participant_id.isin(position)]
    overlaps = [[] for _ in order]
    for node, community in zip(bigclam.participant_id, bigclam.community, strict=True):
        overlaps[position[node]].append(int(community))
    return {
        "full_runs": json.loads(full.to_json(orient="records")),
        "full_stability": json.loads(stability.to_json(orient="records")),
        "null": read_json(artifacts / "p2" / "null" / "summary.json"),
        "partition_meta": read_json(part / "metadata.json"),
        "partition_runs": json.loads(pd.read_csv(part / "runs.csv").to_json(orient="records")),
        "agreement": json.loads(pd.read_csv(part / "agreement.csv").to_json(orient="records")),
        "gn_levels": json.loads(
            pd.read_csv(part / "girvan_newman_levels.csv").to_json(orient="records")
        ),
        "core": {
            "x": rounded(layout.x, 3),
            "y": rounded(layout.y, 3),
            "segment": layout.dominant_segment.fillna("").tolist(),
            "source": [position[u] for u in edges.left],
            "target": [position[v] for v in edges.right],
            "weight": rounded(edges.weight, 3),
            "methods": methods,
            "gn": gn,
            "bigclam": overlaps,
        },
        "bigclam": read_json(artifacts / "p2" / "bigclam" / "summary.json"),
        "bigclam_selection": json.loads(
            pd.read_csv(artifacts / "p2" / "bigclam" / "model_selection.csv").to_json(
                orient="records"
            )
        ),
        "bigclam_communities": json.loads(
            pd.read_csv(artifacts / "p2" / "bigclam" / "communities.csv").to_json(orient="records")
        ),
        "bigclam_sensitivity": json.loads(
            pd.read_csv(artifacts / "p2" / "bigclam" / "sensitivity.csv").to_json(orient="records")
        ),
        "bigclam_trace": bigclam_trace(
            artifacts / "p2" / "bigclam" / "optimization_diagnostics.csv"
        ),
    }


def bigclam_trace(path: Path, step: int = 5) -> dict:
    """Curva de log-verosimilitud submuestreada y cambio relativo de la última iteración."""
    history = pd.read_csv(path).sort_values("iteration")
    shown = history.loc[(history.iteration % step == 0) | (history.index == history.index[-1])]
    last, previous = history.loglik.iloc[-1], history.loglik.iloc[-2]
    return {
        "iteration": shown.iteration.astype(int).tolist(),
        "loglik": rounded(shown.loglik, 2),
        "last_relative_change": float(abs(last - previous) / abs(previous)),
        "relative_tolerance": 1e-5,
    }


def embedding(artifacts: Path) -> dict:
    base = artifacts / "p2" / "embedding"
    frame = pd.read_parquet(base / "buyer_embedding.parquet")
    meta = read_json(base / "metadata.json")
    kmeans = {
        column.removeprefix("svd_kmeans_"): frame[column].astype(int).tolist()
        for column in frame.columns
        if column.startswith("svd_kmeans_")
    }
    return {
        "x": rounded(frame.tsne_x, 2),
        "y": rounded(frame.tsne_y, 2),
        "department": frame.department.fillna("").tolist(),
        "profile": frame.profile_cluster.fillna(-1).astype(int).tolist(),
        "community": frame.dominant_community.fillna(-1).astype(int).tolist(),
        "name": frame.buyer_name.fillna("").tolist(),
        "kmeans": kmeans,
        "selection": json.loads(
            pd.read_csv(base / "kmeans_selection.csv").to_json(orient="records")
        ),
        "metadata": meta,
        "svd": read_json(artifacts / "p2" / "svd_participation" / "metadata.json"),
        "energy_sensitivity": json.loads(
            pd.read_csv(base / "energy_sensitivity.csv").to_json(orient="records")
        ),
        "retention": json.loads(
            pd.read_csv(base / "retention_by_profile.csv").to_json(orient="records")
        ),
        "convergence": read_json(artifacts / "p2" / "convergence" / "metadata.json"),
    }


def recommendation(artifacts: Path) -> dict:
    result = {}
    for name in ("recommendation_test", "recommendation_hybrid", "recommendation_content"):
        for file in ("_metadata.json", "metadata.json"):
            path = artifacts / name / file
            if path.is_file():
                result[name] = read_json(path)
                break
    base = artifacts / "recommendation_substitutes"
    substitutes = pd.read_parquet(base / "substitutes.parquet")
    by_segment = (
        substitutes.loc[substitutes["rank"] == 1]
        .groupby("segment")
        .similarity.agg(["size", "median"])
        .reset_index()
        .sort_values("size", ascending=False)
        .head(15)
    )
    unusual = pd.read_csv(base / "unusual_by_segment.csv", dtype={"supplier_segment": str}).head(15)
    return {
        "models": result,
        "substitutes_meta": read_json(base / "metadata.json"),
        "substitutes_validation": json.loads(
            pd.read_csv(base / "validation.csv").to_json(orient="records")
        ),
        "substitutes_by_segment": json.loads(by_segment.to_json(orient="records")),
        "unusual_by_segment": json.loads(unusual.to_json(orient="records")),
    }


def findings(artifacts: Path) -> dict:
    closure = artifacts / "p2" / "closure"
    outliers = artifacts / "buyer_outliers"
    hits = artifacts / "p2" / "hits_sensitivity"
    units = pd.read_parquet(closure / "unit_closure.parquet")
    units = units.loc[units.process_count >= 10].dropna(subset=["excess_hhi"])
    candidates = pd.read_csv(outliers / "candidates.csv")
    return {
        "closure_results": json.loads(
            pd.read_csv(closure / "association_results.csv").to_json(orient="records")
        ),
        "closure_null": json.loads(
            pd.read_csv(closure / "null_summary.csv").to_json(orient="records")
        ),
        "closure_excess": json.loads(
            pd.read_csv(closure / "excess_hhi.csv").to_json(orient="records")
        ),
        "closure_meta": read_json(closure / "metadata.json"),
        "closure_units": {
            "closure": rounded(units.closure, 3),
            "hhi": rounded(units.observed_hhi, 3),
            "excess": rounded(units.excess_hhi, 3),
        },
        "outliers_meta": read_json(outliers / "metadata.json"),
        "outliers_by_profile": json.loads(
            pd.read_csv(outliers / "by_profile.csv").to_json(orient="records")
        ),
        "outliers": json.loads(
            candidates[
                [
                    "buyer_name",
                    "department",
                    "profile",
                    "reason",
                    "process_count",
                    "profile_distance",
                ]
            ]
            .head(15)
            .to_json(orient="records")
        ),
        "hits_summary": json.loads(pd.read_csv(hits / "summary.csv").to_json(orient="records")),
        "hits_top": json.loads(pd.read_csv(hits / "top_hubs.csv").to_json(orient="records")),
        "null_r1": read_json(artifacts / "p2" / "null_r1" / "summary.json"),
        "hits_agreement": json.loads(pd.read_csv(hits / "agreement.csv").to_json(orient="records")),
        "svd_award": read_json(artifacts / "p2" / "svd" / "metadata.json"),
        "svd_participation": read_json(artifacts / "p2" / "svd_participation" / "metadata.json"),
    }


def run() -> None:
    args = parse_args()
    processed, artifacts = args.processed_dir.resolve(), args.artifacts_dir.resolve()
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()) and not args.overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite para regenerar.")
    output.mkdir(parents=True, exist_ok=True)
    write(output / "segments.json", SEGMENTS)
    write(output / "summary.json", summary(processed, artifacts))
    write(output / "p1.json", p1(processed, artifacts))
    write(output / "profiles.json", profiles(processed, artifacts, args.seed))
    write(output / "links.json", links(processed, artifacts, args.department))
    write(output / "communities.json", communities(artifacts))
    write(output / "embedding.json", embedding(artifacts))
    write(output / "recommendation.json", recommendation(artifacts))
    write(output / "findings.json", findings(artifacts))
    write(output / "oece.json", oece(processed, artifacts))
    sizes = {p.name: p.stat().st_size for p in sorted(output.glob("*.json"))}
    print(json.dumps(sizes, indent=2))
    print(f"Datos web publicados: {output}")


if __name__ == "__main__":
    run()
