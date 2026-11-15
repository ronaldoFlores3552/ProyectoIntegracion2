"""Comprueba que artefactos, documentos y notebooks coincidan con las cifras de la entrega.

Las cifras esperadas viven en scripts/cifras_entrega.json, fijadas tras revisar la corrida.
No reentrena modelos ni modifica archivos. La web se revisa solo con --final, al cierre.
"""

import argparse
import csv
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "cifras_entrega.json"
STALE = [r"(?<![−-])0,137", r"\[−0,136; 0,078\]", r"\[0,084; 0,090\]", "null_puno", "overlap_puno"]


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def read_csv(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def p1_row(path: str, minimum: str, adjustment: str) -> dict[str, str]:
    return next(
        row
        for row in read_csv(path)
        if row.get("scenario", "all_awards") == "all_awards"
        and row.get("participation_measure", "reported_participants_median")
        == "reported_participants_median"
        and row["minimum_processes"] == minimum
        and row["adjustment"] == adjustment
    )


def louvain_range(column: str, resolution: str, path: str) -> tuple[float, float]:
    values = [float(row[column]) for row in read_csv(path) if row["resolution"] == resolution]
    return min(values), max(values)


def observed() -> dict[str, float]:
    p1 = p1_row("artifacts/p1/analysis/association_results.csv", "10", "stratum_centered")
    q_low, q_high = louvain_range("modularity", "1.5", "artifacts/p2/communities/runs.csv")
    ari_low, ari_high = louvain_range("ari", "1.5", "artifacts/p2/communities/stability.csv")
    links = read_json("artifacts/p2/links/metadata.json")
    null = read_json("artifacts/p2/null/summary.json")
    null_r1 = read_json("artifacts/p2/null_r1/summary.json")
    bigclam = read_json("artifacts/p2/bigclam/summary.json")
    closure = p1_row("artifacts/p2/closure/association_results.csv", "10", "raw")
    excess = p1_row("artifacts/p2/closure/excess_hhi.csv", "10", "raw")
    hits = {row["weight"]: row for row in read_csv("artifacts/p2/hits_sensitivity/summary.csv")}
    profiles = read_json("artifacts/buyer_clustering/metadata.json")
    svd = read_json("artifacts/p2/svd/metadata.json")
    convergence = read_json("artifacts/p2/convergence/metadata.json")
    als = read_json("artifacts/recommendation_als/_metadata.json")
    als_selected = next(
        row for row in als["results"] if row["config"]["rank"] == als["selected"]["rank"]
    )
    hybrid = read_json("artifacts/recommendation_hybrid/_metadata.json")
    oece = read_json("artifacts/oece_validation/summary.json")
    oece_p1 = p1_row("artifacts/p1/analysis_oece/association_results.csv", "10", "stratum_centered")
    oece_null = read_json("artifacts/p2/null_oece/summary.json")
    return {
        "p1_rho_centrado_10": float(p1["correlation"]),
        "p1_ic_inferior": float(p1["ci_low"]),
        "p1_ic_superior": float(p1["ci_high"]),
        "red_nodos": links["pagerank"]["nodes"],
        "red_aristas": links["pagerank"]["undirected_edges"],
        "louvain_q_min": q_low,
        "louvain_q_max": q_high,
        "louvain_ari_min": ari_low,
        "louvain_ari_max": ari_high,
        "puno_q_observado": null["observed_modularity"],
        "puno_nulo_p2_5": null["null_percentile_2_5"],
        "puno_nulo_p97_5": null["null_percentile_97_5"],
        "puno_nulo_replicas": null["replicates"],
        "puno_r1_q_observado": null_r1["observed_modularity"],
        "puno_r1_nulo_p97_5": null_r1["null_percentile_97_5"],
        "bigclam_k": bigclam["selected_communities"],
        "bigclam_solapados": bigclam["share_nodes_overlapping"],
        "bigclam_sin_comunidad": bigclam["share_nodes_without_community"],
        "hits_masa_conteo": float(hits["conteo"]["top_authority_mass"]),
        "hits_masa_log1p": float(hits["log1p"]["top_authority_mass"]),
        "cierre_rho_bruto_10": float(closure["correlation"]),
        "exceso_hhi_positivo": float(excess["share_positive_excess"]),
        "perfiles_k": profiles["kmeans_selected"]["k"],
        "perfiles_silueta": profiles["kmeans_selected"]["silhouette"],
        "svd_varianza": svd["explained_variance_ratio_sum"],
        "nmi_perfil_comunidad": convergence["nmi_profile_cluster_dominant_community"],
        "als_validacion_ndcg10": als_selected["metrics_macro"]["10"]["ndcg"],
        "hibrido_validacion_ndcg10": hybrid["metrics_macro"]["10"]["ndcg"],
        "oece_reportados_ofertan": oece["reported_that_bid"],
        "oece_ofertantes_en_lista": oece["bidders_in_reported"],
        "oece_p1_centrado_10": float(oece_p1["correlation"]),
        "oece_puno_q": oece_null["observed_modularity"],
    }


def differs(actual: float, expected: float, tolerance: float) -> bool:
    if not (math.isfinite(actual) and math.isfinite(expected)):
        return True
    return abs(actual - expected) > tolerance


def markdown_of(relative: str) -> str:
    notebook = read_json(relative)
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell["cell_type"] == "markdown"
    )


def check_text(label: str, text: str, snippets: list[str], failures: list[str]) -> None:
    for snippet in snippets:
        if snippet not in text:
            failures.append(f"{label}: falta {snippet!r}")
    for pattern in STALE:
        if re.search(pattern, text):
            failures.append(f"{label}: conserva la cifra o ruta antigua {pattern!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--final", action="store_true", help="exige también la web")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []
    values = observed()
    for key, expected in manifest["cifras"].items():
        actual = float(values[key])
        if differs(actual, float(expected["valor"]), expected.get("tolerancia", 5e-4)):
            failures.append(f"{key}: esperado {expected['valor']}, obtenido {actual}")

    texts = {key: item["texto"] for key, item in manifest["cifras"].items() if "texto" in item}
    for relative, keys in manifest["documentos"].items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"{relative}: no existe")
            continue
        content = (
            markdown_of(relative)
            if relative.endswith(".ipynb")
            else path.read_text(encoding="utf-8")
        )
        check_text(relative, content, [texts.get(key, key) for key in keys], failures)

    web = ROOT / "web" / "index.html"
    if args.final:
        check_text(
            "web/index.html", web.read_text(encoding="utf-8"), list(texts.values()), failures
        )
    else:
        print("Aviso: la web no se revisa hasta el cierre; ejecute con --final.")

    if failures:
        print("INCONSISTENCIAS DE ENTREGA:")
        print("\n".join(f"- {failure}" for failure in failures))
        raise SystemExit(1)
    print(f"Consistencia de entrega verificada: {len(manifest['cifras'])} cifras.")


if __name__ == "__main__":
    main()
