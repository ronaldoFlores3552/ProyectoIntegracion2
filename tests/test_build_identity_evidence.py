import json
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from scripts.download_data import sha256_file
from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import configure_windows_hadoop
from src.processing.build_identity_evidence import (
    build_candidate_tables,
    build_reference_identifiers,
    build_reference_matches,
    extract_identifiers,
    verify_sources,
)


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = SparkSession.builder.master("local[2]").appName("test-identity-evidence")
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    session = builder.getOrCreate()
    yield session
    session.stop()


@pytest.fixture()
def parties(spark: SparkSession):
    return spark.sql(
        """
        SELECT 2023 AS source_year, 'p1' AS process_ocid, 'r1' AS release_id,
               0 AS party_position, 's1' AS party_id, 'Uno' AS party_name,
               ARRAY('supplier') AS party_roles,
               NAMED_STRUCT('scheme', 'RUC', 'id', '100', 'legalName', 'Uno') AS identifier,
               ARRAY(NAMED_STRUCT('scheme', 'RUC', 'id', '101', 'legalName', 'Uno'))
                   AS additional_identifiers
        UNION ALL
        SELECT 2023, 'p1', 'r1', 1, 's2', 'Dos', ARRAY('supplier'),
               NAMED_STRUCT('scheme', 'RUC', 'id', '100', 'legalName', 'Dos'),
               CAST(ARRAY() AS ARRAY<STRUCT<scheme: STRING, id: STRING, legalName: STRING>>)
        UNION ALL
        SELECT 2023, 'p1', 'r1', 2, 'b1', 'Comprador', ARRAY('buyer'),
               NAMED_STRUCT('scheme', 'OTRO', 'id', '100', 'legalName', 'Comprador'),
               CAST(ARRAY() AS ARRAY<STRUCT<scheme: STRING, id: STRING, legalName: STRING>>)
        """
    )


@pytest.fixture()
def references(spark: SparkSession):
    return spark.sql(
        """
        SELECT 2023 AS source_year, 'p1' AS process_ocid, 'r1' AS release_id,
               'supplier' AS reference_role, 's1' AS reference_id
        UNION ALL SELECT 2023, 'p1', 'r1', 'supplier', 's2'
        UNION ALL SELECT 2023, 'p1', 'r1', 'buyer', 'b1'
        UNION ALL SELECT 2023, 'p1', 'r2', 'supplier', 's1'
        """
    )


def test_identifier_sources_do_not_multiply_each_other(parties) -> None:
    identifiers = extract_identifiers(parties).collect()
    assert len(identifiers) == 4
    assert sum(row["identifier_source"] == "additionalIdentifiers" for row in identifiers) == 1
    assert any(
        row["identifier_id"] == "101" and row["identifier_position"] == 0 for row in identifiers
    )


def test_matching_requires_same_release_and_reports_candidates(parties, references) -> None:
    matches = build_reference_matches(references, parties).collect()
    status = {(row["release_id"], row["reference_id"]): row["match_status"] for row in matches}
    assert status[("r1", "s1")] == "matched_one_party"
    assert status[("r2", "s1")] == "unmatched"

    linked = build_reference_identifiers(references, extract_identifiers(parties))
    shared, variants = build_candidate_tables(linked)
    shared_rows = shared.collect()
    variant_rows = variants.collect()
    assert len(shared_rows) == 1
    assert shared_rows[0]["reference_role"] == "supplier"
    assert shared_rows[0]["identifier_scheme"] == "RUC"
    assert shared_rows[0]["distinct_reference_ids"] == 2
    assert len(variant_rows) == 1
    assert variant_rows[0]["reference_id"] == "s1"
    assert variant_rows[0]["distinct_identifier_ids"] == 2


def test_ambiguous_party_and_missing_reference_are_reported(parties, references, spark) -> None:
    repeated_parties = parties.unionByName(parties.where("party_id = 's1'"))
    missing = spark.sql(
        """
        SELECT 2023 AS source_year, 'p1' AS process_ocid, 'r1' AS release_id,
               'buyer' AS reference_role, CAST(NULL AS STRING) AS reference_id
        """
    )
    matches = build_reference_matches(references.unionByName(missing), repeated_parties).collect()
    statuses = {(row["reference_id"], row["release_id"]): row["match_status"] for row in matches}
    assert statuses[("s1", "r1")] == "multiple_party_records"
    assert statuses[(None, "r1")] == "missing_reference_id"


def test_manifest_checks_actual_sha256(tmp_path: Path) -> None:
    source = tmp_path / "2023.jsonl.gz"
    source.write_bytes(b"test-data")
    manifest = {
        "downloads": [{"year": "2023", "filename": source.name, "sha256": sha256_file(source)}]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_sources(tmp_path, ["2023"])[0]["sha256"] == sha256_file(source)

    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_sources(tmp_path, ["2023"])
