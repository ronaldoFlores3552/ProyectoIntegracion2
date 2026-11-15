import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_project.py"


def run_runner(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_list_exposes_pipeline_stages() -> None:
    result = run_runner("pipeline", "--list")
    assert result.returncode == 0
    assert "base" in result.stdout
    assert "web" in result.stdout


def test_dry_run_does_not_execute_pipeline() -> None:
    result = run_runner("pipeline", "p1", "--dry-run")
    assert result.returncode == 0
    assert "src.features.build_market_p1" in result.stdout
    assert "Pipeline terminado: p1" in result.stdout


def test_unknown_stage_returns_clear_error() -> None:
    result = run_runner("pipeline", "inexistente")
    assert result.returncode != 0
    assert "Etapa(s) desconocida(s): inexistente" in result.stderr


def test_pipeline_requires_an_explicit_stage() -> None:
    result = run_runner("pipeline")
    assert result.returncode != 0
    assert "Indique una etapa o use --all" in result.stderr
