import pandas as pd

from src.models.recommendation_neighbors import neighbor_rankings


def test_neighbors_only_recommend_new_cooccurring_providers():
    train = pd.DataFrame(
        [
            ("e1", "a", 1.0),
            ("e2", "a", 1.0),
            ("e2", "b", 1.0),
            ("e3", "a", 1.0),
            ("e3", "c", 1.0),
            ("e4", "d", 1.0),
        ],
        columns=["entity_id", "supplier_id", "strength"],
    )
    rankings, diagnostic = neighbor_rankings(train, {"e1", "e4"}, k_neighbors=50)
    assert rankings == {"e1": ["b", "c"], "e4": []}
    assert diagnostic["pair_expansion"] == 2
