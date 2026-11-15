import numpy as np
import pandas as pd

from src.models.build_svd_p2 import build_participation_matrix


def test_participation_matrix_keeps_recurrent_and_normalizes_rows() -> None:
    edges = pd.DataFrame(
        {
            "buyer_id": ["a", "a", "b", "b", "c"],
            "participant_id": ["x", "y", "x", "z", "y"],
            "process_count": [3, 1, 2, 5, 1],
        }
    )
    recurrence = pd.Series({"x": 6, "y": 5, "z": 1})

    matrix, buyers, participants = build_participation_matrix(edges, recurrence, 5)

    assert list(participants) == ["x", "y"]
    norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel())
    assert np.allclose(norms[norms > 0], 1.0)
