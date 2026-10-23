#!/bin/bash
set -e

cd "$(dirname "$0")"
# Finder-launched Terminal sessions may not include common uv/Node install paths.
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin"

if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv，请先安装 uv 并运行 uv sync。"
  exit 1
fi

exec uv run python -m backend.dev
