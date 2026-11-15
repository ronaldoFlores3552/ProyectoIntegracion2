import pandas as pd

from src.models.profile_outliers import dominant_reason


def test_reason_names_the_largest_deviation_and_its_sign() -> None:
    assert dominant_reason(pd.Series({"a": 0.5, "b": -3.0})) == "b bajo"
    assert dominant_reason(pd.Series({"a": 2.0, "b": -1.0})) == "a alto"
