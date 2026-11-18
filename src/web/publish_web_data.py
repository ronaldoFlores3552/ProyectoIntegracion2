"""Publica en web/data/ solo los JSON curados que necesita el reporte estático.

Corre en local: lee artifacts/web_data/ (ignorado por git) y escribe una copia
versionable para GitHub Pages. Quita las piezas que el navegador no usa y se
detiene si encuentra identificadores o nombres de proveedores o participantes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

# Archivo -> claves de primer nivel que no se publican.
PUBLIC_FILES: dict[str, tuple[str, ...]] = {
    "summary.json": (),
    "segments.json": (),
    "p1.json": (),
    "oece.json": (),
    "profiles.json": (),
    # El grafo departamental completo (1 904 nodos, 85 mil aristas) no se usa en la
    # página y facilitaría reidentificar participantes; basta el núcleo de 120 nodos.
    "links.json": ("graph",),
    "communities.json": (),
    "findings.json": (),
    "embedding.json": (),
    "recommendation.json": (),
}
FORBIDDEN_KEYS = {"supplier_id", "supplier_name", "participant_id", "participant_name"}
FORBIDDEN_TEXT = re.compile(r"PE-RUC-\d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, default=Path("artifacts/web_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("web/data"))
    return parser.parse_args()


def privacy_problems(value: object, path: str = "$") -> list[str]:
    """Devuelve las rutas JSON que exponen proveedores o participantes."""
    problems: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_KEYS:
                problems.append(f"{path}.{key}")
            problems.extend(privacy_problems(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            problems.extend(privacy_problems(item, f"{path}[{index}]"))
    elif isinstance(value, str) and FORBIDDEN_TEXT.search(value):
        problems.append(path)
    return problems


def curate(name: str, value: dict) -> dict:
    dropped = PUBLIC_FILES[name]
    return {key: item for key, item in value.items() if key not in dropped}


def publish(input_dir: Path, output_dir: Path) -> dict:
    missing = [name for name in PUBLIC_FILES if not (input_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Faltan {', '.join(missing)} en {input_dir}; ejecute antes la etapa web."
        )
    curated = {}
    for name in PUBLIC_FILES:
        value = curate(name, json.loads((input_dir / name).read_text(encoding="utf-8")))
        problems = privacy_problems(value)
        if problems:
            raise ValueError(f"{name} expone actores privados: {', '.join(problems[:5])}")
        curated[name] = value
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, value in curated.items():
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        data = (text + "\n").encode("utf-8")
        (output_dir / name).write_bytes(data)
        files[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {
        "published_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "artifacts/web_data (src.web.export_web_data)",
        "dropped_keys": {name: list(keys) for name, keys in PUBLIC_FILES.items() if keys},
        "files": files,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def run() -> None:
    args = parse_args()
    manifest = publish(args.input_dir, args.output_dir)
    total = sum(item["bytes"] for item in manifest["files"].values())
    print(f"Datos públicos en {args.output_dir}: {len(manifest['files'])} archivos, {total} bytes")


if __name__ == "__main__":
    run()
