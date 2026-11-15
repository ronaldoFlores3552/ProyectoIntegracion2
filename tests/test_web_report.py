from pathlib import Path


def test_web_exposes_three_interactive_findings() -> None:
    page = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    for control in ("p1-adjustment", "community-view", "hits-weight"):
        assert f'id="{control}"' in page
        assert f"by('{control}').addEventListener('change'" in page


def test_web_loads_exported_data_with_a_static_reference() -> None:
    page = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    assert "../artifacts/web_data/" in page
    assert "const reference" in page
