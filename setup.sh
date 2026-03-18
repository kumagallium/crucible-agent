#!/usr/bin/env bash
# ==============================================================================
# Crucible Agent — セットアップスクリプト（ローカル開発用）
# ==============================================================================
# .env の生成と前提条件チェックを行う
#
# 使い方:
#   git clone https://github.com/kumagallium/crucible-agent.git
#   cd crucible-agent
#   ./setup.sh
#
# サーバーデプロイ（セキュリティ強化込み）は setup-server.sh を使用:
#   sudo bash setup-server.sh
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# --- 色付き出力 ---
info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$1"; }
ok()    { printf '\033[1;32m[OK]\033[0m    %s\n' "$1"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$1"; }
error() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$1"; }

# ==============================================================================
# 1. .env ファイルの生成
# ==============================================================================
info "環境変数ファイル (.env) をセットアップします"

if [[ -f .env ]]; then
  warn ".env は既に存在します。上書きしますか? [y/N]"
  read -r answer
  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    info ".env のセットアップをスキップしました"
    SKIP_ENV=true
  fi
fi

if [[ "${SKIP_ENV:-}" != "true" ]]; then
  cp .env.example .env
  chmod 600 .env
  ok ".env を生成しました"
  warn "API キーなどの設定は .env を編集してください"
fi

# ==============================================================================
# 2. 前提条件チェック
# ==============================================================================
info "前提条件を確認します"

MISSING=()
command -v docker &>/dev/null || MISSING+=("docker")
command -v git    &>/dev/null || MISSING+=("git")

# Docker Compose (plugin or standalone)
if docker compose version &>/dev/null 2>&1; then
  :
elif command -v docker-compose &>/dev/null; then
  :
else
  MISSING+=("docker compose")
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
  warn "以下のツールが見つかりません: ${MISSING[*]}"
  warn "インストール後に再実行してください"
else
  ok "前提条件を満たしています (docker, docker compose, git)"
fi

# ==============================================================================
# 完了
# ==============================================================================
echo ""
ok "セットアップ完了！"
echo ""
info "次のステップ:"
echo "  1. .env を編集して API キーを設定"
echo "       SAKURA_AI_API_KEY, SAKURA_AI_API_BASE など"
echo "  2. crucible-agent を起動:"
echo "       docker compose up -d"
echo ""
info "API:        http://localhost:8090"
info "Swagger UI: http://localhost:8090/docs"
info "LiteLLM:    http://localhost:4000"
