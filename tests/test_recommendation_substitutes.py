import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from src.models.recommendation_substitutes import pair_rates, segment_neighbors


def test_neighbors_stay_inside_segment() -> None:
    ids = pd.Index(["p1", "p2", "p3", "p4"])
    texts = ["cemento arena", "cemento arena fierro", "papel toner", "papel toner tinta"]
    vectors = normalize(TfidfVectorizer().fit_transform(texts))
    segments = pd.Series(["30", "30", "44", "44"], index=ids)

    result = segment_neighbors(ids, vectors, segments, k=1)

    pairs = dict(zip(result.supplier_id, result.substitute_id, strict=True))
    assert pairs == {"p1": "p2", "p2": "p1", "p3": "p4", "p4": "p3"}
    assert set(result.segment) == {"30", "44"}


def test_pair_rates_counts_shared_processes_and_buyers() -> None:
    pairs = pd.DataFrame({"supplier_id": ["a", "a"], "substitute_id": ["b", "c"]})
    processes = {"a": {1, 2}, "b": {2}, "c": {9}}
    buyers = {"a": {"x"}, "b": {"y"}, "c": {"x"}}

    rates = pair_rates(pairs, processes, buyers)

    assert rates == {"pairs": 2, "share_coparticipate": 0.5, "share_same_buyer": 0.5}
