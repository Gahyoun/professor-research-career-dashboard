#!/usr/bin/env bash
set -euo pipefail

RELEASE_YEAR="${1:?usage: update_release.sh YEAR PRIVATE_DB_PATH}"
PRIVATE_DB_PATH="${2:?usage: update_release.sh YEAR PRIVATE_DB_PATH}"
: "${OPENALEX_API_KEY:?OPENALEX_API_KEY must be set}"
: "${NAMES_PASSWORD:?NAMES_PASSWORD must be set}"

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR"

PREPARE_ARGS=(--year "$RELEASE_YEAR" --db "$PRIVATE_DB_PATH")
if [[ -n "${AUTHOR_ALIASES_JSON:-}" ]]; then
  PREPARE_ARGS+=(--author-aliases "$AUTHOR_ALIASES_JSON")
fi
python3 backend/scripts/prepare_release.py "${PREPARE_ARGS[@]}"
RELEASE_YEAR="$RELEASE_YEAR" node backend/scripts/enrich_openalex_works.mjs
if [[ -f "backend/cache/$RELEASE_YEAR/author_aliases.json" ]]; then
  RELEASE_YEAR="$RELEASE_YEAR" node backend/scripts/enrich_openalex_alias_works.mjs
fi
RELEASE_YEAR="$RELEASE_YEAR" node backend/scripts/fetch_openalex_sources.mjs
RELEASE_YEAR="$RELEASE_YEAR" python3 backend/scripts/build_release.py --year "$RELEASE_YEAR"
RELEASE_YEAR="$RELEASE_YEAR" python3 backend/scripts/validate_release.py --year "$RELEASE_YEAR"
pnpm build
