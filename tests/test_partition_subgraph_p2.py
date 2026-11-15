import networkx as nx

from src.models.partition_subgraph_p2 import (
    girvan_newman_levels,
    groups_from_labels,
    labels_from_sets,
    spectral_partition,
)


def two_triangles() -> nx.Graph:
    graph = nx.Graph()
    graph.add_weighted_edges_from(
        [
            ("a", "b", 3),
            ("a", "c", 3),
            ("b", "c", 3),
            ("x", "y", 3),
            ("x", "z", 3),
            ("y", "z", 3),
            ("c", "x", 0.1),
        ]
    )
    return graph


def test_girvan_newman_first_split_cuts_the_bridge() -> None:
    levels = girvan_newman_levels(two_triangles(), max_communities=2)

    assert sorted(map(sorted, levels[0])) == [["a", "b", "c"], ["x", "y", "z"]]


def test_spectral_separates_the_triangles() -> None:
    graph = two_triangles()
    labels = spectral_partition(graph, sorted(graph.nodes), k=2, seed=42)

    assert labels["a"] == labels["b"] == labels["c"]
    assert labels["x"] == labels["y"] == labels["z"]
    assert labels["a"] != labels["x"]


def test_labels_and_groups_round_trip() -> None:
    groups = [{"a", "b"}, {"c"}]
    labels = labels_from_sets(["a", "b", "c"], groups)

    assert sorted(map(sorted, groups_from_labels(labels))) == [["a", "b"], ["c"]]
