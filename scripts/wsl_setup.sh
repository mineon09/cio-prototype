#!/usr/bin/env bash
# ==============================================================================
# WSL セットアップスクリプト - CIO Prototype
# ==============================================================================
# このスクリプトは WSL (Ubuntu) 内で実行してください。
# 実行方法:
#   1. WSL ターミナルを開く (Windows Terminal → Ubuntu)
#   2. bash /mnt/c/Users/liver/Documents/antigravity/stock_analyze/scripts/wsl_setup.sh
# ==============================================================================
set -euo pipefail

# --- Configuration ---
PROJECT_NAME="stock_analyze"
WSL_PROJECT_DIR="$HOME/projects/$PROJECT_NAME"
WINDOWS_PROJECT_DIR="/mnt/c/Users/liver/Documents/antigravity/stock_analyze"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Step 1: System dependencies ---
info "========================================="
info "Step 1/5: システム依存パッケージの確認..."
info "========================================="
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git curl > /dev/null 2>&1
info "✅ Python3, venv, pip, git, curl を確認しました"

# --- Step 2: Copy project from Windows to WSL native FS ---
info "========================================="
info "Step 2/5: プロジェクトを WSL ネイティブ FS にコピー..."
info "========================================="
mkdir -p "$HOME/projects"

if [ -d "$WSL_PROJECT_DIR/.git" ]; then
    warn "プロジェクトが既に存在します: $WSL_PROJECT_DIR"
    warn "既存を削除して再コピーします..."
    rm -rf "$WSL_PROJECT_DIR"
fi

# rsync でコピー (venv, __pycache__ 等は除外)
if command -v rsync &> /dev/null; then
    rsync -a --progress \
        --exclude 'venv/' \
        --exclude '.venv/' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude '.edinet_cache/' \
        "$WINDOWS_PROJECT_DIR/" "$WSL_PROJECT_DIR/"
else
    # rsync が無い場合は cp + 手動除外
    cp -r "$WINDOWS_PROJECT_DIR" "$WSL_PROJECT_DIR"
    rm -rf "$WSL_PROJECT_DIR/venv" "$WSL_PROJECT_DIR/.venv" 2>/dev/null || true
    find "$WSL_PROJECT_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find "$WSL_PROJECT_DIR" -name "*.pyc" -delete 2>/dev/null || true
    rm -rf "$WSL_PROJECT_DIR/.edinet_cache" 2>/dev/null || true
fi

info "✅ プロジェクトコピー完了: $WSL_PROJECT_DIR"

# --- Step 3: Fix git config for WSL ---
info "========================================="
info "Step 3/5: Git 設定の調整..."
info "========================================="
cd "$WSL_PROJECT_DIR"

# line ending を LF に統一 (Linux)
git config core.autocrlf input
# filemode の差分を無視
git config core.filemode false

# WSL用 credential helper (Windows側の認証情報を共有)
git config credential.helper "/mnt/c/Program\ Files/Git/mingw64/bin/git-credential-manager.exe" 2>/dev/null || \
git config credential.helper "/mnt/c/Program\ Files/Git/mingw64/libexec/git-core/git-credential-manager.exe" 2>/dev/null || \
git config credential.helper store 2>/dev/null || true

info "✅ Git 設定 (autocrlf=input, credential helper) を適用しました"

# --- Step 4: Python virtual environment ---
info "========================================="
info "Step 4/5: Python 仮想環境のセットアップ..."
info "========================================="

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

info "✅ Python venv セットアップ完了 ($(python --version))"

# --- Step 5: bashrc に環境変数・エイリアスを追加 ---
info "========================================="
info "Step 5/5: シェル設定の更新..."
info "========================================="

BASHRC="$HOME/.bashrc"
MARKER="# --- CIO Prototype ---"

if ! grep -q "$MARKER" "$BASHRC" 2>/dev/null; then
    cat >> "$BASHRC" << 'EOF'

# --- CIO Prototype ---
export PYTHONUTF8=1
alias cio='cd ~/projects/stock_analyze && source venv/bin/activate'
# --- End CIO Prototype ---
EOF
    info "✅ .bashrc にエイリアス 'cio' と PYTHONUTF8=1 を追加しました"
else
    warn ".bashrc に CIO 設定は既に存在します (スキップ)"
fi

# --- Summary ---
echo ""
info "========================================="
info "🎉 WSL 移行完了！"
info "========================================="
echo ""
echo "  プロジェクト: $WSL_PROJECT_DIR"
echo "  Python:       $(python --version)"
echo "  venv:         $WSL_PROJECT_DIR/venv"
echo ""
echo "  次回から WSL ターミナルで以下を実行："
echo "    $ cio"
echo "    $ python main.py --ticker 7203.T"
echo ""
echo "  Streamlit ダッシュボード:"
echo "    $ cio"
echo "    $ streamlit run app.py"
echo ""
info "========================================="
