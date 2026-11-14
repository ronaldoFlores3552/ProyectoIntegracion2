"""Publica procesos, participantes reportados y dimensión de compradores desde OCDS."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from scripts.download_data import parse_years
from src.processing.build_fact_award import configure_pyspark_python, missing_or_blank
from src.processing.build_fact_award_item import (
    configure_windows_hadoop,
    input_paths,
    publish_output,
    staging_dir,
)
from src.processing.build_identity_evidence import verify_sources
from src.quality.profile_fact_award_item import write_json_atomically

PROCESS_KEY = "process_ocid"
PARTICIPANT_KEY = (PROCESS_KEY, "participant_id")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/processed/participation")
    )
    parser.add_argument("--years", nargs="+", required=True)
    parser.add_argument("--start-award-year", type=int, default=2023)
    parser.add_argument("--end-award-year", type=int, default=2024)
    parser.add_argument("--master", default="local[*]", help="Spark master; use local[*] en local.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _nonempty(column: str) -> F.Column:
    return ~missing_or_blank(column)


def _release_conflicts(releases: DataFrame) -> DataFrame:
    return releases.groupBy(PROCESS_KEY).count().where(F.col("count") > 1)


def select_eligible_releases(releases: DataFrame, start_year: int, end_year: int) -> DataFrame:
    """Keep one release per process that has an award inside the requested award-year window."""
    if PROCESS_KEY not in releases.columns:
        if "ocid" not in releases.columns:
            raise ValueError("Los releases no contienen ocid.")
        releases = releases.withColumnRenamed("ocid", PROCESS_KEY)
    invalid = releases.where(missing_or_blank(PROCESS_KEY)).limit(1)
    if invalid.count():
        raise ValueError("Los releases contienen process_ocid vacío.")
    conflicts = _release_conflicts(releases).limit(5).collect()
    if conflicts:
        examples = ", ".join(row[PROCESS_KEY] for row in conflicts)
        raise ValueError(f"Hay más de un release para el mismo proceso: {examples}.")

    awards = (
        releases.select(PROCESS_KEY, F.explode_outer("awards").alias("award"))
        .where(F.col("award.id").isNotNull())
        .withColumn("award_date", F.to_timestamp("award.date"))
        .where(F.year("award_date").between(start_year, end_year))
    )
    eligible = awards.groupBy(PROCESS_KEY).agg(
        F.countDistinct("award.id").cast("int").alias("eligible_award_count"),
        F.min("award_date").alias("first_eligible_award_date"),
        F.max("award_date").alias("last_eligible_award_date"),
    )
    return releases.join(eligible, PROCESS_KEY, "inner")


def _primary_segments(releases: DataFrame) -> DataFrame:
    """Choose the most frequent valid CUBSO two-digit segment; ties use lexical order."""
    segments = (
        releases.select(PROCESS_KEY, F.posexplode_outer("tender.items").alias("position", "item"))
        .select(
            PROCESS_KEY,
            F.col("item.classification.scheme").alias("classification_scheme"),
            F.col("item.classification.id").alias("classification_id"),
        )
        .where(F.upper("classification_scheme") == "CUBSO")
        .where(F.col("classification_id").rlike(r"^[0-9]{16}$"))
        .withColumn("cubso_segment", F.substring("classification_id", 1, 2))
        .groupBy(PROCESS_KEY, "cubso_segment")
        .count()
    )
    ranking = Window.partitionBy(PROCESS_KEY).orderBy(F.desc("count"), F.asc("cubso_segment"))
    primary = (
        segments.withColumn("_rank", F.row_number().over(ranking))
        .where(F.col("_rank") == 1)
        .select(
            PROCESS_KEY,
            "cubso_segment",
            F.col("count").cast("int").alias("primary_segment_items"),
        )
    )
    coverage = segments.groupBy(PROCESS_KEY).agg(
        F.count("*").cast("int").alias("cubso_segment_count")
    )
    return coverage.join(primary, PROCESS_KEY, "inner")


def build_fact_tender(releases: DataFrame) -> DataFrame:
    """Create one process row without expanding awards, items or participants."""
    segments = _primary_segments(releases)
    tenderer_count = F.when(F.col("tender.tenderers").isNull(), F.lit(0)).otherwise(
        F.size("tender.tenderers")
    )
    return (
        releases.select(
            "source_year",
            PROCESS_KEY,
            F.col("id").alias("release_id"),
            F.to_timestamp("date").alias("release_date"),
            F.to_timestamp("publishedDate").alias("published_date"),
            "eligible_award_count",
            "first_eligible_award_date",
            "last_eligible_award_date",
            F.col("buyer.id").alias("buyer_id"),
            F.col("buyer.name").alias("buyer_name"),
            F.col("tender.id").alias("tender_id"),
            F.col("tender.title").alias("tender_title"),
            F.col("tender.description").alias("tender_description"),
            F.col("tender.mainProcurementCategory").alias("procurement_category"),
            F.col("tender.procurementMethod").alias("procurement_method"),
            F.col("tender.procurementMethodDetails").alias("procurement_method_details"),
            F.col("tender.numberOfTenderers").cast("int").alias("number_of_tenderers"),
            tenderer_count.cast("int").alias("tenderer_list_count"),
        )
        .join(segments, PROCESS_KEY, "left")
    )


def tenderer_name_conflicts(releases: DataFrame) -> DataFrame:
    """Find a process/participant pair with incompatible non-empty names."""
    rows = (
        releases.select(
            PROCESS_KEY,
            F.posexplode_outer("tender.tenderers").alias("position", "tenderer"),
        )
        .select(
            PROCESS_KEY,
            F.trim(F.col("tenderer.id")).alias("participant_id"),
            F.when(
                F.col("tenderer.name").isNull() | (F.trim(F.col("tenderer.name")) == ""),
                F.lit(None).cast("string"),
            )
            .otherwise(F.trim(F.col("tenderer.name")))
            .alias("participant_name"),
        )
        .where(_nonempty("participant_id") & F.col("participant_name").isNotNull())
        .dropDuplicates()
    )
    return rows.groupBy(*PARTICIPANT_KEY).count().where(F.col("count") > 1)


def build_fact_tenderer(releases: DataFrame) -> DataFrame:
    """Return one valid participant-report row per process and published participant ID."""
    rows = (
        releases.select(
            "source_year",
            PROCESS_KEY,
            F.col("buyer.id").alias("buyer_id"),
            F.posexplode_outer("tender.tenderers").alias("participant_position", "tenderer"),
        )
        .select(
            "source_year",
            PROCESS_KEY,
            "buyer_id",
            "participant_position",
            F.trim(F.col("tenderer.id")).alias("participant_id"),
            F.when(
                F.col("tenderer.name").isNull() | (F.trim(F.col("tenderer.name")) == ""),
                F.lit(None).cast("string"),
            )
            .otherwise(F.trim(F.col("tenderer.name")))
            .alias("participant_name"),
        )
        .where(_nonempty("participant_id"))
    )
    return (
        rows.groupBy("source_year", PROCESS_KEY, "buyer_id", "participant_id")
        .agg(
            F.first("participant_name", ignorenulls=True).alias("participant_name"),
            F.min("participant_position").cast("int").alias("first_participant_position"),
            F.count("*").cast("int").alias("duplicate_rows_in_source"),
        )
        .select(
            "source_year",
            PROCESS_KEY,
            "buyer_id",
            "participant_id",
            "participant_name",
            "first_participant_position",
            "duplicate_rows_in_source",
        )
    )


def _buyer_party_rows(releases: DataFrame) -> DataFrame:
    return (
        releases.select(
            PROCESS_KEY,
            F.col("buyer.id").alias("buyer_id"),
            F.col("buyer.name").alias("buyer_name"),
            F.posexplode_outer("parties").alias("party_position", "party"),
        )
        .where(F.col("party.id") == F.col("buyer_id"))
        .select(
            PROCESS_KEY,
            "buyer_id",
            "buyer_name",
            "party_position",
            F.col("party.name").alias("party_name"),
            F.col("party.address.department").alias("department"),
            F.col("party.address.region").alias("region"),
            F.col("party.address.locality").alias("locality"),
            F.col("party.address.streetAddress").alias("street_address"),
            # El esquema OECE actual no publica postalCode; se mantiene como nulo explícito.
            F.lit(None).cast("string").alias("postal_code"),
            F.col("party.identifier").alias("identifier"),
            F.col("party.additionalIdentifiers").alias("additional_identifiers"),
        )
    )


def _canonical_values(rows: DataFrame, field: str) -> DataFrame:
    values = rows.where(~missing_or_blank(field)).groupBy("buyer_id").agg(
        F.array_sort(F.collect_set(F.trim(F.col(field)))).alias(f"_{field}_values")
    )
    return values.select(
        "buyer_id",
        F.element_at(f"_{field}_values", 1).alias(field),
        F.size(f"_{field}_values").cast("int").alias(f"{field}_variant_count"),
    )


def build_dim_buyer(releases: DataFrame) -> DataFrame:
    """Create one buyer row and retain variation counts instead of silently overwriting fields."""
    parties = _buyer_party_rows(releases)
    identifiers = parties.select(
        "buyer_id", F.explode_outer(F.array("identifier")).alias("identifier")
    ).unionByName(
        parties.select("buyer_id", F.explode_outer("additional_identifiers").alias("identifier"))
    )
    rucs = (
        identifiers.where(F.upper(F.col("identifier.scheme")) == "PE-RUC")
        .where(_nonempty("identifier.id"))
        .groupBy("buyer_id")
        .agg(F.array_sort(F.collect_set(F.trim(F.col("identifier.id")))).alias("buyer_ruc_values"))
        .withColumn("buyer_ruc", F.element_at("buyer_ruc_values", 1))
        .withColumn("buyer_ruc_variant_count", F.size("buyer_ruc_values").cast("int"))
    )
    result = parties.select("buyer_id").dropDuplicates()
    fields = (
        "buyer_name",
        "party_name",
        "department",
        "region",
        "locality",
        "street_address",
        "postal_code",
    )
    for field in fields:
        result = result.join(_canonical_values(parties, field), "buyer_id", "left")
    return (
        result.join(rucs, "buyer_id", "left")
        .withColumn("buyer_name", F.coalesce("buyer_name", "party_name"))
        .drop("party_name", "party_name_variant_count")
    )


def _validate_outputs(tenders: DataFrame, tenderers: DataFrame, buyers: DataFrame) -> None:
    if tenders.where(missing_or_blank(PROCESS_KEY) | missing_or_blank("buyer_id")).limit(1).count():
        raise ValueError("fact_tender contiene proceso o comprador vacío.")
    if tenders.groupBy(PROCESS_KEY).count().where(F.col("count") > 1).limit(1).count():
        raise ValueError("fact_tender no tiene grano único por proceso.")
    if tenderers.groupBy(*PARTICIPANT_KEY).count().where(F.col("count") > 1).limit(1).count():
        raise ValueError("fact_tenderer no tiene grano único por proceso y participante.")
    if tenderers.join(tenders.select(PROCESS_KEY), PROCESS_KEY, "left_anti").limit(1).count():
        raise ValueError("fact_tenderer contiene procesos ausentes de fact_tender.")
    if buyers.groupBy("buyer_id").count().where(F.col("count") > 1).limit(1).count():
        raise ValueError("dim_buyer no tiene grano único por comprador.")


def _validate_paths(raw: Path, output: Path, overwrite: bool) -> None:
    if output.exists() and not overwrite:
        raise FileExistsError(f"Ya existe {output}; use --overwrite para regenerar.")
    for target in (output, staging_dir(output), output.with_name(f"{output.name}.previous")):
        if target == raw or target in raw.parents or raw in target.parents:
            raise ValueError(f"La salida se solapa con los raw: {target}")


def run() -> None:
    args = parse_args()
    years = parse_years(args.years)
    if args.start_award_year > args.end_award_year:
        raise ValueError("La ventana de adjudicación es inválida.")
    raw, output = args.input_dir.resolve(), args.output_dir.resolve()
    _validate_paths(raw, output, args.overwrite)
    sources = verify_sources(raw, years)
    hadoop_home = configure_windows_hadoop()
    configure_pyspark_python()
    builder = (
        SparkSession.builder.appName("proyecto-integrador-2-build-participation")
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
                    "La JVM no cargó hadoop.dll; ejecute setup_windows_hadoop.py --check."
                )
        releases = spark.read.json(input_paths(raw, years)).withColumn(
            "source_year",
            F.regexp_extract(F.input_file_name(), r"([12][0-9]{3})\.jsonl\.gz", 1).cast("int"),
        )
        # No se cachea el release anidado completo: en local supera la memoria disponible.
        # Cada salida se calcula y escribe por separado; es más lento, pero evita publicar
        # resultados incompletos por un fallo de memoria.
        eligible = select_eligible_releases(releases, args.start_award_year, args.end_award_year)
        conflicts = tenderer_name_conflicts(eligible).limit(5).collect()
        if conflicts:
            examples = ", ".join(f"({r[PROCESS_KEY]}, {r['participant_id']})" for r in conflicts)
            raise ValueError(
                f"Un participante tiene nombres incompatibles en un proceso: {examples}"
            )
        tenders = build_fact_tender(eligible)
        tenderers = build_fact_tenderer(eligible)
        buyers = build_dim_buyer(eligible)
        _validate_outputs(tenders, tenderers, buyers)
        stage = staging_dir(output)
        shutil.rmtree(stage, ignore_errors=True)
        tables = {"fact_tender": tenders, "fact_tenderer": tenderers, "dim_buyer": buyers}
        for name, frame in tables.items():
            frame.write.mode("overwrite").parquet(str(stage / name))
            if not (stage / name / "_SUCCESS").is_file():
                raise RuntimeError(f"La tabla {name} no dejó _SUCCESS.")
        written = {
            name: spark.read.parquet(str(stage / name)) for name in tables
        }
        metadata = {
            "version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "sources": sources,
            "award_window": {
                "start_year": args.start_award_year,
                "end_year": args.end_award_year,
            },
            "participant_semantics": (
                "participantes reportados; contraste OECE fila a fila pendiente"
            ),
            "cubso_rule": (
                "segmento de dos dígitos más frecuente en tender.items CUBSO de 16 dígitos; "
                "empate léxico"
            ),
            "tables": {
                name: {"rows": written[name].count(), "columns": written[name].columns}
                for name in tables
            },
        }
        write_json_atomically(stage / "_metadata.json", metadata)
        (stage / "_SUCCESS").touch()
        publish_output(stage, output)
        print(f"Participación publicada: {output}")
    finally:
        spark.stop()


if __name__ == "__main__":
    run()
