import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "index.html"


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_web_exposes_three_interactive_findings() -> None:
    text = page()
    for control in ("p1-adjustment", "community-view", "hits-weight"):
        assert f'id="{control}"' in text
        assert f"by('{control}').addEventListener('change'" in text


def test_web_exposes_rubric_parameters_live() -> None:
    # k de KMeans, HDBSCAN, número de recomendaciones, amortiguamiento y comunidades.
    text = page()
    for control in ("cl-k", "cl-h", "rec-k", "pr-d", "gn-level", "emb-k", "p1-min"):
        assert f'id="{control}"' in text


def test_web_loads_public_data_with_a_static_reference() -> None:
    text = page()
    assert "fetch(`data/${name}.json`)" in text
    assert "../artifacts/" not in text  # artifacts/ no se publica en GitHub Pages
    assert "const reference" in text


def test_web_requests_only_published_files() -> None:
    names = re.search(r"const NAMES = \[([^\]]+)\]", page()).group(1)
    requested = {name.strip(" '") + ".json" for name in names.split(",")}
    published = ROOT / "web" / "data" / "manifest.json"
    if published.is_file():
        files = set(json.loads(published.read_text(encoding="utf-8"))["files"])
        assert requested <= files
