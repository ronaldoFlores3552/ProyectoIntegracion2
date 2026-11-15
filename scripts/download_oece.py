"""Descarga el Listado de ofertantes de OECE (CONOSCE) por año de convocatoria."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.download_data import CHUNK_SIZE, sha256_file, utc_now

BASE_URL = "https://conosce.osce.gob.pe/buscador/assets/67ae6c4a/reportes"
DATASET_URL = (
    "https://www.datosabiertos.gob.pe/dataset/listado-de-ofertantes-%E2%80%93-organismo-"
    "especializado-para-las-contrataciones-p%C3%BAblicas-eficientes"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=[2021, 2022, 2023, 2024])
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/oece"))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def download(url: str, target: Path) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=300) as response, partial.open("wb") as sink:
        for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
            sink.write(chunk)
    partial.replace(target)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = [
        (f"{BASE_URL}/postor/{year}/POSTOR{year}_0.xlsx", f"POSTOR{year}_0.xlsx")
        for year in args.years
    ]
    files.append((f"{BASE_URL}/Diccionario.xlsx", "Diccionario.xlsx"))
    entries = []
    for url, name in files:
        target = args.output_dir / name
        if args.force or not target.is_file():
            download(url, target)
        entries.append({"url": url, "file": name, "sha256": sha256_file(target)})
        print(f"{name}: {entries[-1]['sha256']}")
    manifest = {"downloaded_at_utc": utc_now(), "dataset": DATASET_URL, "files": entries}
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
