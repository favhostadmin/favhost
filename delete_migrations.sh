#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false

case "${1:-}" in
  --dry-run)
    DRY_RUN=true
    ;;
  --yes|"")
    DRY_RUN=false
    ;;
esac

echo "Project root: ${ROOT_DIR}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "Dry run only. Re-run without --dry-run to delete files."
  echo
fi

mapfile -t MIGRATION_FILES < <(
  find "${ROOT_DIR}" \
    -path "${ROOT_DIR}/env" -prune -o \
    -path "${ROOT_DIR}/.git" -prune -o \
    -path '*/migrations/*.py' \
    ! -name '__init__.py' \
    -type f \
    -print | sort
)

mapfile -t MIGRATION_CACHES < <(
  find "${ROOT_DIR}" \
    -path "${ROOT_DIR}/env" -prune -o \
    -path "${ROOT_DIR}/.git" -prune -o \
    -path '*/migrations/__pycache__' \
    -type d \
    -print | sort
)

if [[ "${#MIGRATION_FILES[@]}" -eq 0 && "${#MIGRATION_CACHES[@]}" -eq 0 ]]; then
  echo "No migration files or migration caches found."
  exit 0
fi

if [[ "${#MIGRATION_FILES[@]}" -gt 0 ]]; then
  echo "Migration files:"
  printf '  %s\n' "${MIGRATION_FILES[@]#${ROOT_DIR}/}"
fi

if [[ "${#MIGRATION_CACHES[@]}" -gt 0 ]]; then
  echo
  echo "Migration caches:"
  printf '  %s\n' "${MIGRATION_CACHES[@]#${ROOT_DIR}/}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  exit 0
fi

for file in "${MIGRATION_FILES[@]}"; do
  rm -f "${file}"
done

for cache_dir in "${MIGRATION_CACHES[@]}"; do
  rm -rf "${cache_dir}"
done

echo
echo "Deleted migration files and migration __pycache__ folders."
echo "Preserved every migrations/__init__.py file."