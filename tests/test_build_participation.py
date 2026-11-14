import json
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import configure_windows_hadoop
from src.processing.build_participation import (
    build_dim_buyer,
    build_fact_tender,
    build_fact_tenderer,
    select_eligible_releases,
    tenderer_name_conflicts,
)


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.master("local[2]")
        .appName("test-build-participation")
        .config("spark.sql.session.timeZone", "America/Lima")
    )
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


@pytest.fixture
def releases(spark: SparkSession, tmp_path: Path):
    rows = [
        {
            "source_year": 2023,
            "ocid": "p1",
            "id": "r1",
            "date": "2023-05-02T00:00:00Z",
            "publishedDate": "2023-05-03T00:00:00Z",
            "buyer": {"id": "b1", "name": "Comprador Uno"},
            "tender": {
                "id": "t1", "title": "Compra", "description": "Detalle",
                "mainProcurementCategory": "goods", "procurementMethod": "open",
                "procurementMethodDetails": "Licitación", "numberOfTenderers": 3,
                "items": [
                    {"classification": {"scheme": "CUBSO", "id": "8110150000000000"}},
                    {"classification": {"scheme": "CUBSO", "id": "7210000000000000"}},
                ],
                "tenderers": [
                    {"id": "x1", "name": "Postor Uno"}, {"id": "x1", "name": "Postor Uno"},
                    {"id": "x2", "name": "Postor Dos"}, {"name": "Sin id"},
                ],
            },
            "awards": [{"id": "a1", "date": "2023-05-02T00:00:00Z"}],
            "parties": [{
                "id": "b1", "name": "Comprador Uno",
                "address": {
                    "department": "LIMA", "region": "LIMA", "locality": "MIRAFLORES",
                    "streetAddress": "Calle 1", "postalCode": "15074",
                },
                "identifier": {"scheme": "PE-CONSUCODE", "id": "b1"},
                "additionalIdentifiers": [{"scheme": "PE-RUC", "id": "20123456789"}],
            }],
        },
        {
            "source_year": 2023, "ocid": "p2", "id": "r2",
            "buyer": {"id": "b2", "name": "Fuera de ventana"},
            "tender": {"tenderers": [{"id": "x3", "name": "Postor Tres"}]},
            "awards": [{"id": "a2", "date": "2022-12-31T00:00:00Z"}], "parties": [],
        },
    ]
    source = tmp_path / "releases.json"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return spark.read.json(str(source))


def test_process_participant_and_buyer_grains(releases) -> None:
    eligible = select_eligible_releases(releases, 2023, 2024)
    tenders = build_fact_tender(eligible)
    tenderers = build_fact_tenderer(eligible)
    buyers = build_dim_buyer(eligible)

    tender = tenders.first().asDict()
    assert tenders.count() == 1
    assert tender["process_ocid"] == "p1"
    assert tender["eligible_award_count"] == 1
    assert tender["tenderer_list_count"] == 4
    assert tender["cubso_segment"] == "72"
    assert tenderers.select("process_ocid", "participant_id").distinct().count() == 2
    assert tenderers.where("participant_id = 'x1'").first()["duplicate_rows_in_source"] == 2
    buyer = buyers.first().asDict()
    assert buyer["buyer_id"] == "b1"
    assert buyer["department"] == "LIMA"
    assert buyer["buyer_ruc"] == "20123456789"


def test_conflicting_participant_names_are_detected(spark: SparkSession, tmp_path: Path) -> None:
    source = tmp_path / "conflict.json"
    source.write_text(json.dumps({
        "ocid": "p1", "buyer": {"id": "b1"},
        "tender": {
            "tenderers": [
                {"id": "x1", "name": "Nombre A"},
                {"id": "x1", "name": "Nombre B"},
            ]
        },
        "awards": [{"id": "a1", "date": "2023-01-02T00:00:00Z"}],
    }), encoding="utf-8")
    releases = spark.read.json(str(source))
    eligible = select_eligible_releases(releases, 2023, 2024)
    conflicts = tenderer_name_conflicts(eligible).collect()
    assert [(row["process_ocid"], row["participant_id"]) for row in conflicts] == [("p1", "x1")]
