import pytest
from pyspark.sql import SparkSession

from src.processing.build_fact_award import (
    award_level_conflicts,
    build_fact_award,
    configure_pyspark_python,
)
from src.processing.build_fact_award_item import configure_windows_hadoop


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = SparkSession.builder.master("local[2]").appName("test-build-fact-award")
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


def test_build_fact_award_collapses_item_level_repetition(spark: SparkSession) -> None:
    fact_award_item = spark.sql(
        """
        SELECT 2023 AS source_year, 'p1' AS process_ocid, 'r1' AS release_id,
               TIMESTAMP '2023-01-01 00:00:00' AS release_date,
               TIMESTAMP '2023-01-02 00:00:00' AS published_date, 'e1' AS entity_id,
               'Entidad' AS entity_name, 'e1' AS procuring_entity_id,
               'Entidad' AS procuring_entity_name, 't1' AS tender_id, 'Compra' AS tender_title,
               'Detalle' AS tender_description, 'goods' AS procurement_category,
               'open' AS procurement_method, 'Pública' AS procurement_method_details,
               2 AS number_of_tenderers, 'a1' AS award_id,
               TIMESTAMP '2023-01-03 00:00:00' AS award_date,
               CAST(100.00 AS DECIMAL(20, 2)) AS award_amount, 'PEN' AS award_currency
        UNION ALL
        SELECT 2023, 'p1', 'r1', TIMESTAMP '2023-01-01 00:00:00',
               TIMESTAMP '2023-01-02 00:00:00', 'e1', 'Entidad', 'e1', 'Entidad', 't1',
               'Compra', 'Detalle', 'goods', 'open', 'Pública', 2, 'a1',
               TIMESTAMP '2023-01-03 00:00:00', CAST(100.00 AS DECIMAL(20, 2)), 'PEN'
        """
    )

    fact_award = build_fact_award(fact_award_item)

    assert fact_award.count() == 1
    assert fact_award.first()["award_amount"] == 100
    assert award_level_conflicts(fact_award_item).count() == 0


def test_award_level_conflicts_detects_inconsistent_award_amount(spark: SparkSession) -> None:
    fact_award_item = spark.sql(
        """
        SELECT 2023 AS source_year, 'p1' AS process_ocid, 'r1' AS release_id,
               TIMESTAMP '2023-01-01 00:00:00' AS release_date,
               TIMESTAMP '2023-01-02 00:00:00' AS published_date, 'e1' AS entity_id,
               'Entidad' AS entity_name, 'e1' AS procuring_entity_id,
               'Entidad' AS procuring_entity_name, 't1' AS tender_id, 'Compra' AS tender_title,
               'Detalle' AS tender_description, 'goods' AS procurement_category,
               'open' AS procurement_method, 'Pública' AS procurement_method_details,
               2 AS number_of_tenderers, 'a1' AS award_id,
               TIMESTAMP '2023-01-03 00:00:00' AS award_date,
               CAST(100.00 AS DECIMAL(20, 2)) AS award_amount, 'PEN' AS award_currency
        UNION ALL
        SELECT 2023, 'p1', 'r1', TIMESTAMP '2023-01-01 00:00:00',
               TIMESTAMP '2023-01-02 00:00:00', 'e1', 'Entidad', 'e1', 'Entidad', 't1',
               'Compra', 'Detalle', 'goods', 'open', 'Pública', 2, 'a1',
               TIMESTAMP '2023-01-03 00:00:00', CAST(120.00 AS DECIMAL(20, 2)), 'PEN'
        """
    )

    conflicts = award_level_conflicts(fact_award_item).collect()

    assert len(conflicts) == 1
    assert conflicts[0]["process_ocid"] == "p1"
    assert conflicts[0]["award_id"] == "a1"
