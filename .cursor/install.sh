#!/usr/bin/env bash
# Cursor Cloud Build 用。冪等であること。長時間プロセスは起動しない。
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="${HOME}/.local/bin:${PATH}"

uv python install 3.12

if [[ -f pyproject.toml ]]; then
  if [[ -f uv.lock ]]; then
    uv sync --frozen --all-extras --dev
  else
    uv sync --all-extras --dev
  fi
fi

if [[ -f pnpm-lock.yaml ]]; then
  if ! command -v pnpm >/dev/null 2>&1; then
    if command -v corepack >/dev/null 2>&1; then
      corepack enable
    elif command -v npm >/dev/null 2>&1; then
      npm install -g pnpm
    else
      echo "pnpm is required but node/corepack/npm were not found" >&2
      exit 1
    fi
  fi
  pnpm install --frozen-lockfile
fi
