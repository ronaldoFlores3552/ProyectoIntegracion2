from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from src.features.build_interactions import (
    _check_sentinel,
    _validate_paths,
    build_interaction,
    source_metrics,
)
from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import configure_windows_hadoop


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = SparkSession.builder.master("local[2]").appName("test-build-interactions")
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


@pytest.fixture()
def sample(spark: SparkSession):
    return spark.sql(
        """
        SELECT 'e1' AS entity_id, 's1' AS supplier_id, 'goods' AS procurement_category,
               TIMESTAMP '2023-02-01 00:00:00' AS award_date, 'PEN' AS award_currency,
               CAST(10 AS DECIMAL(20, 2)) AS award_amount_single_supplier,
               CAST(10 AS DECIMAL(20, 2)) AS award_amount
        UNION ALL
        SELECT 'e1', 's1', 'goods', TIMESTAMP '2023-03-01 00:00:00', 'PEN', NULL, 20
        UNION ALL
        SELECT 'e1', 's1', NULL, TIMESTAMP '2023-03-01 00:00:00', 'USD', 30, 30
        UNION ALL
        SELECT 'e1', 's1', 'goods', TIMESTAMP '2023-03-01 00:00:00', NULL, 40, 40
        UNION ALL
        SELECT 'e1', 's1', 'goods', NULL, 'PEN', 50, 50
        UNION ALL
        SELECT NULL, 's1', 'goods', TIMESTAMP '2023-03-01 00:00:00', 'PEN', 60, 60
        """
    )


def test_supplier_counts_currency_and_attributable_amounts(sample) -> None:
    result = build_interaction(sample, "supplier_id", "award_amount_single_supplier").collect()
    groups = {row["award_currency"]: row.asDict() for row in result}
    assert groups["PEN"]["award_count"] == 2
    assert groups["PEN"]["amount_known_count"] == 1
    assert groups["PEN"]["amount_sum"] == 10
    assert groups["USD"]["amount_sum"] == 30
    assert groups["<MISSING>"]["award_count"] == 1
    assert groups["<MISSING>"]["amount_sum"] is None
    metrics = source_metrics(sample, "supplier_id", "award_amount_single_supplier")
    assert metrics["input_rows"] == 6
    assert metrics["missing_date_rows"] == 1
    assert metrics["missing_entity_rows"] == 1
    assert metrics["excluded_rows"] == 2
    assert metrics["eligible_rows"] == 4
    assert metrics["eligible_amount_known_rows"] == 2


def test_category_uses_award_amount_and_preserves_missing_category(sample) -> None:
    result = build_interaction(sample, "procurement_category", "award_amount").collect()
    groups = {(row["procurement_category"], row["award_currency"]): row for row in result}
    assert groups[("goods", "PEN")]["amount_sum"] == 30
    assert groups[("<MISSING>", "USD")]["award_count"] == 1
    assert groups[("goods", "<MISSING>")]["amount_sum"] is None
    assert source_metrics(sample, "procurement_category", "award_amount")[
        "eligible_missing_category_rows"
    ] == 1


def test_overlapping_output_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "_SUCCESS").touch()
    with pytest.raises(ValueError, match="solaparse"):
        _validate_paths((source,), (source / "output",), overwrite=True)


def test_reserved_missing_marker_in_source_is_rejected(spark: SparkSession) -> None:
    frame = spark.sql("SELECT '<MISSING>' AS award_currency, 'goods' AS procurement_category")
    with pytest.raises(ValueError, match="valor reservado"):
        _check_sentinel(frame, "procurement_category")
