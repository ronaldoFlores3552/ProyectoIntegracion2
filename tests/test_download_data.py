from pathlib import Path

from scripts.download_data import (
    build_url,
    parse_years,
    read_manifest,
    sha256_file,
    upsert_download,
    write_manifest,
)


def test_parse_years_supports_commas_and_removes_duplicates() -> None:
    assert parse_years(["2023, 2024", "2024", "2025"]) == ["2023", "2024", "2025"]


def test_build_url() -> None:
    assert build_url("https://example.test/dataset/", "2024") == "https://example.test/dataset/2024.jsonl.gz"


def test_manifest_is_written_and_read(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = read_manifest(path)
    upsert_download(manifest, {"year": "2024", "sha256": "abc"})
    write_manifest(path, manifest)
    assert read_manifest(path)["downloads"] == [{"year": "2024", "sha256": "abc"}]


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("datos OCDS", encoding="utf-8")
    assert sha256_file(path) == "bf13db49307e6e599c8a8bb92ee8dfeb191c3eebabc4861b8d7656477866ef9d"

