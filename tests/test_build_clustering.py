import numpy as np
import pandas as pd
import pytest

from src.models.build_clustering import (
    add_flags,
    choose_models,
    prepare,
    read_input,
    valid_silhouette,
)


def test_preparation_handles_constant_dimension_and_category_weight():
    frame = pd.DataFrame(
        {
            "log_award_count": [1.0, 2.0, 3.0],
            "fraction_0": [0.5, 0.5, 0.5],
            "fraction_1": [0.3, 0.4, 0.2],
            "fraction_2": [0.2, 0.1, 0.3],
        }
    )
    matrices, metadata = prepare(frame)
    assert np.all(matrices["standard"][:, 1] == 0)
    np.testing.assert_allclose(
        matrices["weighted"][:, 1:], matrices["standard"][:, 1:] / np.sqrt(3)
    )
    assert metadata["variance"][1] == 0


def test_rejects_incomplete_part1_before_loading_data(tmp_path):
    with pytest.raises(FileNotFoundError, match="publicación completa"):
        read_input(tmp_path / "part1", tmp_path / "suppliers", tmp_path / "categories", 100)


def test_silhouette_and_selection_do_not_invent_valid_models():
    x = np.array([[0.0], [1.0], [2.0], [3.0]])
    assert valid_silhouette(x, np.array([-1, -1, -1, -1]), ignore_noise=True) is None
    assert valid_silhouette(x, np.array([0, 0, 0, 0])) is None
    km = pd.DataFrame([{"variant": "weighted", "k": 2, "min_cluster_size": 2, "silhouette": 0.8}])
    hm = pd.DataFrame(
        [
            {
                "variant": "weighted",
                "groups": 1,
                "coverage": 0.1,
                "silhouette_assigned": None,
                "min_cluster_size": 15,
                "min_samples": 5,
            }
        ]
    )
    assert choose_models(km, hm, 100) == (None, None)


def test_outlier_flag_is_scoped_to_selected_configuration():
    items = pd.DataFrame(
        [
            {
                "entity_id": f"e{i:03}",
                "method": "kmeans",
                "variant": "weighted",
                "config": "2",
                "label": 0,
                "distance": i,
            }
            for i in range(100)
        ]
        + [
            {
                "entity_id": "noise",
                "method": "hdbscan",
                "variant": "weighted",
                "config": "15:5",
                "label": -1,
                "distance": np.nan,
            },
            {
                "entity_id": "not_selected",
                "method": "hdbscan",
                "variant": "standard",
                "config": "15:5",
                "label": -1,
                "distance": np.nan,
            },
        ]
    )
    result = add_flags(items, {"k": 2}, {"min_cluster_size": 15, "min_samples": 5})
    assert set(result.loc[result.outlier_candidate, "entity_id"]) == {"e099", "noise"}
