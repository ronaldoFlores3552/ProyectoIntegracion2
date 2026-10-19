"""Descarga reproducible de datos OCDS de OECE/OSCE."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://fastly.data.open-contracting.org/downloads/peru_oece_bulk/4263"
DEFAULT_YEARS = ("2023", "2024", "2025")
CHUNK_SIZE = 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_years(values: list[str]) -> list[str]:
    years = [item.strip() for value in values for item in value.split(",") if item.strip()]
    if not years or any(not year.isdigit() or len(year) != 4 for year in years):
        raise ValueError("Use años de cuatro dígitos, por ejemplo: 2023 2024.")
    return list(dict.fromkeys(years))


def build_url(base_url: str, year: str) -> str:
    return f"{base_url.rstrip('/')}/{year}.jsonl.gz"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "dataset": "Contrataciones públicas del Perú - OECE/OSCE (OCDS)",
            "publisher": "OECE/OSCE",
            "license": "CC BY 4.0",
            "registry_url": "https://data.open-contracting.org/es/publication/135",
            "format": "JSON Lines comprimido con gzip",
            "downloads": [],
        }
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"El manifiesto no es JSON válido: {path}") from exc
    if not isinstance(manifest.get("downloads"), list):
        raise ValueError(f"El manifiesto no contiene la lista downloads: {path}")
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = utc_now()
    temporary = path.with_suffix(".tmp")
    content = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def upsert_download(manifest: dict[str, Any], entry: dict[str, Any]) -> None:
    records = [item for item in manifest["downloads"] if item.get("year") != entry["year"]]
    records.append(entry)
    manifest["downloads"] = sorted(records, key=lambda item: item["year"])


def download_file(url: str, destination: Path, retries: int, timeout: int) -> tuple[int, str]:
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"User-Agent": "ProyectoIntegrador2/0.1"})
            with urlopen(request, timeout=timeout) as response, partial.open("wb") as target:
                if response.status != 200:
                    raise HTTPError(
                        url,
                        response.status,
                        "Respuesta HTTP no exitosa",
                        response.headers,
                        None,
                    )
                for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
                    target.write(chunk)
            size = partial.stat().st_size
            if size == 0:
                raise ValueError("La descarga terminó con un archivo vacío.")
            checksum = sha256_file(partial)
            partial.replace(destination)
            return size, checksum
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < retries:
                wait = min(2 ** (attempt - 1), 8)
                message = f"  Intento {attempt}/{retries} falló: {exc}. Reintento en {wait}s."
                print(message, file=sys.stderr)
                time.sleep(wait)
    raise RuntimeError(f"No se pudo descargar {url} después de {retries} intentos: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Descarga archivos JSONL.GZ OCDS de OECE/OSCE.")
    parser.add_argument("--years", nargs="+", default=list(DEFAULT_YEARS))
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        years = parse_years(args.years)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.timeout <= 0 or args.retries <= 0:
        print("Error: --timeout y --retries deben ser positivos.", file=sys.stderr)
        return 2

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    try:
        manifest = read_manifest(manifest_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    known = {entry.get("year"): entry for entry in manifest["downloads"]}
    for year in years:
        destination = output_dir / f"{year}.jsonl.gz"
        previous = known.get(year, {})
        is_verified = destination.exists() and previous.get("sha256") == sha256_file(destination)
        if not args.force and is_verified:
            print(f"[omitido] {destination.name}: checksum verificado.")
            continue

        url = build_url(args.base_url, year)
        print(f"[descargando] {year}: {url}")
        try:
            size, checksum = download_file(url, destination, args.retries, args.timeout)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        upsert_download(manifest, {
            "year": year, "filename": destination.name, "url": url,
            "size_bytes": size, "sha256": checksum, "downloaded_at": utc_now(),
        })
        write_manifest(manifest_path, manifest)
        print(f"[ok] {destination.name}: {size:,} bytes; sha256={checksum}")

    write_manifest(manifest_path, manifest)
    print(f"Manifiesto actualizado: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

