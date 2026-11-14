import pandas as pd
import pytest

from src.models.analyze_market_p1 import association, hhi_from_events


def test_association_centres_within_fixed_strata() -> None:
    metrics = pd.DataFrame(
        {
            "buyer_id": ["b1", "b2", "b3", "b4", "b5", "b6"],
            "department": ["LIMA"] * 6,
            "cubso_segment": ["72"] * 6,
            "procurement_method_details": ["Licitación"] * 6,
            "process_count": [10, 11, 12, 20, 21, 22],
            "hhi": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "reported_participants_median": [6, 5, 4, 3, 2, 1],
        }
    )

    raw = association(metrics, "reported_participants_median", 10, adjusted=False)
    adjusted = association(metrics, "reported_participants_median", 10, adjusted=True)

    assert raw["correlation"] == pytest.approx(-1.0)
    assert adjusted["correlation"] < -0.9
    assert adjusted["units"] == 6
    assert adjusted["strata"] == 2


def test_hhi_from_events_rebuilds_only_units_with_awards() -> None:
    units = pd.DataFrame(
        {
            "buyer_id": ["b1"],
            "department": ["LIMA"],
            "cubso_segment": ["72"],
            "procurement_method_details": ["Licitación"],
            "process_count": [3],
            "hhi": [0.0],
            "award_count": [0],
        }
    )
    events = pd.DataFrame(
        {
            "buyer_id": ["b1", "b1", "b1"],
            "department": ["LIMA"] * 3,
            "cubso_segment": ["72"] * 3,
            "procurement_method_details": ["Licitación"] * 3,
            "supplier_id": ["s1", "s1", "s2"],
        }
    )

    result = hhi_from_events(events, units).iloc[0]

    assert result["award_count"] == 3
    assert result["hhi"] == pytest.approx(5 / 9)


def test_hhi_from_events_accepts_a_monetary_weight() -> None:
    units = pd.DataFrame(
        {
            "buyer_id": ["b1"],
            "department": ["LIMA"],
            "cubso_segment": ["72"],
            "procurement_method_details": ["Licitación"],
            "process_count": [3],
        }
    )
    events = pd.DataFrame(
        {
            "buyer_id": ["b1", "b1", "b1"],
            "department": ["LIMA"] * 3,
            "cubso_segment": ["72"] * 3,
            "procurement_method_details": ["Licitación"] * 3,
            "supplier_id": ["s1", "s1", "s2"],
            "amount": [10, 10, 80],
        }
    )

    result = hhi_from_events(events, units, "amount").iloc[0]

    assert result["hhi"] == pytest.approx(0.68)
    assert result["concentration_weight_total"] == 100
