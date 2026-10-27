#!/usr/bin/env bash
set -euo pipefail
STRATOS_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$STRATOS_REPO_ROOT"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${STRATOS_REPO_ROOT}/.cache/uv}"
uv sync --frozen --python 3.12
(
  cd apps/web
  npm ci --cache "$STRATOS_REPO_ROOT/.cache/npm"
  npm run build
)
.venv/bin/python -m services.api.storage
