import numpy as np
from scipy import sparse

from src.models.analyze_links_p2 import hits_bipartite, pagerank_weighted


def test_hits_bipartite_favours_the_supplier_with_more_buyer_links() -> None:
    matrix = sparse.csr_matrix(np.array([[1, 0], [1, 1], [1, 0]], dtype=float))

    hubs, authorities, iterations = hits_bipartite(matrix, tolerance=1e-12, max_iterations=100)

    assert iterations < 100
    assert authorities[0] > authorities[1]
    assert hubs[1] > 0


def test_weighted_pagerank_is_a_probability_distribution() -> None:
    matrix = sparse.csr_matrix(np.array([[0, 2, 1], [2, 0, 0], [1, 0, 0]], dtype=float))

    rank, iterations = pagerank_weighted(matrix, damping=0.85, tolerance=1e-12, max_iterations=1000)

    assert iterations < 1000
    np.testing.assert_approx_equal(rank.sum(), 1.0)
    assert rank[0] > rank[1] > 0
