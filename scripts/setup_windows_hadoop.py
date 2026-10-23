"""Prepara el helper nativo mínimo que Hadoop requiere al escribir en Windows."""

from __future__ import annotations

import hashlib
import json
import os
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


def main() -> int:
    if os.name != "nt":
        print("No se requieren helpers nativos de Hadoop fuera de Windows.")
        return 0

    home = helper_home()
    binary_dir = home / "bin"
    binary_dir.mkdir(parents=True, exist_ok=True)
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
            return 1

        partial.replace(binary)
        checksums[filename] = checksum
        print(f"{filename} preparado y verificado: {binary}")

    metadata = {
        "hadoop_helper_version": HADOOP_HELPER_VERSION,
        "source_base_url": SOURCE_BASE_URL,
        "sha256": checksums,
    }
    (home / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Helpers nativos preparados y verificados: {binary_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

