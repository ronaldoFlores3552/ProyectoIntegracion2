"""Comprueba que la síntesis de entrega coincida con los artefactos publicados.

No reentrena modelos ni modifica archivos. Se ejecuta después de la publicación
de artefactos para evitar que README y la web presenten cifras de otra corrida.
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def read_csv(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def close(actual: float, expected: float, label: str, failures: list[str]) -> None:
    if abs(actual - expected) > 5e-4:
        failures.append(f"{label}: esperado {expected}, obtenido {actual}")


def require_text(relative: str, snippets: list[str], failures: list[str]) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    for snippet in snippets:
        if snippet not in text:
            failures.append(f"{relative}: falta la frase o cifra {snippet!r}")


def main() -> None:
    failures: list[str] = []

    p1 = read_csv("artifacts/p1/analysis/association_results.csv")
    p1_row = next(
        row
        for row in p1
        if row["scenario"] == "all_awards"
        and row["participation_measure"] == "reported_participants_median"
        and row["minimum_processes"] == "10"
        and row["adjustment"] == "stratum_centered"
    )
    close(float(p1_row["correlation"]), -0.0503878953, "P1 rho", failures)
    close(float(p1_row["ci_low"]), -0.1362607124, "P1 IC inferior", failures)
    close(float(p1_row["ci_high"]), 0.0783465335, "P1 IC superior", failures)

    p2 = read_json("artifacts/p2/links/metadata.json")
    if p2["pagerank"]["nodes"] != 25379:
        failures.append("P2: la red k<=30 no tiene 25 379 nodos")
    if p2["pagerank"]["undirected_edges"] != 1698528:
        failures.append("P2: la red k<=30 no tiene 1 698 528 aristas")

    communities = read_csv("artifacts/p2/communities/runs.csv")
    modularities = [
        float(row["modularity"])
        for row in communities
        if row["resolution"] == "1.5"
    ]
    close(min(modularities), 0.6225594197, "P2 modularidad mínima", failures)
    close(max(modularities), 0.6293374381, "P2 modularidad máxima", failures)
    stability = read_csv("artifacts/p2/communities/stability.csv")
    aris = [float(row["ari"]) for row in stability if row["resolution"] == "1.5"]
    close(min(aris), 0.8398986239, "P2 ARI mínimo", failures)
    close(max(aris), 0.8688376999, "P2 ARI máximo", failures)

    puno = read_json("artifacts/p2/null_puno/summary.json")
    close(puno["observed_modularity"], 0.6115438435, "Nulo Puno observado", failures)
    close(puno["null_ci_low"], 0.0838140064, "Nulo Puno IC inferior", failures)
    close(puno["null_ci_high"], 0.0904952211, "Nulo Puno IC superior", failures)

    overlap_dir = ROOT / "artifacts/p2/overlap_puno"
    if not (overlap_dir / "_SUCCESS").is_file():
        failures.append("BigCLAM Puno: falta _SUCCESS")
    else:
        overlap = read_json("artifacts/p2/overlap_puno/metadata.json")
        if overlap["parameters"]["department"] != "PUNO":
            failures.append("BigCLAM Puno: el departamento no es PUNO")
        if overlap["coverage"]["nodes_in_projection"] != 1908:
            failures.append("BigCLAM Puno: la proyección no tiene 1 908 nodos")
        if overlap["coverage"]["edges_in_projection"] != 84962:
            failures.append("BigCLAM Puno: la proyección no tiene 84 962 aristas")
        if not 0 < overlap["coverage"]["share_nodes_in_multiple_communities"] < 1:
            failures.append("BigCLAM Puno: falta solapamiento no trivial")
        if overlap["diagnostics"]["objective_final"] < overlap["diagnostics"]["objective_initial"]:
            failures.append("BigCLAM Puno: el objetivo disminuyó")

    profiles = read_json("artifacts/buyer_clustering/metadata.json")
    if profiles["kmeans_selected"]["k"] != 5:
        failures.append("Perfiles: KMeans final no tiene k=5")
    close(profiles["kmeans_selected"]["silhouette"], 0.3432246674, "Silueta perfiles", failures)

    svd = read_json("artifacts/p2/svd/metadata.json")
    close(svd["explained_variance_ratio_sum"], 0.3545852132, "Varianza SVD", failures)
    convergence = read_json("artifacts/p2/convergence/metadata.json")
    close(
        convergence["nmi_profile_cluster_dominant_community"],
        0.1366766657,
        "NMI de convergencia",
        failures,
    )

    als = read_json("artifacts/recommendation_als/_metadata.json")
    als_selected = next(
        row for row in als["results"] if row["config"]["rank"] == als["selected"]["rank"]
    )
    close(als_selected["metrics_macro"]["10"]["ndcg"], 0.0557783937, "ALS validación", failures)
    hybrid = read_json("artifacts/recommendation_hybrid/_metadata.json")
    close(hybrid["metrics_macro"]["10"]["ndcg"], 0.0400063138, "Híbrido validación", failures)

    readme_snippets = [
        "−0,050",
        "[−0,136; 0,078]",
        "52 106",
        "25 379",
        "1 698 528",
        "0,623--0,629",
        "0,840--0,869",
        "0,612",
        "[0,084; 0,090]",
        "k=5",
        "35,46 %",
        "0,137",
        "NDCG@10 0,040",
        "(0,056)",
        "participantes reportados",
    ]
    web_snippets = [
        snippet.replace("--", "–") for snippet in readme_snippets
    ]
    require_text("README.md", readme_snippets, failures)
    require_text("web/index.html", web_snippets, failures)
    require_text(
        "docs/ReporteReproduccionReplanteamiento20261114.md",
        ["silueta 0,343", "35,46 %", "NMI fue 0,137", "NDCG@10 0,040"],
        failures,
    )
    require_text(
        "docs/GUIA_EXPOSICION_VSCODE.md",
        [
            "experimento histórico",
            "k=5",
            "silueta 0,343",
            "35,46 %",
            "NMI 0,137",
            "NDCG@10 0,040",
            "0,056 de ALS",
            "participantes reportados",
        ],
        failures,
    )
    require_text(
        "docs/README_Guia_Proyecto.md",
        [
            "El `k=4` de esta sección no compite",
            "selecciona `k=5` (silueta 0,343)",
            "NDCG@10 0,040 frente a",
            "0,056 de ALS",
        ],
        failures,
    )
    require_text(
        "docs/README_ParteIII.md",
        ["híbrido RRF", "NDCG@10 0,040", "por lo que no", "se declara una mejora"],
        failures,
    )

    notebook_04 = read_json("notebooks/04_clustering_y_anomalias.ipynb")
    notebook_06 = read_json("notebooks/06_recomendacion.ipynb")
    notebook_07 = read_json("notebooks/07_auditoria_contenido.ipynb")
    notebook_08 = read_json("notebooks/08_p1_p2_redes_y_comunidades.ipynb")
    notebook_09 = read_json("notebooks/09_sintesis_entrega_y_reporte.ipynb")
    for notebook, expected in (
        (notebook_04, "experimento histórico"),
        (notebook_06, "híbrido RRF"),
        (notebook_07, "híbrido RRF"),
        (notebook_08, "BigCLAM"),
        (notebook_09, "capa de lectura"),
    ):
        markdown = "\n".join(
            "".join(cell.get("source", []))
            for cell in notebook["cells"]
            if cell["cell_type"] == "markdown"
        )
        if expected not in markdown:
            failures.append(f"Notebook: falta el contexto vigente {expected!r}")

    if failures:
        print("INCONSISTENCIAS DE ENTREGA:")
        print("\n".join(f"- {failure}" for failure in failures))
        raise SystemExit(1)

    print("Consistencia de entrega verificada contra los artefactos publicados.")


if __name__ == "__main__":
    main()
