import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_validator():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "validate_environment", SCRIPTS / "validate_environment.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_preflight_checks_openpyxl_for_oece_validation() -> None:
    # La validación OECE lee el Listado de ofertantes en Excel con openpyxl.
    assert "openpyxl" in load_validator().REQUIRED_PACKAGES


def test_preflight_packages_are_pinned_in_requirements() -> None:
    requirements = (SCRIPTS.parent / "requirements.txt").read_text(encoding="utf-8").lower()
    for package in load_validator().REQUIRED_PACKAGES:
        assert f"{package}==" in requirements, package
