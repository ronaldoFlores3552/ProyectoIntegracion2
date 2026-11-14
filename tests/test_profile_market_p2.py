from src.quality.profile_market_p2 import UnionFind


def test_union_find_reports_deterministic_components() -> None:
    union_find = UnionFind()
    union_find.union("p3", "p2")
    union_find.union("p2", "p1")
    union_find.union("q2", "q1")

    groups = union_find.components()
    sizes = sorted((min(nodes), len(nodes)) for nodes in groups.values())

    assert sizes == [("p1", 3), ("q1", 2)]
