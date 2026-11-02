import pytest
from pyspark.sql import SparkSession

from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import configure_windows_hadoop
from src.processing.build_fact_award_supplier import (
    build_fact_award_supplier,
    supplier_name_conflicts,
)


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = SparkSession.builder.master("local[2]").appName("test-build-fact-award-supplier")
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


@pytest.fixture()
def fact_award(spark: SparkSession):
    return spark.sql(
        """
        SELECT 2023 AS source_year, 'p1' AS process_ocid, 'a1' AS award_id,
               'r1' AS release_id, 'e1' AS entity_id, 'Entidad' AS entity_name,
               't1' AS tender_id, 'goods' AS procurement_category,
               'open' AS procurement_method, TIMESTAMP '2023-01-03 00:00:00' AS award_date,
               CAST(100.00 AS DECIMAL(20, 2)) AS award_amount, 'PEN' AS award_currency
        """
    )


def test_build_fact_award_supplier_collapses_repeated_items(
    fact_award, spark: SparkSession
) -> None:
    fact_award_item = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'a1' AS award_id, 's1' AS supplier_id,
               'Proveedor Uno' AS supplier_name
        UNION ALL
        SELECT 'p1', 'a1', 's1', 'Proveedor Uno'
        """
    )

    result = build_fact_award_supplier(fact_award, fact_award_item).first()

    assert result["supplier_id"] == "s1"
    assert result["supplier_count_per_award"] == 1
    assert result["award_amount_total"] == 100
    assert result["award_amount_single_supplier"] == 100
    assert result["award_year"] == 2023


def test_multi_supplier_award_never_allocates_total_amount(fact_award, spark: SparkSession) -> None:
    fact_award_item = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'a1' AS award_id, 's1' AS supplier_id,
               'Proveedor Uno' AS supplier_name
        UNION ALL
        SELECT 'p1', 'a1', 's2', 'Proveedor Dos'
        """
    )

    results = build_fact_award_supplier(fact_award, fact_award_item).collect()

    assert len(results) == 2
    assert {row["supplier_count_per_award"] for row in results} == {2}
    assert all(row["award_amount_total"] == 100 for row in results)
    assert all(row["award_amount_single_supplier"] is None for row in results)


def test_supplier_name_conflicts_are_reported(spark: SparkSession) -> None:
    fact_award_item = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'a1' AS award_id, 's1' AS supplier_id,
               'Proveedor Uno' AS supplier_name
        UNION ALL
        SELECT 'p1', 'a1', 's1', 'Proveedor Distinto'
        """
    )

    conflicts = supplier_name_conflicts(fact_award_item).collect()

    assert len(conflicts) == 1
    assert conflicts[0]["supplier_id"] == "s1"
