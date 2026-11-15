"""Punto de entrada portable para revisar o reproducir el proyecto.

El comando ``review`` no modifica datos y está pensado para una revisión rápida.
El comando ``pipeline`` ejecuta solo las etapas solicitadas; ``--all`` hace la
reproducción completa y puede tardar bastante porque reconstruye las tablas a
partir de los datos OCDS.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stages(master: str) -> dict[str, list[list[str]]]:
    """Devuelve los comandos de cada etapa, en su orden de dependencia."""
    return {
        "base": [
            ["scripts/validate_environment.py"],
            [
                "-m",
                "src.processing.build_fact_award_item",
                "--years",
                "2023",
                "2024",
                "--master",
                master,
                "--overwrite",
            ],
            ["-m", "src.quality.profile_fact_award_item", "--overwrite"],
            ["-m", "src.processing.build_fact_award", "--master", master, "--overwrite"],
            ["-m", "src.processing.build_fact_award_supplier", "--master", master, "--overwrite"],
            ["-m", "src.features.build_interactions", "--master", master, "--overwrite"],
            [
                "-m",
                "src.processing.build_identity_evidence",
                "--years",
                "2023",
                "2024",
                "--master",
                master,
                "--overwrite",
            ],
        ],
        "parte1": [["-m", "src.features.build_part1", "--master", master, "--overwrite"]],
        "clustering": [["-m", "src.models.build_clustering", "--overwrite"]],
        "participacion": [
            [
                "-m",
                "src.processing.build_participation",
                "--years",
                "2023",
                "2024",
                "--master",
                master,
                "--overwrite",
            ]
        ],
        "recomendacion": [
            ["-m", "src.features.build_recommendation", "--master", master, "--overwrite"],
            ["-m", "src.models.recommendation_baseline", "--overwrite"],
            ["-m", "src.models.recommendation_neighbors", "--overwrite"],
            ["-m", "src.models.recommendation_als", "--master", master, "--overwrite"],
            ["-m", "src.models.recommendation_test", "--master", master, "--overwrite"],
            ["-m", "src.models.recommendation_content", "--overwrite"],
            ["-m", "src.models.recommendation_hybrid", "--overwrite"],
            ["-m", "src.models.recommendation_substitutes", "--overwrite"],
        ],
        "p1": [
            ["-m", "src.features.build_market_p1", "--master", master, "--overwrite"],
            ["-m", "src.models.analyze_market_p1", "--overwrite"],
        ],
        "p2": [
            ["-m", "src.features.build_market_p2", "--master", master, "--overwrite"],
            [
                "-m",
                "src.features.build_market_p2",
                "--max-recurrent-participants",
                "30",
                "--output-dir",
                "data/processed/market_p2_k30",
                "--master",
                master,
                "--overwrite",
            ],
            [
                "-m",
                "src.quality.profile_market_p2",
                "--market-dir",
                "data/processed/market_p2_k30",
                "--master",
                master,
                "--overwrite",
            ],
            ["-m", "src.models.analyze_links_p2", "--overwrite"],
            ["-m", "src.models.hits_sensitivity_p2", "--overwrite"],
            ["-m", "src.models.detect_communities_p2", "--overwrite"],
            ["-m", "src.models.louvain_order_p2", "--overwrite"],
            [
                "-m",
                "src.models.null_communities_p2",
                "--replicates",
                "50",
                "--trades-per-participant",
                "50",
                "--overwrite",
            ],
            [
                "-m",
                "src.models.null_communities_p2",
                "--replicates",
                "50",
                "--trades-per-participant",
                "50",
                "--resolution",
                "1.0",
                "--output-dir",
                "artifacts/p2/null_r1",
                "--overwrite",
            ],
        ],
        "perfiles": [
            ["-m", "src.features.build_buyer_profiles", "--master", master, "--overwrite"],
            ["-m", "src.models.cluster_buyer_profiles", "--overwrite"],
            ["-m", "src.models.profile_outliers", "--overwrite"],
        ],
        "comunidades": [
            ["-m", "src.models.partition_subgraph_p2", "--overwrite"],
            ["-m", "src.models.bigclam_p2", "--overwrite"],
            ["-m", "src.models.link_closure_p1", "--overwrite"],
        ],
        "representacion": [
            ["-m", "src.models.build_svd_p2", "--overwrite"],
            [
                "-m",
                "src.models.build_svd_p2",
                "--matrix",
                "participation",
                "--components",
                "64",
                "--output-dir",
                "artifacts/p2/svd_participation",
                "--overwrite",
            ],
            ["-m", "src.models.build_convergence_p2", "--overwrite"],
            ["-m", "src.models.embed_visualization_p2", "--overwrite"],
        ],
        "oece": [
            ["-m", "src.quality.validate_tenderers_oece", "--overwrite"],
            [
                "-m",
                "src.features.build_market_p1",
                "--participation-dir",
                "data/processed/participation_oece",
                "--output-dir",
                "data/processed/market_p1_oece",
                "--master",
                master,
                "--overwrite",
            ],
            [
                "-m",
                "src.models.analyze_market_p1",
                "--market-dir",
                "data/processed/market_p1_oece",
                "--participation-dir",
                "data/processed/participation_oece",
                "--output-dir",
                "artifacts/p1/analysis_oece",
                "--overwrite",
            ],
            [
                "-m",
                "src.models.null_communities_p2",
                "--participation-dir",
                "data/processed/participation_oece",
                "--replicates",
                "50",
                "--trades-per-participant",
                "50",
                "--output-dir",
                "artifacts/p2/null_oece",
                "--overwrite",
            ],
            [
                "-m",
                "src.models.partition_subgraph_p2",
                "--participation-dir",
                "data/processed/participation_oece",
                "--output-dir",
                "artifacts/p2/partition_oece",
                "--overwrite",
            ],
        ],
        "web": [["-m", "src.web.export_web_data", "--overwrite"]],
    }


def run(commands: Iterable[list[str]], python: str, *, dry_run: bool) -> None:
    environment = os.environ.copy()
    environment.setdefault("PYSPARK_SUBMIT_ARGS", "--driver-memory 6g pyspark-shell")
    for arguments in commands:
        command = [python, *arguments]
        print("==>", " ".join(command))
        if not dry_run:
            subprocess.run(command, cwd=ROOT, env=environment, check=True)


def review(python: str, *, delivery: bool) -> int:
    commands = [
        ["scripts/validate_environment.py"],
        ["-m", "pytest", "-q"],
        ["-m", "ruff", "check", "."],
    ]
    if delivery:
        commands.append(["scripts/verify_delivery_consistency.py", "--final"])
    run(commands, python, dry_run=False)
    print("Revisión terminada.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    review_parser = subparsers.add_parser(
        "review", help="comprueba entorno, pruebas y estilo sin regenerar datos"
    )
    review_parser.add_argument(
        "--delivery", action="store_true", help="incluye la verificación de artefactos finales"
    )
    review_parser.add_argument(
        "--python", default=sys.executable, help="intérprete Python a utilizar"
    )

    pipeline_parser = subparsers.add_parser("pipeline", help="ejecuta etapas de reproducción")
    pipeline_parser.add_argument(
        "stages", nargs="*", help="etapas a ejecutar; use --list para verlas"
    )
    pipeline_parser.add_argument("--all", action="store_true", help="ejecuta toda la reproducción")
    pipeline_parser.add_argument(
        "--list", action="store_true", help="muestra las etapas disponibles"
    )
    pipeline_parser.add_argument(
        "--dry-run", action="store_true", help="muestra comandos sin modificar archivos"
    )
    pipeline_parser.add_argument(
        "--master", default=os.environ.get("SPARK_MASTER", "local[8]"), help="Spark master"
    )
    pipeline_parser.add_argument(
        "--python", default=sys.executable, help="intérprete Python a utilizar"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "review":
        return review(args.python, delivery=args.delivery)

    available = stages(args.master)
    if args.list:
        print("\n".join(available))
        return 0
    if args.all and args.stages:
        raise SystemExit("Use --all o una lista de etapas, no ambos.")
    if not args.all and not args.stages:
        raise SystemExit("Indique una etapa o use --all. Use --list para ver las alternativas.")
    selected = list(available) if args.all else args.stages
    unknown = [stage for stage in selected if stage not in available]
    if unknown:
        raise SystemExit(f"Etapa(s) desconocida(s): {', '.join(unknown)}. Use --list.")
    for stage in selected:
        print(f"\n#### etapa: {stage}")
        run(available[stage], args.python, dry_run=args.dry_run)
    print(f"\nPipeline terminado: {' '.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
