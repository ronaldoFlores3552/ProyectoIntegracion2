from src.models.louvain_order_p2 import build_graph, edge_orders


def test_edge_orders_keep_the_same_edges() -> None:
    edges = [("a", "b", 1.0), ("c", "d", 0.5), ("a", "c", 0.2), ("b", "d", 0.7)]
    orders = edge_orders(edges, [0, 1])

    assert set(orders) == {"archivo", "ordenado", "aleatorio_0", "aleatorio_1"}
    for ordered in orders.values():
        assert sorted(ordered) == sorted(edges)


def test_build_graph_keeps_weights() -> None:
    graph = build_graph([("a", "b", 0.25)])

    assert graph["a"]["b"]["weight"] == 0.25
