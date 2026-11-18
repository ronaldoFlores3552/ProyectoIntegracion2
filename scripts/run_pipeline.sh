#!/usr/bin/env bash
# Compatibilidad para Linux/macOS. En cualquier sistema se recomienda:
#   python scripts/run_project.py pipeline [etapa ...]
set -euo pipefail

cd "$(dirname "$0")/.."
if [ "$#" -eq 0 ]; then
  echo "El pipeline completo puede tardar. Revise primero:"
  echo "  python scripts/run_project.py review"
  echo "Para reconstruir todo de forma explícita:"
  echo "  python scripts/run_project.py pipeline --all"
  exit 0
fi
exec "${PYTHON:-python}" scripts/run_project.py pipeline "$@"
