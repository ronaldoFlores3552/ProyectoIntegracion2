import random

from src.models.null_communities_p2 import curveball_trade, validate_margins


def test_curveball_preserves_participant_and_process_margins() -> None:
    adjacency = [{0, 1}, {1, 2}, {0, 2}]
    participant_sizes = [len(values) for values in adjacency]
    process_sizes = [2, 2, 2]

    curveball_trade(adjacency, random.Random(42))

    assert [len(values) for values in adjacency] == participant_sizes
    assert validate_margins(adjacency, process_sizes)
