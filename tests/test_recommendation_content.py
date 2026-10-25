import pandas as pd
import pytest

from src.models.recommendation_content import content_rankings, select_training_items


def test_content_profiles_use_words_and_exclude_existing_links():
    items = pd.DataFrame(
        [
            ("e1", "a", "cemento concreto gris"),
            ("e2", "b", "cemento concreto blanco"),
            ("e2", "c", "madera tablero"),
            ("e3", "d", "vacunas farmacia"),
        ],
        columns=["entity_id", "supplier_id", "item_description"],
    )
    train = items[["entity_id", "supplier_id"]].copy()
    rankings, info = content_rankings(items, train, {"e1", "e3"}, min_df=1)
    assert rankings["e1"] == ["b"]
    assert rankings["e3"] == []
    assert info["entities_with_profile"] == 3
    assert info["suppliers_with_profile"] == 4


def test_only_training_items_are_used_and_counts_must_match():
    events = pd.DataFrame(
        [
            ("p1", "a1", "s1", "e1", "2022-12-31", 2022),
            ("p2", "a2", "s1", "e1", "2023-01-01", 2023),
            ("p3", "a3", "s2", "e2", None, None),
        ],
        columns=[
            "process_ocid",
            "award_id",
            "supplier_id",
            "entity_id",
            "award_date",
            "award_year",
        ],
    )
    items = pd.DataFrame(
        [
            ("p1", "a1", "s1", "i1", "texto anterior"),
            ("p2", "a2", "s1", "i2", "texto futuro"),
            ("p3", "a3", "s2", "i3", "fecha ausente"),
        ],
        columns=["process_ocid", "award_id", "supplier_id", "item_id", "item_description"],
    )
    train = pd.DataFrame(
        [("e1", "s1", 1)], columns=["entity_id", "supplier_id", "interaction_count"]
    )
    assert select_training_items(events, items, train).item_description.tolist() == [
        "texto anterior"
    ]
    train.loc[0, "interaction_count"] = 2
    with pytest.raises(ValueError, match="no concilian"):
        select_training_items(events, items, train)
