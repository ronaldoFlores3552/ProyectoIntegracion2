import pandas as pd

from src.quality.validate_tenderers_oece import (
    bidder_participation,
    compare_sets,
    join_coverage,
    summarize,
)


def frames():
    tenders = pd.DataFrame(
        {
            "process_ocid": ["a", "b", "c"],
            "source_year": ["2023", "2023", "2024"],
            "buyer_id": ["B1", "B1", "B2"],
            "tender_id": ["10", "20", "30"],
            "procurement_method_details": ["AS", "AS", "CD"],
            "number_of_tenderers": [3, 1, 1],
            "tenderer_list_count": [3, 1, 1],
        }
    )
    tenderers = pd.DataFrame(
        {
            "source_year": ["2023"] * 4 + ["2024"],
            "process_ocid": ["a", "a", "a", "b", "c"],
            "participant_id": ["PE-RUC-1", "PE-RUC-2", "PE-RUC-3", "PE-RUC-4", "PE-RUC-5"],
        }
    )
    bidders = pd.DataFrame(
        {
            "tender_id": ["10", "10", "20"],
            "code": ["1", "9", "4"],
            "participant_name": ["Uno", "Nueve", "Cuatro"],
        }
    )
    return tenders, tenderers, bidders


def test_compare_sets_counts_overlap_per_process():
    per_process = compare_sets(*frames()).set_index("process_ocid")
    assert set(per_process.index) == {"a", "b"}
    assert per_process.loc["a", ["reported", "bidders", "shared"]].tolist() == [3, 2, 1]
    assert bool(per_process.loc["b", "identical"])
    total = summarize(per_process.reset_index(), None).iloc[0]
    assert total["reported_that_bid"] == 2 / 4
    assert total["bidders_in_reported"] == 2 / 3


def test_bidder_participation_replaces_lists_with_bidders():
    fact_tender, fact_tenderer = bidder_participation(*frames())
    assert fact_tender.set_index("process_ocid")["tenderer_list_count"].to_dict() == {
        "a": 2,
        "b": 1,
    }
    assert sorted(fact_tenderer["participant_id"]) == ["PE-RUC-1", "PE-RUC-4", "PE-RUC-9"]


def test_shared_call_code_repeats_bidders_and_keeps_number_of_tenderers():
    tenders, tenderers, bidders = frames()
    tenders = pd.concat(
        [tenders, tenders.iloc[[0]].assign(process_ocid="a2", number_of_tenderers=9)],
        ignore_index=True,
    )
    fact_tender, fact_tenderer = bidder_participation(tenders, tenderers, bidders)
    counts = fact_tender.set_index("process_ocid")
    assert counts.loc["a2", "tenderer_list_count"] == 2
    assert counts.loc["a2", "number_of_tenderers"] == 9
    assert sorted(fact_tenderer.loc[fact_tenderer.process_ocid == "a2", "participant_id"]) == [
        "PE-RUC-1",
        "PE-RUC-9",
    ]
    per_process = compare_sets(tenders, tenderers, bidders).set_index("process_ocid")
    assert per_process.loc["a2", ["reported", "bidders", "shared"]].tolist() == [0, 2, 0]


def test_join_coverage_counts_shared_codes_and_unmatched():
    tenders, _, bidders = frames()
    tenders = pd.concat([tenders, tenders.iloc[[0]].assign(process_ocid="a2")], ignore_index=True)
    coverage = join_coverage(tenders, bidders)
    assert coverage["matched_call_codes"] == 2
    assert coverage["call_codes_with_several_processes"] == 1
    assert coverage["processes_sharing_a_call_code"] == 2
    assert coverage["unmatched_processes"] == 1
