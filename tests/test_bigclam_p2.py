import networkx as nx
import numpy as np
from scipy import sparse

from src.models.bigclam_p2 import (
    fit_bigclam,
    heldout_metrics,
    log_likelihood,
    membership_shares,
    seed_neighborhoods,
    sensitivity_factors,
    update_node,
)


def two_cliques() -> sparse.csr_matrix:
    graph = nx.disjoint_union(nx.complete_graph(6), nx.complete_graph(6))
    graph.add_edge(0, 6)
    return sparse.csr_matrix(nx.to_scipy_sparse_array(graph, weight=None, format="csr"))


def test_seed_neighborhoods_do_not_reuse_neighbors() -> None:
    factors = seed_neighborhoods(two_cliques(), k=2)

    assert factors.shape == (12, 2)
    assert (factors.sum(axis=0) > 0).all()


def test_fit_increases_likelihood_and_separates_cliques() -> None:
    adjacency = two_cliques()
    factors, history = fit_bigclam(adjacency, k=2, iterations=200, seed=42)

    assert history[-1] >= history[0]
    first, second = factors[1:6].argmax(axis=1), factors[7:12].argmax(axis=1)
    assert len(set(first)) == 1 and len(set(second)) == 1
    assert first[0] != second[0]


def test_log_likelihood_matches_bruteforce() -> None:
    adjacency = two_cliques()
    factors = np.random.default_rng(0).uniform(0.1, 1.0, (12, 2))
    upper = sparse.triu(adjacency, k=1).tocoo()
    expected = 0.0
    edges = set(zip(upper.row.tolist(), upper.col.tolist(), strict=True))
    for u in range(12):
        for v in range(u + 1, 12):
            dot = factors[u] @ factors[v]
            expected += np.log1p(-np.exp(-dot)) if (u, v) in edges else -dot

    assert np.isclose(log_likelihood(factors, upper.row, upper.col), expected)


def test_zero_node_recovers_from_huge_gradient() -> None:
    neighbors = np.array([[1.0, 0.0], [0.8, 0.1]])
    outside = np.array([0.5, 0.5])

    candidate = update_node(np.zeros(2), neighbors, outside)

    assert candidate is not None
    assert (neighbors @ candidate > 0).all()


def test_excluded_pairs_leave_the_objective() -> None:
    adjacency = two_cliques()
    factors = np.full((12, 2), 0.5)
    upper = sparse.triu(adjacency, k=1).tocoo()
    excluded = np.array([[0, 11]])

    full = log_likelihood(factors, upper.row, upper.col)
    reduced = log_likelihood(factors, upper.row, upper.col, excluded)

    assert np.isclose(reduced - full, factors[0] @ factors[11])


def test_heldout_metrics_rank_true_edges_first() -> None:
    factors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]])
    metrics = heldout_metrics(factors, np.array([[0, 1], [2, 3]]), np.array([[0, 2], [1, 3]]))

    assert metrics["heldout_auc"] == 1.0
    assert metrics["heldout_average_precision"] == 1.0


def test_membership_shares_count_nodes_without_community() -> None:
    factors = np.array([[0.9, 0.8], [0.9, 0.0], [0.0, 0.0]])
    shares = membership_shares(factors, 0.5)

    assert np.isclose(shares["share_nodes_without_community"], 1 / 3)
    assert np.isclose(shares["share_nodes_overlapping"], 1 / 3)


def test_sensitivity_factors_always_include_base_threshold() -> None:
    assert sensitivity_factors([0.5, 2.0]) == [0.5, 1.0, 2.0]
    assert sensitivity_factors([1.0, 0.5, 1.0]) == [0.5, 1.0]
