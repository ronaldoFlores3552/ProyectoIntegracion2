import json
from pathlib import Path

import pytest

from src.web import publish_web_data as publisher


def write_inputs(folder: Path, overrides: dict | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in publisher.PUBLIC_FILES:
        value = {"ok": 1}
        if name == "links.json":
            value = {"hubs": [{"buyer_name": "MUNICIPALIDAD"}], "graph": {"source": [0]}}
        value = (overrides or {}).get(name, value)
        (folder / name).write_text(json.dumps(value), encoding="utf-8")


def test_publish_drops_department_graph_and_writes_manifest(tmp_path: Path) -> None:
    write_inputs(tmp_path / "in")
    manifest = publisher.publish(tmp_path / "in", tmp_path / "out")
    links = json.loads((tmp_path / "out" / "links.json").read_text(encoding="utf-8"))
    assert "graph" not in links
    assert links["hubs"][0]["buyer_name"] == "MUNICIPALIDAD"
    assert set(manifest["files"]) == set(publisher.PUBLIC_FILES)
    assert (tmp_path / "out" / "manifest.json").is_file()


@pytest.mark.parametrize(
    "value",
    [
        {"rows": [{"supplier_name": "X"}]},
        {"rows": [{"participant_id": 1}]},
        {"note": "ganador PE-RUC-20123456789"},
    ],
)
def test_publish_refuses_private_actors(tmp_path: Path, value: dict) -> None:
    write_inputs(tmp_path / "in", {"findings.json": value})
    with pytest.raises(ValueError, match="findings.json"):
        publisher.publish(tmp_path / "in", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_publish_requires_every_input(tmp_path: Path) -> None:
    write_inputs(tmp_path / "in")
    (tmp_path / "in" / "p1.json").unlink()
    with pytest.raises(FileNotFoundError, match="p1.json"):
        publisher.publish(tmp_path / "in", tmp_path / "out")
