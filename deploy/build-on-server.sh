#!/usr/bin/env bash
# 在 Linux 服务器上、仓库根目录执行：构建前端并安装 Python 依赖（不含 venv 创建，便于与 install-venv 拆分）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/frontend/dist/index.html" && "${SKIP_FRONTEND_BUILD:-}" != "0" ]]; then
  echo "==> 已存在 frontend/dist（打包机已构建），跳过 npm。若需重构建前端：rm -rf frontend/dist 或设 SKIP_FRONTEND_BUILD=0"
else
  echo "==> npm ci + build (frontend)"
  cd "$ROOT/frontend"
  if [[ ! -f package-lock.json ]]; then
    echo "缺少 frontend/package-lock.json" >&2
    exit 1
  fi
  npm ci
  npm run build
fi

echo "==> Python venv + pip（backend）"
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3.12 -m venv .venv 2>/dev/null || python3.11 -m venv .venv 2>/dev/null || python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt

echo "==> 完成。请配置 backend/.env 后启动："
echo "    cd $ROOT/backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"
