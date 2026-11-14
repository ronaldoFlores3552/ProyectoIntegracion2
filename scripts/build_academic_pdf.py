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
OUTPUT = ROOT / "docs" / "Informe_Proyecto_Integrador_2.pdf"


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


def fmt(value: float, places: int = 3) -> str:
    return f"{value:.{places}f}".replace(".", ",")


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def add_table(story: list, rows: list[list[str]], widths: list[float], styles: dict) -> None:
    table = Table(
        [
            [
                paragraph(cell, styles["header"] if index == 0 else styles["body"])
                for cell in row
            ]
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
    p1 = p1_result()
    p1_metadata = read_json("artifacts/p1/analysis/metadata.json")
    links = read_json("artifacts/p2/links/metadata.json")
    with (ROOT / "artifacts/p2/communities/runs.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        modularities = [
            float(row["modularity"])
            for row in csv.DictReader(stream)
            if row["resolution"] == "1.5"
        ]
    puno = read_json("artifacts/p2/null_puno/summary.json")
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
    styles.add(
        ParagraphStyle(name="body", parent=styles["BodyText"], fontSize=9, leading=12)
    )
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
    styles.add(
        ParagraphStyle(name="note", parent=styles["BodyText"], fontSize=8.5, leading=11)
    )

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
                f"[{fmt(float(p1['ci_low']))}; {fmt(float(p1['ci_high']))}] en "
                f"{fmt_int(p1_metadata['coverage']['selected_processes'])} procesos.",
                "No respalda asociación persistente entre concentración y participación reportada.",
            ],
            [
                "P2",
                f"Red k<=30: {fmt_int(links['pagerank']['nodes'])} participantes y "
                f"{fmt_int(links['pagerank']['undirected_edges'])} aristas. Louvain 1,5: "
                f"modularidad {fmt(min(modularities))}-{fmt(max(modularities))}.",
                "Describe co-participación reportada; no prueba colusión.",
            ],
            [
                "Nulo Puno",
                f"Modularidad observada {fmt(puno['observed_modularity'])}; nulo "
                f"[{fmt(puno['null_ci_low'])}; {fmt(puno['null_ci_high'])}], 20 réplicas.",
                "Evidencia delimitada a Puno, sin extrapolación nacional.",
            ],
            [
                "Perfiles y SVD",
                f"k={profiles['kmeans_selected']['k']}; "
                f"silueta {fmt(profiles['kmeans_selected']['silhouette'])}; "
                f"SVD 8 componentes: {fmt(svd['explained_variance_ratio_sum'] * 100, 2)} %.",
                "NMI perfil-comunidad "
                f"{fmt(convergence['nmi_profile_cluster_dominant_community'])}: "
                "no convergen fuertemente.",
            ],
            [
                "Recomendación",
                f"Validación 2023: ALS NDCG@10 {fmt(selected_als['metrics_macro']['10']['ndcg'])}; "
                f"híbrido RRF {fmt(hybrid['metrics_macro']['10']['ndcg'])}.",
                "El híbrido no mejora ALS; la evaluación es retrospectiva.",
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
                "Usar Python 3.12 en .venv312 y Java 17. La guía de réplica ejecuta pruebas, Ruff, "
                "verificación de artefactos y verify_delivery_consistency.py antes de "
                "abrir la web local. La exposición sigue: fuente y grano -> P1 -> "
                "P2/nulo Puno -> perfiles/SVD/convergencia -> recomendación -> web. "
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
