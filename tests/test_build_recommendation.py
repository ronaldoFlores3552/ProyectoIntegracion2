"""Casos límite del contrato de cortes retrospectivos."""

import pytest
from pyspark.sql import SparkSession

from src.features.build_recommendation import split_pairs
from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import configure_windows_hadoop


@pytest.fixture(scope="module")
def spark():
    hadoop = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.master("local[2]")
        .appName("recommendation-test")
        .config("spark.sql.session.timeZone", "America/Lima")
    )
    if hadoop:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


def test_training_excludes_future_and_classifies_pairs(spark):
    rows = spark.sql("""
        SELECT 'e1' entity_id, 's1' supplier_id, TIMESTAMP '2022-12-31 12:00:00' award_date
        UNION ALL SELECT 'e1', 's1', TIMESTAMP '2022-01-01 00:00:00'
        UNION ALL SELECT 'e2', 's2', TIMESTAMP '2022-03-01 00:00:00'
        UNION ALL SELECT 'e1', 's1', TIMESTAMP '2023-01-01 00:00:00'
        UNION ALL SELECT 'e1', 's2', TIMESTAMP '2023-01-01 00:00:00'
        UNION ALL SELECT 'e1', 's2', TIMESTAMP '2023-02-01 00:00:00'
        UNION ALL SELECT 'e1', 's3', TIMESTAMP '2023-02-01 00:00:00'
        UNION ALL SELECT 'e3', 's1', TIMESTAMP '2023-02-01 00:00:00'
        UNION ALL SELECT 'e3', 's3', TIMESTAMP '2023-02-01 00:00:00'
        UNION ALL SELECT 'e1', 's4', CAST(NULL AS TIMESTAMP)
        UNION ALL SELECT 'e1', 's5', TIMESTAMP '2024-01-01 00:00:00'
    """)
    train, future = split_pairs(rows, 2023)
    observed = {(r.entity_id, r.supplier_id): r.interaction_count for r in train.collect()}
    assert observed == {("e1", "s1"): 2, ("e2", "s2"): 1}
    future_rows = {(r.entity_id, r.supplier_id): r for r in future.collect()}
    assert len(future_rows) == 5
    assert future_rows[("e1", "s1")].seen
    assert future_rows[("e1", "s2")].eligible_positive
    assert not future_rows[("e1", "s3")].supplier_known
    assert not future_rows[("e3", "s1")].entity_known
    assert not future_rows[("e3", "s3")].eligible_positive
