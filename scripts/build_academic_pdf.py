"""Genera el informe PDF de entrega desde los artefactos publicados actuales."""

import csv
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "report" / "Informe_Proyecto_Integrador_2.pdf"


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def p1_result() -> dict[str, str]:
    with (ROOT / "artifacts/p1/analysis/association_results.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        for row in csv.DictReader(stream):
            if (
                row["scenario"] == "all_awards"
                and row["participation_measure"] == "reported_participants_median"
                and row["minimum_processes"] == "10"
                and row["adjustment"] == "stratum_centered"
            ):
                return row
    raise RuntimeError("No se encontró la fila P1 ajustada para >=10 procesos.")


def csv_rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def pct(value: float, places: int = 1) -> str:
    return f"{fmt(value * 100, places)} %"


def fmt(value: float, places: int = 3) -> str:
    return f"{value:.{places}f}".replace(".", ",")


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def add_table(story: list, rows: list[list[str]], widths: list[float], styles: dict) -> None:
    table = Table(
        [
            [paragraph(cell, styles["header"] if index == 0 else styles["body"]) for cell in row]
            for index, row in enumerate(rows)
        ],
        colWidths=widths,
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E2F3")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7FAFF")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([table, Spacer(1, 12)])


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    p1 = p1_result()
    p1_metadata = read_json("artifacts/p1/analysis/metadata.json")
    links = read_json("artifacts/p2/links/metadata.json")
    with (ROOT / "artifacts/p2/communities/runs.csv").open(encoding="utf-8", newline="") as stream:
        modularities = [
            float(row["modularity"]) for row in csv.DictReader(stream) if row["resolution"] == "1.5"
        ]
    puno = read_json("artifacts/p2/null/summary.json")
    puno_r1 = read_json("artifacts/p2/null_r1/summary.json")
    bigclam = read_json("artifacts/p2/bigclam/summary.json")
    hits = {row["weight"]: row for row in csv_rows("artifacts/p2/hits_sensitivity/summary.csv")}
    closure = next(
        row
        for row in csv_rows("artifacts/p2/closure/excess_hhi.csv")
        if row["minimum_processes"] == "10" and row["adjustment"] == "raw"
    )
    svd_participation = read_json("artifacts/p2/svd_participation/metadata.json")
    embedding = read_json("artifacts/p2/embedding/metadata.json")
    substitutes = {
        row["set"]: row for row in csv_rows("artifacts/recommendation_substitutes/validation.csv")
    }
    profiles = read_json("artifacts/buyer_clustering/metadata.json")
    svd = read_json("artifacts/p2/svd/metadata.json")
    convergence = read_json("artifacts/p2/convergence/metadata.json")
    als = read_json("artifacts/recommendation_als/_metadata.json")
    hybrid = read_json("artifacts/recommendation_hybrid/_metadata.json")
    selected_als = next(
        row for row in als["results"] if row["config"]["rank"] == als["selected"]["rank"]
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ProjectTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            textColor=colors.black,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ProjectSubtitle",
            parent=styles["Normal"],
            alignment=TA_CENTER,
            fontSize=10,
            leading=14,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading2"],
            textColor=colors.black,
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(ParagraphStyle(name="body", parent=styles["BodyText"], fontSize=9, leading=12))
    styles.add(
        ParagraphStyle(
            name="header",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.white,
        )
    )
    styles.add(ParagraphStyle(name="note", parent=styles["BodyText"], fontSize=8.5, leading=11))

    story: list = [
        paragraph("Proyecto Integrador 2", styles["ProjectTitle"]),
        paragraph(
            "Consolidado académico de grafos, clustering, representaciones y recomendación "
            "sobre contrataciones públicas del Perú, 2023-2024.",
            styles["ProjectSubtitle"],
        ),
        paragraph("Conclusión", styles["Section"]),
        paragraph(
            "El proyecto publica una cadena reproducible desde releases OCDS hasta resultados "
            "analíticos. Los hallazgos describen registros y relaciones publicadas: no prueban "
            "competencia efectiva, colusión, fraude, idoneidad de proveedores ni causalidad.",
            styles["body"],
        ),
        Spacer(1, 8),
        paragraph("Resultados consolidados", styles["Section"]),
    ]
    add_table(
        story,
        [
            ["Línea", "Resultado", "Lectura correcta"],
            [
                "P1",
                f"Spearman ajustado {fmt(float(p1['correlation']))}; IC bootstrap "
                f"[{fmt(float(p1['ci_low']))}; {fmt(float(p1['ci_high']))}], bootstrap por "
                f"comprador sobre {fmt_int(int(p1['units']))} unidades; población base de "
                f"{fmt_int(p1_metadata['coverage']['selected_processes'])} procesos.",
                "No respalda asociación persistente entre concentración y participación reportada.",
            ],
            [
                "P2",
                f"Red k<=30: {fmt_int(links['pagerank']['nodes'])} participantes y "
                f"{fmt_int(links['pagerank']['undirected_edges'])} aristas. Louvain 1,5: "
                f"modularidad {fmt(min(modularities))}-{fmt(max(modularities))}.",
                "Describe co-participación reportada; no prueba colusión. Louvain depende "
                "del orden de inserción de las aristas: el rango es sensibilidad, no error.",
            ],
            [
                "HITS",
                "Masa de la primera authority: "
                f"{pct(float(hits['conteo']['top_authority_mass']))} con conteos, "
                f"{pct(float(hits['log1p']['top_authority_mass']))} con log1p.",
                "Depende del peso y lo domina un proveedor; no es un ranking de importancia.",
            ],
            [
                "Nulo Puno",
                f"Modularidad observada {fmt(puno['observed_modularity'])}; percentiles 2,5 y "
                f"97,5 del nulo [{fmt(puno['null_percentile_2_5'])}; "
                f"{fmt(puno['null_percentile_97_5'])}], {puno['replicates']} réplicas Curveball. "
                f"Con resolución 1,0: {fmt(puno_r1['observed_modularity'])} frente a "
                f"[{fmt(puno_r1['null_percentile_2_5'])}; "
                f"{fmt(puno_r1['null_percentile_97_5'])}].",
                "Evidencia delimitada a Puno, sin extrapolación nacional.",
            ],
            [
                "BigCLAM Puno",
                f"K={bigclam['selected_communities']} elegido con pares reservados; "
                f"{pct(bigclam['share_nodes_overlapping'])} en dos o más comunidades "
                f"({pct(bigclam['overlap_share_min_across_seeds'])} a "
                f"{pct(bigclam['overlap_share_max_across_seeds'])} entre semillas), "
                f"{pct(bigclam['share_nodes_without_community'])} sin comunidad.",
                "K es provisional; la proporción es estable entre semillas, pero depende del "
                "umbral de pertenencia.",
            ],
            [
                "Cierre y concentración",
                f"HHI observado medio {fmt(float(closure['mean_observed_hhi']))} frente a "
                f"{fmt(float(closure['mean_expected_hhi']))} con ganador uniforme; "
                f"{pct(float(closure['share_positive_excess']), 0)} de unidades con exceso. "
                f"Cierre-exceso: rho {fmt(float(closure['closure_excess_correlation']))}.",
                "No se detecta asociación entre cierre comunitario y exceso de concentración.",
            ],
            [
                "Perfiles y SVD",
                f"k={profiles['kmeans_selected']['k']}; "
                f"silueta {fmt(profiles['kmeans_selected']['silhouette'])}. "
                f"SVD de adjudicaciones: {fmt(svd['explained_variance_ratio_sum'] * 100, 2)} % "
                "de varianza, pero casi nula por comprador; se usa la SVD de participación "
                "(mediana de energía "
                f"{fmt(svd_participation['captured_energy_quantiles']['0.5'], 2)}, "
                f"{fmt_int(embedding['buyers'])} compradores conservados).",
                "NMI perfil-comunidad "
                f"{fmt(convergence['nmi_profile_cluster_dominant_community'])}: "
                "convergencia parcial; perfiles y comunidades miden cosas distintas.",
            ],
            [
                "Recomendación",
                f"Validación 2023: ALS NDCG@10 {fmt(selected_als['metrics_macro']['10']['ndcg'])}; "
                f"híbrido RRF {fmt(hybrid['metrics_macro']['10']['ndcg'])}.",
                "El híbrido no mejora ALS; la evaluación es retrospectiva.",
            ],
            [
                "Sustitutos",
                "El vecino TF-IDF del mismo segmento coincide en un proceso de 2024 en "
                f"{pct(float(substitutes['sustituto_top1']['share_coparticipate']))} de los casos "
                "frente a "
                f"{pct(float(substitutes['aleatorio_mismo_segmento']['share_coparticipate']))} "
                "al azar.",
                "Recupera competidores plausibles, no proveedores intercambiables.",
            ],
        ],
        [1.3 * inch, 2.75 * inch, 2.65 * inch],
        styles,
    )
    story.extend(
        [
            paragraph("Diseño y trazabilidad", styles["Section"]),
            paragraph(
                "Spark aplana los releases y publica tablas por etapas con marcador _SUCCESS, "
                "metadatos y controles de grano. P1 separa procesos, participantes "
                "y adjudicaciones; P2 usa HITS sobre comprador-proveedor y "
                "PageRank/Louvain sobre co-participación con peso Newman. Los perfiles "
                "renovados excluyen HHI y participación para evitar circularidad.",
                styles["body"],
            ),
            Spacer(1, 8),
            paragraph("Límites que se mantienen", styles["Section"]),
            paragraph(
                "1. tender.tenderers se nombra participantes reportados hasta validarlo "
                "externamente. 2. Los identificadores de proveedores y participantes no "
                "tienen una identidad canónica. 3. La disponibilidad histórica de los "
                "releases y el arranque en frío no están verificados. 4. El híbrido no "
                "demuestra sustitución por CUBSO ni sorpresa. Node2Vec, API, React y "
                "despliegue público son extensiones opcionales.",
                styles["body"],
            ),
            Spacer(1, 8),
            paragraph("Cómo reproducir y presentar", styles["Section"]),
            paragraph(
                "Usar Python 3.12 y Java 17 con requirements.txt. La guía de réplica ejecuta "
                "pruebas, Ruff, verificación de artefactos y verify_delivery_consistency.py "
                "antes de abrir la web local. La exposición sigue: fuente y grano -> P1 -> "
                "P2, nulo y BigCLAM en Puno -> cierre -> perfiles, SVD y convergencia -> "
                "recomendación -> web. "
                "El clustering inicial k=4 es histórico y no debe confundirse con el "
                "perfil final k=5.",
                styles["body"],
            ),
            Spacer(1, 16),
            paragraph(
                "Fuentes internas: artefactos publicados P1, P2, perfiles, SVD, "
                "convergencia y recomendación. "
                "Fuente primaria: Registro OCDS OECE/OSCE, Perú, CC BY 4.0.",
                styles["note"],
            ),
        ]
    )

    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="Proyecto Integrador 2",
        author="Equipo del proyecto",
    )
    document.build(story)
    print(f"PDF generado: {OUTPUT}")


if __name__ == "__main__":
    main()
