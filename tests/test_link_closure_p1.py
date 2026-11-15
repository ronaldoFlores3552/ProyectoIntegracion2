import numpy as np
import pandas as pd

from src.models.link_closure_p1 import expected_hhi, observed_hhi, unit_closure


def test_closure_counts_participations_by_community() -> None:
    processes = pd.DataFrame(
        {
            "buyer_id": ["b", "b"],
            "department": ["PUNO", "PUNO"],
            "cubso_segment": ["72", "72"],
            "procurement_method_details": ["AS", "AS"],
            "process_ocid": ["p1", "p2"],
        }
    )
    tenderers = pd.DataFrame(
        {"process_ocid": ["p1", "p1", "p2", "p2"], "participant_id": ["x", "y", "x", "z"]}
    )
    communities = pd.DataFrame({"participant_id": ["x", "y"], "community": [1, 2]})

    result = unit_closure(processes, tenderers, communities).iloc[0]

    assert result.participations == 4
    assert result.labeled_participations == 3
    assert result.closure == 2 / 3
    assert result.labeled_share == 3 / 4


def test_expected_hhi_matches_enumeration() -> None:
    events = pd.DataFrame(
        {
            "buyer_id": ["b", "b"],
            "department": ["PUNO", "PUNO"],
            "cubso_segment": ["72", "72"],
            "procurement_method_details": ["AS", "AS"],
            "process_ocid": ["p1", "p2"],
            "award_id": ["a1", "a2"],
            "supplier_id": ["a", "a"],
        }
    )
    candidates = {"p1": np.array(["a", "b"]), "p2": np.array(["a"])}

    expected = expected_hhi(events, candidates).expected_hhi.iloc[0]
    observed = observed_hhi(events, candidates).observed_hhi.iloc[0]

    assert np.isclose(expected, 0.75)
    assert np.isclose(observed, 1.0)


def test_expected_hhi_keeps_awards_with_repeated_ids_across_processes() -> None:
    events = pd.DataFrame(
        {
            "buyer_id": ["b", "b"],
            "department": ["PUNO", "PUNO"],
            "cubso_segment": ["72", "72"],
            "procurement_method_details": ["AS", "AS"],
            "process_ocid": ["p1", "p2"],
            "award_id": ["1", "1"],
            "supplier_id": ["a", "c"],
        }
    )
    candidates = {"p1": np.array(["a"]), "p2": np.array(["c"])}

    assert np.isclose(expected_hhi(events, candidates).expected_hhi.iloc[0], 0.5)
