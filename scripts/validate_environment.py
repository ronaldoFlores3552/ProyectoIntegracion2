"""Comprueba requisitos locales o dentro de Docker sin modificar datos."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

from setup_windows_hadoop import helper_home, verify_helpers

REQUIRED_PACKAGES = (
    "pyspark",
    "setuptools",
    "pandas",
    "numpy",
    "pyarrow",
    "scikit-learn",
    "networkx",
)


def main() -> int:
    print(f"Python: {sys.version.split()[0]} ({platform.platform()})")
    if sys.version_info[:2] != (3, 12):
        print(
            "ERROR: el proyecto exige Python 3.12.x; use Docker o cree el entorno indicado.",
            file=sys.stderr,
        )
        return 1

    java = shutil.which("java")
    if not java:
        print("ERROR: no se encontró Java 17+. Instale Java o use Docker.", file=sys.stderr)
        return 1
    result = subprocess.run([java, "-version"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print("ERROR: Java no se pudo ejecutar.", file=sys.stderr)
        return 1
    print(f"Java: {(result.stderr or result.stdout).splitlines()[0]}")

    missing = []
    for package in REQUIRED_PACKAGES:
        try:
            print(f"{package}: {version(package)}")
        except PackageNotFoundError:
            missing.append(package)
    if missing:
        print(f"ERROR: faltan paquetes: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        from pyspark.ml.recommendation import ALS  # noqa: F401
    except ImportError as exc:
        print(f"ERROR: PySpark ML no se puede importar: {exc}", file=sys.stderr)
        return 1
    print("PySpark ML ALS: importación correcta")

    if os.name == "nt":
        problems = verify_helpers()
        if problems:
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            return 1
        print(f"Hadoop local para Windows (verificado): {helper_home()}")

    print("Entorno válido para iniciar el pipeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
