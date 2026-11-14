import networkx as nx

from src.models.detect_communities_p2 import run_louvain


def test_louvain_finds_two_dense_groups() -> None:
    graph = nx.Graph()
    graph.add_weighted_edges_from(
        [
            ("a", "b", 3),
            ("a", "c", 3),
            ("b", "c", 3),
            ("x", "y", 3),
            ("x", "z", 3),
            ("y", "z", 3),
            ("c", "x", 0.01),
        ]
    )

    partition, modularity = run_louvain(graph, resolution=1.0, seed=42)

    assert partition["a"] == partition["b"] == partition["c"]
    assert partition["x"] == partition["y"] == partition["z"]
    assert partition["a"] != partition["x"]
    assert modularity > 0
