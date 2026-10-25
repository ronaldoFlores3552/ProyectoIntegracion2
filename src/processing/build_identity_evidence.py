"""Extrae evidencia OCDS de identidad sin fusionar identificadores."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, StringType, StructField, StructType

from scripts.download_data import parse_years, read_manifest, sha256_file
from src.processing.build_fact_award import configure_pyspark_python, missing_or_blank
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    input_paths,
    publish_output,
    staging_dir,
)
from src.quality.profile_fact_award_item import write_json_atomically

IDENTIFIER_SCHEMA = StructType(
    [StructField(name, StringType()) for name in ("scheme", "id", "legalName")]
)
RELEASE_SCHEMA = StructType(
    [
        StructField("ocid", StringType()),
        StructField("id", StringType()),
        StructField(
            "parties",
            ArrayType(
                StructType(
                    [
                        StructField("id", StringType()),
                        StructField("name", StringType()),
                        StructField("roles", ArrayType(StringType())),
                        StructField("identifier", IDENTIFIER_SCHEMA),
                        StructField("additionalIdentifiers", ArrayType(IDENTIFIER_SCHEMA)),
                    ]
                )
            ),
        ),
    ]
)
CONTEXT = ("source_year", "process_ocid", "release_id")
REFERENCE_KEY = (*CONTEXT, "reference_role", "reference_id")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--suppliers-dir", type=Path, default=Path("data/processed/fact_award_supplier")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/processed/identity_evidence")
    )
    parser.add_argument("--years", nargs="+", required=True)
    parser.add_argument("--master", default="local[*]")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def verify_sources(input_dir: Path, years: list[str]) -> list[dict[str, str]]:
    """Validate the files against the download manifest before reading them."""
    paths = input_paths(input_dir, years)
    manifest_path = input_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Falta el manifiesto de descarga: {manifest_path}")
    records = read_manifest(manifest_path)["downloads"]
    result = []
    for year, path_string in zip(years, paths, strict=True):
        path = Path(path_string)
        entries = [record for record in records if str(record.get("year")) == year]
        if len(entries) != 1 or entries[0].get("filename") != path.name:
            raise ValueError(f"El manifiesto no contiene una entrada única para {path.name}.")
        actual_hash = sha256_file(path)
        if actual_hash != entries[0].get("sha256"):
            raise ValueError(f"El SHA-256 de {path.name} no coincide con el manifiesto.")
        result.append({"year": year, "filename": path.name, "sha256": actual_hash})
    return result


def extract_parties(releases: DataFrame) -> DataFrame:
    return (
        releases.select(*CONTEXT, F.posexplode("parties").alias("party_position", "party"))
        .select(
            *CONTEXT,
            "party_position",
            F.col("party.id").alias("party_id"),
            F.col("party.name").alias("party_name"),
            F.col("party.roles").alias("party_roles"),
            F.col("party.identifier").alias("identifier"),
            F.col("party.additionalIdentifiers").alias("additional_identifiers"),
        )
    )


def extract_identifiers(parties: DataFrame) -> DataFrame:
    common = [*CONTEXT, "party_position", "party_id", "party_name", "party_roles"]
    primary = parties.where(F.col("identifier").isNotNull()).select(
        *common,
        F.lit("identifier").alias("identifier_source"),
        F.lit(None).cast("int").alias("identifier_position"),
        F.col("identifier.scheme").alias("identifier_scheme"),
        F.col("identifier.id").alias("identifier_id"),
        F.col("identifier.legalName").alias("identifier_legal_name"),
    )
    additional = (
        parties.select(
            *common,
            F.posexplode("additional_identifiers").alias("identifier_position", "identifier"),
        )
        .where(F.col("identifier").isNotNull())
        .select(
            *common,
            F.lit("additionalIdentifiers").alias("identifier_source"),
            "identifier_position",
            F.col("identifier.scheme").alias("identifier_scheme"),
            F.col("identifier.id").alias("identifier_id"),
            F.col("identifier.legalName").alias("identifier_legal_name"),
        )
    )
    return primary.unionByName(additional)


def extract_references(fact: DataFrame, years: list[str]) -> DataFrame:
    filtered = fact.where(F.col("source_year").isin([int(year) for year in years]))
    supplier = filtered.select(
        *CONTEXT,
        F.lit("supplier").alias("reference_role"),
        F.col("supplier_id").alias("reference_id"),
    )
    buyer = filtered.select(
        *CONTEXT, F.lit("buyer").alias("reference_role"), F.col("entity_id").alias("reference_id")
    )
    return supplier.unionByName(buyer).dropDuplicates()


def build_reference_matches(references: DataFrame, parties: DataFrame) -> DataFrame:
    party_counts = (
        parties.where(~missing_or_blank("party_id"))
        .groupBy(*CONTEXT, "party_id")
        .agg(F.count("*").alias("matched_party_records"))
        .withColumnRenamed("party_id", "reference_id")
    )
    return (
        references.join(party_counts, [*CONTEXT, "reference_id"], "left")
        .fillna({"matched_party_records": 0})
        .withColumn(
            "match_status",
            F.when(missing_or_blank("reference_id"), F.lit("missing_reference_id"))
            .when(F.col("matched_party_records") == 0, F.lit("unmatched"))
            .when(F.col("matched_party_records") > 1, F.lit("multiple_party_records"))
            .otherwise(F.lit("matched_one_party")),
        )
    )


def build_reference_identifiers(references: DataFrame, identifiers: DataFrame) -> DataFrame:
    return (
        references.where(~missing_or_blank("reference_id"))
        .join(
            identifiers.withColumnRenamed("party_id", "reference_id"),
            [*CONTEXT, "reference_id"],
            "inner",
        )
    )


def build_candidate_tables(reference_identifiers: DataFrame) -> tuple[DataFrame, DataFrame]:
    valid = reference_identifiers.where(
        ~missing_or_blank("identifier_scheme") & ~missing_or_blank("identifier_id")
    )
    shared = (
        valid.groupBy("reference_role", "identifier_scheme", "identifier_id")
        .agg(F.countDistinct("reference_id").alias("distinct_reference_ids"))
        .where(F.col("distinct_reference_ids") > 1)
    )
    variants = (
        valid.groupBy("reference_role", "reference_id", "identifier_scheme")
        .agg(F.countDistinct("identifier_id").alias("distinct_identifier_ids"))
        .where(F.col("distinct_identifier_ids") > 1)
    )
    return shared, variants


def _validate_paths(raw: Path, suppliers: Path, output: Path, overwrite: bool) -> None:
    if not (suppliers / "_SUCCESS").is_file():
        raise FileNotFoundError(f"Falta la tabla publicada con _SUCCESS: {suppliers}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"La salida ya existe: {output}. Use --overwrite para regenerarla.")
    for target in (output, staging_dir(output), output.with_name(f"{output.name}.previous")):
        for source in (raw, suppliers):
            if target == source or target in source.parents or source in target.parents:
                raise ValueError(f"Ruta de salida o temporal se solapa con una entrada: {target}")


def run() -> None:
    args = parse_args()
    years = parse_years(args.years)
    raw, suppliers, output = (
        args.input_dir.resolve(), args.suppliers_dir.resolve(), args.output_dir.resolve()
    )
    _validate_paths(raw, suppliers, output, args.overwrite)
    sources = verify_sources(raw, years)
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-identity-evidence")
        .master(args.master)
        .config("spark.sql.session.timeZone", "America/Lima")
        .config("spark.sql.shuffle.partitions", "8")
    )
    if hadoop_home:
        builder = builder.config("spark.driver.extraLibraryPath", str(hadoop_home / "bin"))
    spark = builder.getOrCreate()
    try:
        if hadoop_home:
            native_loader = spark.sparkContext._jvm.org.apache.hadoop.util.NativeCodeLoader
            if not native_loader.isNativeCodeLoaded():
                raise RuntimeError(
                    "La JVM no cargó hadoop.dll. Ejecute: "
                    "python scripts/setup_windows_hadoop.py --check"
                )
        releases = spark.read.schema(RELEASE_SCHEMA).json(input_paths(raw, years)).select(
            F.regexp_extract(F.input_file_name(), r"([12][0-9]{3})\.jsonl\.gz", 1)
            .cast("int")
            .alias("source_year"),
            F.col("ocid").alias("process_ocid"),
            F.col("id").alias("release_id"),
            "parties",
        )
        parties = extract_parties(releases).cache()
        identifiers = extract_identifiers(parties).cache()
        supplier_fact = spark.read.parquet(str(suppliers))
        available_years = {
            str(row["source_year"])
            for row in supplier_fact.select("source_year").distinct().collect()
            if row["source_year"] is not None
        }
        if set(years) - available_years:
            raise ValueError(
                "fact_award_supplier no contiene todos los años solicitados: "
                f"{sorted(set(years) - available_years)}"
            )
        references = extract_references(supplier_fact, years).cache()
        matches = build_reference_matches(references, parties).cache()
        referenced_identifiers = build_reference_identifiers(references, identifiers).cache()
        shared, variants = build_candidate_tables(referenced_identifiers)

        stage = staging_dir(output)
        shutil.rmtree(stage, ignore_errors=True)
        tables = {
            "party_identifiers": identifiers,
            "reference_matches": matches,
            "reference_identifiers": referenced_identifiers,
            "candidate_shared_identifiers": shared,
            "candidate_identifier_variants": variants,
        }
        for name, frame in tables.items():
            frame.write.mode("overwrite").parquet(str(stage / name))
            if not (stage / name / "_SUCCESS").is_file():
                raise RuntimeError(f"La tabla {name} no dejó _SUCCESS; no se publica el conjunto.")

        status = [
            row.asDict()
            for row in matches.groupBy("reference_role", "match_status").count().collect()
        ]
        covered_references = (
            referenced_identifiers.where(
                ~missing_or_blank("identifier_scheme") & ~missing_or_blank("identifier_id")
            )
            .select(*REFERENCE_KEY)
            .dropDuplicates()
        )
        coverage = (
            covered_references
            .groupBy("reference_role")
            .count()
            .collect()
        )
        missing_coverage = (
            references.join(covered_references, list(REFERENCE_KEY), "left_anti")
            .groupBy("reference_role")
            .count()
            .collect()
        )
        identifier_quality = identifiers.agg(
            F.count("*").alias("rows"),
            F.count(F.when(missing_or_blank("party_id"), 1)).alias("missing_party_id"),
            F.count(F.when(missing_or_blank("identifier_scheme"), 1)).alias("missing_scheme"),
            F.count(F.when(missing_or_blank("identifier_id"), 1)).alias("missing_identifier_id"),
        ).first().asDict()
        metadata = {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "sources": sources,
            "fact_award_supplier": str(suppliers),
            "years": years,
            "reference_grain": list(REFERENCE_KEY),
            "references_by_role_and_status": status,
            "references_with_complete_identifier_by_role": [row.asDict() for row in coverage],
            "references_without_complete_identifier_by_role": [
                row.asDict() for row in missing_coverage
            ],
            "party_identifier_rows": identifier_quality["rows"],
            "party_identifier_quality": identifier_quality,
            "reference_identifier_rows": referenced_identifiers.count(),
            "candidate_shared_identifier_groups": shared.count(),
            "candidate_identifier_variant_groups": variants.count(),
            "interpretation": "Los candidatos no son fusiones ni duplicados confirmados.",
        }
        write_json_atomically(stage / "_metadata.json", metadata)
        (stage / "_SUCCESS").touch()
        publish_output(stage, output)
        print(f"Evidencia publicada: {output}")
        print(f"Resumen: {metadata}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
