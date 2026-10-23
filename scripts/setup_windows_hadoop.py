"""Prepara y verifica el helper nativo mínimo que Hadoop requiere al escribir en Windows.

PySpark 3.5.6 incluye Hadoop 3.3.4. Los binarios usados aquí son de Hadoop 3.3.5: la interfaz
JNI de Windows (NativeIO$Windows) no cambió entre ambas versiones, por lo que son compatibles.
Ambos binarios dependen de MSVCR100.dll (Visual C++ 2010 x64), que Windows no incluye de serie.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

HADOOP_HELPER_VERSION = "3.3.5"
SOURCE_BASE_URL = "https://raw.githubusercontent.com/cdarlint/winutils/master/hadoop-3.3.5/bin"
EXPECTED_SHA256 = {
    "winutils.exe": "a0ca6e358357c41ef56ebdb02c38e4a4d55da7ca7a13001678bb2ef7d644adea",
    "hadoop.dll": "d3dd64afdc85f2a7eb5345abf2ecaa744b0a157de40859313337d47f81ee1c7b",
}
CHUNK_SIZE = 1024 * 1024
ERROR_MOD_NOT_FOUND = 126
ERROR_BAD_EXE_FORMAT = 193
STATUS_DLL_NOT_FOUND = 0xC0000135
RUNTIME_HINT = (
    "Falta MSVCR100.dll (Microsoft Visual C++ 2010 x64 Redistributable), dependencia de "
    "hadoop.dll y winutils.exe. Use Docker (recomendado) o instale el redistribuible oficial: "
    "winget install --id Microsoft.VCRedist.2010.x64 --exact"
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def helper_home() -> Path:
    return project_root() / ".tools" / f"hadoop-{HADOOP_HELPER_VERSION}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_dll_loadable(dll: Path) -> list[str]:
    """Load the DLL as the JVM does (LoadLibraryW with full path) to detect missing deps."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryW.restype = ctypes.c_void_p
    kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
    handle = kernel32.LoadLibraryW(str(dll))
    if handle:
        kernel32.FreeLibrary(handle)
        return []
    error = ctypes.get_last_error()
    if error == ERROR_MOD_NOT_FOUND:
        return [f"No se pudo cargar {dll.name}. {RUNTIME_HINT}"]
    if error == ERROR_BAD_EXE_FORMAT:
        return [f"{dll.name} no es compatible con este Python/Java: ambos deben ser de 64 bits."]
    return [f"No se pudo cargar {dll} (código de Windows {error})."]


def check_winutils(winutils: Path) -> list[str]:
    result = subprocess.run(
        [str(winutils), "ls", str(winutils.parent)],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    if result.returncode & 0xFFFFFFFF == STATUS_DLL_NOT_FOUND:
        return [f"No se pudo ejecutar {winutils.name}. {RUNTIME_HINT}"]
    return [f"{winutils} terminó con código {result.returncode}."]


def verify_helpers(home: Path | None = None) -> list[str]:
    """Return every problem that would stop Spark from using the helpers; empty means valid."""
    home = home or helper_home()
    binary_dir = home / "bin"
    problems = []
    for filename, expected_sha256 in EXPECTED_SHA256.items():
        binary = binary_dir / filename
        if not binary.is_file():
            problems.append(f"Falta {binary}. Ejecute: python scripts/setup_windows_hadoop.py")
        elif file_sha256(binary) != expected_sha256:
            problems.append(
                f"El SHA-256 de {binary} no coincide. "
                "Ejecute de nuevo: python scripts/setup_windows_hadoop.py"
            )
    if problems:
        return problems

    problems += check_dll_loadable(binary_dir / "hadoop.dll")
    problems += check_winutils(binary_dir / "winutils.exe")

    # java.library.path busca en System32 antes que en PATH: una copia ajena tendría prioridad.
    system_dll = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "hadoop.dll"
    if system_dll.exists():
        problems.append(
            f"Existe {system_dll}: la JVM lo cargaría en lugar del helper verificado del "
            "proyecto. Retírelo o use Docker."
        )
    return problems


def download_helpers(binary_dir: Path) -> dict[str, str] | None:
    checksums: dict[str, str] = {}
    for filename, expected_sha256 in EXPECTED_SHA256.items():
        binary = binary_dir / filename
        if binary.exists() and file_sha256(binary) == expected_sha256:
            checksums[filename] = expected_sha256
            print(f"{filename} ya verificado: {binary}")
            continue

        partial = binary.with_suffix(binary.suffix + ".part")
        source_url = f"{SOURCE_BASE_URL}/{filename}"
        print(f"Descargando helper de Hadoop para Windows: {source_url}")
        request = Request(source_url, headers={"User-Agent": "ProyectoIntegrador2/0.1"})
        with urlopen(request, timeout=60) as response, partial.open("wb") as target:
            for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
                target.write(chunk)

        checksum = file_sha256(partial)
        if checksum != expected_sha256:
            partial.unlink(missing_ok=True)
            print(
                f"ERROR: el SHA-256 de {filename} no coincide con el valor esperado.",
                file=sys.stderr,
            )
            return None

        partial.replace(binary)
        checksums[filename] = checksum
        print(f"{filename} preparado y verificado: {binary}")
    return checksums


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo verifica los helpers existentes; no descarga nada.",
    )
    args = parser.parse_args()

    if os.name != "nt":
        print("No se requieren helpers nativos de Hadoop fuera de Windows.")
        return 0

    home = helper_home()
    binary_dir = home / "bin"
    if not args.check:
        binary_dir.mkdir(parents=True, exist_ok=True)
        checksums = download_helpers(binary_dir)
        if checksums is None:
            return 1
        metadata = {
            "hadoop_helper_version": HADOOP_HELPER_VERSION,
            "source_base_url": SOURCE_BASE_URL,
            "sha256": checksums,
        }
        (home / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )

    problems = verify_helpers(home)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"Helpers nativos verificados (hash, carga de hadoop.dll y winutils.exe): {binary_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
