import importlib.util
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "verify_delivery_consistency",
    Path(__file__).resolve().parents[1] / "scripts" / "verify_delivery_consistency.py",
)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def test_differs_rejects_non_finite_values() -> None:
    assert verify.differs(math.nan, 0.5, 1e-3)
    assert verify.differs(0.5, math.nan, 1e-3)
    assert verify.differs(math.inf, 0.5, 1e-3)


def test_differs_respects_tolerance() -> None:
    assert not verify.differs(0.5004, 0.5, 5e-4)
    assert verify.differs(0.501, 0.5, 5e-4)


def test_stale_patterns_skip_negative_interval_bound() -> None:
    failures: list[str] = []
    verify.check_text("doc", "IC [−0,137; 0,063]", [], failures)
    assert failures == []
    verify.check_text("doc", "NMI 0,137", [], failures)
    assert len(failures) == 1
