import pytest
from pyspark.sql import SparkSession

from src.features.build_market_p2 import (
    build_award_edges,
    build_coparticipation,
    build_participation_edges,
)
from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import configure_windows_hadoop


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = SparkSession.builder.master("local[2]").appName("test-build-market-p2")
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


def test_builds_bipartite_edges_at_the_declared_grain(spark: SparkSession) -> None:
    tenders = spark.sql("SELECT 'p1' AS process_ocid, 'b1' AS buyer_id")
    awards = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'a1' AS award_id, 's1' AS supplier_id,
               'PEN' AS award_currency, 20.0 AS award_amount_single_supplier
        UNION ALL SELECT 'p1', 'a2', 's1', 'PEN', 30.0
        UNION ALL SELECT 'p1', 'a3', 's2', 'USD', 5.0
        """
    )
    tenderers = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'b1' AS buyer_id, 'x1' AS participant_id
        UNION ALL SELECT 'p1', 'b1', 'x1'
        UNION ALL SELECT 'p2', 'b1', 'x1'
        UNION ALL SELECT 'p2', 'b1', 'x2'
        """
    )

    award_rows = {
        row["supplier_id"]: row.asDict() for row in build_award_edges(tenders, awards).collect()
    }
    participation = build_participation_edges(tenderers).orderBy("participant_id").collect()

    assert award_rows["s1"]["award_count"] == 2
    assert award_rows["s1"]["pen_amount_total"] == 50
    assert award_rows["s2"]["pen_amount_total"] is None
    assert [(row["participant_id"], row["process_count"]) for row in participation] == [
        ("x1", 2),
        ("x2", 1),
    ]


def test_coparticipation_filters_recurrence_orders_pairs_and_normalizes(
    spark: SparkSession,
) -> None:
    tenderers = spark.sql(
        """
        SELECT 'p1' AS process_ocid, 'b1' AS buyer_id, 'x1' AS participant_id
        UNION ALL SELECT 'p1', 'b1', 'x2'
        UNION ALL SELECT 'p1', 'b1', 'x3'
        UNION ALL SELECT 'p2', 'b1', 'x1'
        UNION ALL SELECT 'p2', 'b1', 'x2'
        UNION ALL SELECT 'p3', 'b2', 'x1'
        UNION ALL SELECT 'p3', 'b2', 'x2'
        UNION ALL SELECT 'p4', 'b2', 'x3'
        """
    )

    coverage, edges = build_coparticipation(tenderers, min_recurrent_processes=2)
    result = {
        tuple(row[key] for key in ("participant_left", "participant_right")): row.asDict()
        for row in edges.collect()
    }
    p1 = coverage.where("process_ocid = 'p1'").first().asDict()

    assert p1["reported_participant_count"] == 3
    assert p1["recurrent_participant_count"] == 3
    assert p1["is_projectable"] is True
    assert result[("x1", "x2")]["shared_process_count"] == 3
    assert result[("x1", "x2")]["newman_weight"] == pytest.approx(2.5)
    assert result[("x1", "x3")]["shared_process_count"] == 1
    assert result[("x1", "x3")]["newman_weight"] == pytest.approx(0.5)

    capped_coverage, capped_edges = build_coparticipation(
        tenderers, min_recurrent_processes=2, max_recurrent_participants=2
    )
    capped_p1 = capped_coverage.where("process_ocid = 'p1'").first().asDict()

    assert capped_p1["is_projectable"] is False
    assert capped_edges.where("participant_left = 'x1' AND participant_right = 'x2'").first()[
        "newman_weight"
    ] == pytest.approx(2.0)
