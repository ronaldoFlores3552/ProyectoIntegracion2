import pytest

from src.models.recommendation_hybrid import validate_compatible_metadata


def test_validate_compatible_metadata_accepts_same_cut_and_input() -> None:
    metadata = {"cut": 2023, "input_sha256": "same"}

    validate_compatible_metadata(metadata, metadata.copy())


@pytest.mark.parametrize(
    ("als", "content", "field"),
    [
        ({"cut": 2023, "input_sha256": "same"}, {"cut": 2024, "input_sha256": "same"}, "cut"),
        (
            {"cut": 2023, "input_sha256": "one"},
            {"cut": 2023, "input_sha256": "two"},
            "input_sha256",
        ),
    ],
)
def test_validate_compatible_metadata_rejects_mismatch(
    als: dict, content: dict, field: str
) -> None:
    with pytest.raises(ValueError, match=field):
        validate_compatible_metadata(als, content)
