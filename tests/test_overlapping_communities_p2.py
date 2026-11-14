import numpy as np

from src.models.overlapping_communities_p2 import (
    bigclam_objective,
    fit_bigclam,
    memberships_from_affiliations,
    sampled_reconstruction_metrics,
)


def test_bigclam_improves_or_preserves_objective_on_two_dense_groups() -> None:
    edges = np.asarray([(0, 1), (0, 2), (1, 2), (3, 4), (3, 5), (4, 5)], dtype=int)

    affiliations, diagnostics = fit_bigclam(
        node_count=6,
        edges=edges,
        components=2,
        iterations=30,
        learning_rate=0.0001,
        seed=42,
    )

    assert affiliations.shape == (6, 2)
    assert np.all(affiliations >= 0)
    assert diagnostics.objective.is_monotonic_increasing
    assert diagnostics.iteration.max() > 1
    assert bigclam_objective(affiliations, edges) == diagnostics.iloc[-1].objective


def test_memberships_can_preserve_an_overlapping_node() -> None:
    affiliations = np.asarray([[1.0, 0.1], [0.8, 0.7], [0.2, 0.9]])

    memberships = memberships_from_affiliations(affiliations, membership_fraction=0.8)

    assert {(node, community) for node, community, _, _ in memberships} == {
        (0, 0),
        (1, 0),
        (1, 1),
        (2, 1),
    }


def test_reconstruction_diagnostic_samples_only_absent_pairs() -> None:
    affiliations = np.asarray([[1.0, 0.1], [0.9, 0.2], [0.1, 1.0], [0.2, 0.9]])
    edges = np.asarray([(0, 1), (2, 3)], dtype=int)

    metrics = sampled_reconstruction_metrics(affiliations, edges, negative_samples=10, seed=42)

    assert metrics["positive_edges_sampled"] == 2
    assert metrics["negative_pairs_sampled"] == 2
    assert 0.0 <= metrics["sampled_reconstruction_auc"] <= 1.0
    assert 0.0 <= metrics["sampled_reconstruction_average_precision"] <= 1.0
