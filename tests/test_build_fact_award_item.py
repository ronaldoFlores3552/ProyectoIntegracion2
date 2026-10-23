from pathlib import Path

import pytest

from scripts.setup_windows_hadoop import verify_helpers
from src.processing.build_fact_award_item import publish_output, staging_dir


def test_publish_replaces_output_only_with_complete_staging(tmp_path: Path) -> None:
    output = tmp_path / "fact_award_item"
    output.mkdir()
    (output / "old.parquet").write_text("anterior", encoding="utf-8")
    staging = staging_dir(output)
    staging.mkdir()
    (staging / "_SUCCESS").touch()

    publish_output(staging, output)

    assert (output / "_SUCCESS").is_file()
    assert not (output / "old.parquet").exists()
    assert not staging.exists()


def test_incomplete_staging_keeps_previous_output(tmp_path: Path) -> None:
    output = tmp_path / "fact_award_item"
    output.mkdir()
    (output / "_SUCCESS").touch()
    staging = staging_dir(output)
    staging.mkdir()

    with pytest.raises(RuntimeError, match="_SUCCESS"):
        publish_output(staging, output)

    assert (output / "_SUCCESS").is_file()


def test_verify_helpers_reports_missing_binaries(tmp_path: Path) -> None:
    problems = verify_helpers(tmp_path)
    assert len(problems) == 2
    assert all("setup_windows_hadoop.py" in problem for problem in problems)
