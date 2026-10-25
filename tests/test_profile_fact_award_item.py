import pytest
from pyspark.sql import SparkSession

from src.processing.build_fact_award_item import configure_windows_hadoop
from src.quality.profile_fact_award_item import (
    candidate_duplicate_groups,
    collect_profile,
    configure_pyspark_python,
    profile_by_year,
)


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = SparkSession.builder.master("local[2]").appName("test-quality-profile")
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


@pytest.fixture()
def fact_sample(spark: SparkSession):
    return spark.sql(
        """
        SELECT 2023 AS source_year, 'p1' AS process_ocid, 'a1' AS award_id,
               's1' AS supplier_id, 'i1' AS item_id, 'e1' AS entity_id,
               'pe1' AS procuring_entity_id,
               DATE '2023-01-01' AS award_date, CAST(10.00 AS DECIMAL(20, 2)) AS award_amount,
               'PEN' AS award_currency, 'goods' AS procurement_category,
               'open' AS procurement_method, '1' AS item_classification_id
        UNION ALL
        SELECT 2023, 'p1', 'a1', 's1', 'i1', 'e1', 'pe1', DATE '2023-01-01',
               CAST(10.00 AS DECIMAL(20, 2)), 'PEN', 'goods', 'open', '1'
        UNION ALL
        SELECT 2023, 'p1', 'a1', 's1', 'i2', 'e1', 'pe1', DATE '2023-01-01',
               CAST(10.00 AS DECIMAL(20, 2)), 'PEN', 'goods', 'open', '2'
        UNION ALL
        SELECT 2024, 'p2', 'a1', 's2', CAST(NULL AS STRING), CAST(NULL AS STRING),
               CAST(NULL AS STRING),
               DATE '2024-02-01', CAST(-1.00 AS DECIMAL(20, 2)), 'USD',
               CAST(NULL AS STRING), 'direct', CAST(NULL AS STRING)
        """
    )


def test_collect_profile_reports_repetition_without_summing_awards(fact_sample, tmp_path) -> None:
    profile = collect_profile(fact_sample, tmp_path)

    assert profile["global_metrics"]["rows"] == 4
    assert profile["global_metrics"]["distinct_awards"] == 2
    assert profile["global_metrics"]["distinct_award_suppliers"] == 2
    assert profile["global_metrics"]["award_amount_positive"] == 3
    assert profile["global_metrics"]["award_amount_negative"] == 1
    assert profile["global_metrics"]["entity_id_missing"] == 1
    assert profile["global_metrics"]["procuring_entity_id_missing"] == 1
    assert profile["global_metrics"]["buyer_procuring_entity_id_mismatch"] == 3
    assert profile["candidate_key_diagnostics"]["candidate_duplicate_groups"] == 1
    assert profile["candidate_key_diagnostics"]["candidate_duplicate_excess_rows"] == 1
    assert profile["candidate_key_diagnostics"]["exact_duplicate_excess_rows"] == 1
    assert "no lo suma" in profile["interpretation"]["award_amount_is_not_summed"]


def test_profile_by_year_and_duplicate_groups_keep_the_grain(fact_sample) -> None:
    yearly = {row["source_year"]: row.asDict() for row in profile_by_year(fact_sample).collect()}
    duplicates = candidate_duplicate_groups(fact_sample).collect()

    assert yearly[2023]["rows"] == 3
    assert yearly[2023]["distinct_awards"] == 1
    assert yearly[2024]["rows_missing_item_id"] == 1
    assert len(duplicates) == 1
    assert duplicates[0]["count"] == 2

