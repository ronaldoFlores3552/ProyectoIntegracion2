#!/usr/bin/env bash
# Uso: bash scripts/run_pipeline.sh [etapa ...]
set -euo pipefail

cd "$(dirname "$0")/.."
MASTER="${SPARK_MASTER:-local[8]}"
export PYSPARK_SUBMIT_ARGS="--driver-memory ${SPARK_DRIVER_MEMORY:-6g} pyspark-shell"
PY="${PYTHON:-python}"

run() {
  echo
  echo "==> $*"
  "$PY" -m "$@"
}

base() {
  "$PY" scripts/validate_environment.py
  run src.processing.build_fact_award_item --years 2023 2024 --master "$MASTER" --overwrite
  run src.quality.profile_fact_award_item --overwrite
  run src.processing.build_fact_award --master "$MASTER" --overwrite
  run src.processing.build_fact_award_supplier --master "$MASTER" --overwrite
  run src.features.build_interactions --master "$MASTER" --overwrite
  run src.processing.build_identity_evidence --years 2023 2024 --master "$MASTER" --overwrite
}

parte1() {
  run src.features.build_part1 --master "$MASTER" --overwrite
}

clustering() {
  run src.models.build_clustering --overwrite
}

recomendacion() {
  run src.features.build_recommendation --master "$MASTER" --overwrite
  run src.models.recommendation_baseline --overwrite
  run src.models.recommendation_neighbors --overwrite
  run src.models.recommendation_als --master "$MASTER" --overwrite
  run src.models.recommendation_test --master "$MASTER" --overwrite
  run src.models.recommendation_content --overwrite
  run src.models.recommendation_hybrid --overwrite
  run src.models.recommendation_substitutes --overwrite
}

participacion() {
  run src.processing.build_participation --years 2023 2024 --master "$MASTER" --overwrite
}

p1() {
  run src.features.build_market_p1 --master "$MASTER" --overwrite
  run src.models.analyze_market_p1 --overwrite
}

p2() {
  run src.features.build_market_p2 --master "$MASTER" --overwrite
  run src.features.build_market_p2 --max-recurrent-participants 30 \
    --output-dir data/processed/market_p2_k30 --master "$MASTER" --overwrite
  run src.quality.profile_market_p2 --market-dir data/processed/market_p2_k30 \
    --master "$MASTER" --overwrite
  run src.models.analyze_links_p2 --overwrite
  run src.models.hits_sensitivity_p2 --overwrite
  run src.models.detect_communities_p2 --overwrite
  run src.models.louvain_order_p2 --overwrite
  run src.models.null_communities_p2 --replicates 50 --trades-per-participant 50 --overwrite
  run src.models.null_communities_p2 --replicates 50 --trades-per-participant 50 \
    --resolution 1.0 --output-dir artifacts/p2/null_r1 --overwrite
}

perfiles() {
  run src.features.build_buyer_profiles --master "$MASTER" --overwrite
  run src.models.cluster_buyer_profiles --overwrite
  run src.models.profile_outliers --overwrite
}

comunidades() {
  run src.models.partition_subgraph_p2 --overwrite
  run src.models.bigclam_p2 --overwrite
  run src.models.link_closure_p1 --overwrite
}

representacion() {
  run src.models.build_svd_p2 --overwrite
  run src.models.build_svd_p2 --matrix participation --components 64 \
    --output-dir artifacts/p2/svd_participation --overwrite
  run src.models.build_convergence_p2 --overwrite
  run src.models.embed_visualization_p2 --overwrite
}

web() {
  run src.web.export_web_data --overwrite
}

ALL=(base parte1 clustering participacion recomendacion p1 p2 perfiles comunidades representacion web)
STAGES=("$@")
[ ${#STAGES[@]} -eq 0 ] && STAGES=("${ALL[@]}")
for stage in "${STAGES[@]}"; do
  echo
  echo "#### etapa: $stage"
  "$stage"
done
echo
echo "Pipeline terminado: ${STAGES[*]}"
