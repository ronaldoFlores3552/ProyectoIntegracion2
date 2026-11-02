import pandas as pd

from src.models.recommendation_als import exact_rankings


def test_exact_ranking_excludes_history_and_resolves_ties_by_id():
    users = pd.DataFrame([("e1", [1.0, 0.0])], columns=["entity_id", "features"])
    items = pd.DataFrame(
        [("c", [1.0, 0.0]), ("a", [2.0, 0.0]), ("b", [1.0, 0.0])],
        columns=["supplier_id", "features"],
    )
    train = pd.DataFrame([("e1", "a")], columns=["entity_id", "supplier_id"])
    assert exact_rankings(users, items, train, {"e1"}, top_k=2) == {"e1": ["b", "c"]}
