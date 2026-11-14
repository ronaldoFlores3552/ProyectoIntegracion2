import pytest
from pyspark.sql import SparkSession

from src.features.build_market_p1 import (
    build_buyer_segment_method,
    select_awards_in_window,
    select_p1_processes,
)
from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import configure_windows_hadoop


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = SparkSession.builder.master("local[2]").appName("test-build-market-p1")
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


def test_p1_uses_the_same_competitive_processes_for_both_measures(spark: SparkSession) -> None:
    tenders = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'b1' AS buyer_id, '72' AS cubso_segment,
               'open' AS procurement_method, 'Licitación Pública' AS procurement_method_details,
               5 AS tenderer_list_count, 5 AS number_of_tenderers
        UNION ALL
        SELECT 'p2', 'b1', '72', 'open', 'Licitación Pública', 3, 3
        UNION ALL
        SELECT 'p3', 'b1', '72', 'direct', 'Contratación Directa', 1, 1
        UNION ALL
        SELECT 'p4', 'b1', NULL, 'open', 'Licitación Pública', 9, 9
        """
    )
    awards = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'a1' AS award_id, 's1' AS supplier_id, 2023 AS award_year
        UNION ALL SELECT 'p2', 'a2', 's1', 2024
        UNION ALL SELECT 'p2', 'a3', 's2', 2024
        UNION ALL SELECT 'p2', 'a_fuera', 's3', 2022
        UNION ALL SELECT 'p3', 'a4', 's3', 2024
        UNION ALL SELECT 'p4', 'a5', 's4', 2024
        """
    )
    tenderers = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'x1' AS participant_id
        UNION ALL SELECT 'p1', 'x2'
        UNION ALL SELECT 'p2', 'x1'
        UNION ALL SELECT 'p2', 'x3'
        """
    )
    buyers = spark.sql("SELECT 'b1' AS buyer_id, 'LIMA' AS department")

    processes = select_p1_processes(tenders, awards, tenderers, buyers, 2023, 2024)
    eligible_awards = select_awards_in_window(awards, 2023, 2024)
    result = build_buyer_segment_method(processes, eligible_awards).first().asDict()

    assert processes.select("process_ocid").distinct().count() == 2
    assert result["process_count"] == 2
    assert result["award_count"] == 3
    assert result["distinct_suppliers"] == 2
    assert result["top_supplier_id"] == "s1"
    assert result["top_supplier_share"] == pytest.approx(2 / 3)
    assert result["hhi"] == pytest.approx((2 / 3) ** 2 + (1 / 3) ** 2)
    assert result["reported_participants_median"] == 3.0
