import hashlib
import json
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from src.features.build_part1 import (
    build_features,
    build_knn,
    build_matrix,
    directory_fingerprint,
    validate_inputs,
    windowed,
)
from src.processing.build_fact_award import configure_pyspark_python
from src.processing.build_fact_award_item import configure_windows_hadoop


@pytest.fixture(scope="module")
def spark():
    hadoop = configure_windows_hadoop()
    configure_pyspark_python()
    builder = SparkSession.builder.master("local[2]").appName("test-part1")
    if hadoop:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop / "bin"))
    session = builder.config("spark.sql.shuffle.partitions", "2").getOrCreate()
    yield session
    session.stop()


def test_matrix_sums_counts_across_currencies_and_filters_year(spark):
    frame = spark.sql("""
        SELECT 'e1' entity_id, 's1' supplier_id, 2023 award_year,
               'PEN' award_currency, 2 award_count
        UNION ALL SELECT 'e1', 's1', 2023, 'USD', 3
        UNION ALL SELECT 'e1', 's2', 2024, 'PEN', 1
        UNION ALL SELECT 'e1', 's1', 2022, 'PEN', 9
    """)
    matrix, entities, suppliers = build_matrix(windowed(frame, 2023, 2024))
    assert {r.supplier_id: r.interaction_count for r in matrix.collect()} == {"s1": 5, "s2": 1}
    assert [(r.entity_id, r.entity_index) for r in entities.collect()] == [("e1", 0)]
    assert sorted(r.supplier_index for r in suppliers.collect()) == [0, 1]


def test_features_knn_ties_and_pair_limit(spark):
    frame = spark.sql("""
        SELECT 'a' entity_id, 'goods' procurement_category, 2 award_count
        UNION ALL SELECT 'b', 'goods', 2
        UNION ALL SELECT 'c', 'goods', 2
    """)
    features, categories, params = build_features(frame)
    assert categories == ["goods"]
    assert all(p["std"] == 0 for p in params)
    assert all(r.vector_scaled == [0.0, 0.0] for r in features.collect())
    edges, pairs = build_knn(features, 1, 6)
    assert pairs == 6
    assert {(r.src, r.dst, r.distance) for r in edges.collect()} == {
        ("a", "b", 0.0),
        ("b", "a", 0.0),
        ("c", "a", 0.0),
    }
    with pytest.raises(ValueError, match="límite"):
        build_knn(features, 1, 5)


def test_lineage_detects_changes_and_incompatible_runs(tmp_path: Path):
    paths = [tmp_path / "supplier", tmp_path / "category"]
    for path in paths:
        path.mkdir()
        (path / "_SUCCESS").touch()
        (path / "_metadata.json").write_text(json.dumps({"run_id": "a"}))
    first = directory_fingerprint(paths[0])
    (paths[0] / "data.parquet").write_bytes(b"changed")
    assert first != directory_fingerprint(paths[0])
    assert validate_inputs(*paths, tmp_path / "result", False)["run_id"] == "a"
    (paths[1] / "_metadata.json").write_text(json.dumps({"run_id": "b"}))
    with pytest.raises(ValueError, match="misma corrida"):
        validate_inputs(*paths, tmp_path / "result", False)


def test_fingerprint_uses_portable_case_sensitive_path_order(tmp_path: Path):
    (tmp_path / "_SUCCESS").write_bytes(b"")
    (tmp_path / "_metadata.json").write_bytes(b"{}")
    expected = hashlib.sha256()
    for name, content in [("_SUCCESS", b""), ("_metadata.json", b"{}")]:
        name_bytes = name.encode("utf-8")
        expected.update(len(name_bytes).to_bytes(8, "big"))
        expected.update(name_bytes)
        expected.update(hashlib.sha256(content).digest())
    assert directory_fingerprint(tmp_path) == expected.hexdigest()
