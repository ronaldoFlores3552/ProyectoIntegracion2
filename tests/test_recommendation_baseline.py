from math import log2

import pandas as pd
import pytest

from src.models.recommendation_baseline import rank_popularity, score_rankings


def test_popularity_uses_distinct_entities_and_breaks_ties_by_id():
    train = pd.DataFrame(
        [("e1", "a"), ("e1", "a"), ("e2", "b"), ("e3", "a"), ("e3", "c")],
        columns=["entity_id", "supplier_id"],
    )
    assert rank_popularity(train, {"e1", "e2"}, 3) == {"e1": ["b", "c"], "e2": ["a", "c"]}


def test_metrics_penalize_missing_positions_and_use_all_positives():
    result = score_rankings({"e1": ["b"]}, {"e1": {"b", "c"}}, {"e1": 3}, 3).iloc[0]
    assert result.recall == pytest.approx(0.5)
    assert result.precision == pytest.approx(1 / 3)
    assert result.ndcg == pytest.approx(1 / (1 + 1 / log2(3)))
    assert result.ranking_length == 1


def test_duplicate_rankings_rejected():
    with pytest.raises(ValueError, match="duplicado"):
        score_rankings({"e1": ["a", "a"]}, {"e1": {"a"}}, {"e1": 2}, 2)
