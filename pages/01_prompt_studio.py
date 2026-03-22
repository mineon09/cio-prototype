"""
pages/01_prompt_studio.py - Prompt Studio (Streamlit マルチページ)
=====================================================================
STEP 1: ティッカー入力 → generate_prompt.py でプロンプト生成 → 画面表示
STEP 3: Claude 回答を貼り付け → save_claude_result.py 経由で results.json に保存
"""

import os
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path

import streamlit as st

# ============================================================
# Helpers
# ============================================================

def get_python_cmd() -> str:
    """venv が存在すれば優先、なければ sys.executable にフォールバック"""
    venv_py = Path("./venv/bin/python3")
    return str(venv_py) if venv_py.exists() else sys.executable


try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False


def copy_to_clipboard(text: str):
    """pyperclip でクリップボードにコピー"""
    try:
        pyperclip.copy(text)
        st.toast("📋 クリップボードにコピーしました")
    except Exception as e:
        st.warning(f"コピー失敗: {e}")


def validate_ticker(ticker: str) -> bool:
    """英数字・ドット・ハイフンのみ許可（最大20文字）"""
    return bool(re.match(r'^[A-Za-z0-9.\-]{1,20}$', ticker))


def extract_prompt_text(stdout: str) -> str:
    """
    generate_prompt.py の stdout から本文を抽出する。
    "====" 区切り行以降〜"💡 使用方法" 行の前まで。
    """
    lines = stdout.splitlines()
    start_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if start_idx is None and re.match(r'^=+$', line.strip()):
            start_idx = i + 1
        if start_idx is not None and "💡 使用方法" in line:
            end_idx = i
            break

    if start_idx is not None:
        segment = lines[start_idx:end_idx] if end_idx else lines[start_idx:]
        return "\n".join(segment).strip()

    # フォールバック: stdout 全体を返す
    return stdout.strip()


# ============================================================
# Page Config
# ============================================================

st.set_page_config(
    page_title="Prompt Studio",
    page_icon="🧠",
    layout="wide",
)

# セッションステートの初期化
if "generated_prompt" not in st.session_state:
    st.session_state["generated_prompt"] = ""
if "last_ticker" not in st.session_state:
    st.session_state["last_ticker"] = ""

st.title("🧠 Prompt Studio")
st.caption("STEP 1 でプロンプトを生成し、Claude に貼り付けた後、STEP 3 で結果を保存します。")

col_left, col_right = st.columns(2)

# ============================================================
# 左カラム — STEP 1: プロンプト生成
# ============================================================
with col_left:
    st.subheader("📝 STEP 1 — プロンプト生成")

    ticker_gen = st.text_input(
        "ティッカーコード",
        placeholder="例: 7203.T, AAPL",
        key="gen_ticker",
    )
    model_sel = st.selectbox(
        "モデル",
        ["claude", "gemini", "qwen", "chatgpt"],
        key="gen_model",
    )
    simple_mode = st.checkbox(
        "シンプルモード（データ取得なし・高速）",
        value=False,
        key="gen_simple",
    )

    gen_btn = st.button("🔍 プロンプト生成", type="primary")

    if gen_btn:
        # バリデーション
        if not ticker_gen:
            st.error("ティッカーコードを入力してください")
            st.stop()
        if not validate_ticker(ticker_gen):
            st.error("無効なティッカーコードです（英数字・ドット・ハイフン、最大20文字）")
            st.stop()

        ticker_gen_upper = ticker_gen.strip().upper()
        py_cmd = get_python_cmd()

        cmd = [py_cmd, "generate_prompt.py", ticker_gen_upper, "--model", model_sel]
        if simple_mode:
            cmd.append("--simple")

        with st.spinner("プロンプト生成中..."):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(Path(__file__).parent.parent),
                )
            except subprocess.TimeoutExpired:
                st.error("タイムアウト（120秒）: データ取得に失敗しました")
                st.stop()

        if result.returncode == 0:
            prompt_text = extract_prompt_text(result.stdout)
            st.session_state["generated_prompt"] = prompt_text
            st.session_state["last_ticker"] = ticker_gen_upper
            st.success("✅ プロンプト生成完了")
        else:
            st.error(f"❌ 生成失敗: {result.stderr[:200] if result.stderr else '（エラーなし）'}")
            with st.expander("エラーログ"):
                st.code(result.stderr or result.stdout or "（出力なし）")

    # 生成済みプロンプトの表示（ページリロード後も維持）
    if st.session_state["generated_prompt"]:
        prompt_text = st.session_state["generated_prompt"]

        st.text_area(
            "生成されたプロンプト",
            value=prompt_text,
            height=400,
            key="prompt_display",
        )

        if HAS_PYPERCLIP:
            st.button(
                "📋 クリップボードにコピー",
                on_click=copy_to_clipboard,
                args=(prompt_text,),
                key="copy_btn",
            )
        else:
            st.info("上のテキストエリアを選択して手動コピーしてください")

        # コンテキストJSON 確認（simple=False の場合のみ）
        if not st.session_state.get("gen_simple", False):
            last_t = st.session_state["last_ticker"]
            context_path = f"prompts/{last_t.replace('.', '_')}_context.json"
            if os.path.exists(context_path):
                st.info(f"📋 コンテキスト保存済み: {context_path}")
            else:
                st.warning("⚠️ コンテキストJSONが見つかりません")


# ============================================================
# 右カラム — STEP 3: 結果保存
# ============================================================
with col_right:
    st.subheader("💾 STEP 3 — 結果保存")

    save_ticker = st.text_input(
        "ティッカーコード",
        key="save_ticker",
        placeholder="STEP 1 と同じコードを入力",
        value=st.session_state.get("last_ticker", ""),
    )
    model_name = st.text_input(
        "使用モデル名（任意）",
        value="claude-sonnet-4-5",
        placeholder="claude-sonnet-4-5",
        key="save_model",
    )
    response_text = st.text_area(
        "Claude の回答をここに貼り付け",
        height=300,
        placeholder='```json\n{"signal": "BUY", ...}\n```\nを含む回答全体をペースト',
        key="save_response",
    )

    save_btn = st.button("💾 ダッシュボードに保存", type="primary")

    if save_btn:
        # バリデーション
        if not save_ticker:
            st.error("ティッカーコードを入力してください")
            st.stop()
        if not validate_ticker(save_ticker):
            st.error("無効なティッカーコードです（英数字・ドット・ハイフン、最大20文字）")
            st.stop()
        if not response_text:
            st.error("Claude の回答を貼り付けてください")
            st.stop()

        # JSON ブロックチェック
        has_json_block = "```json" in response_text
        if not has_json_block:
            confirm_key = "confirm_no_json"
            confirmed = st.session_state.get(confirm_key, False)
            st.warning("⚠️ JSONブロックが見つかりません。保存を続行しますか？")
            if not confirmed:
                if st.checkbox("続行する", key=confirm_key):
                    st.rerun()
                st.stop()

        save_ticker_upper = save_ticker.strip().upper()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_path = f"/tmp/claude_response_{save_ticker_upper}_{timestamp}.txt"

        # 一時ファイルに書き出し
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(response_text)
        except Exception as e:
            st.error(f"❌ 一時ファイル書き出し失敗: {e}")
            st.stop()

        py_cmd = get_python_cmd()
        cmd = [
            py_cmd, "save_claude_result.py",
            save_ticker_upper,
            "--from-file", tmp_path,
            "--model", model_name or "claude-sonnet-4-5",
        ]

        with st.spinner("ダッシュボードに保存中..."):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(Path(__file__).parent.parent),
                )
            except subprocess.TimeoutExpired:
                os.unlink(tmp_path)
                st.error("タイムアウト（120秒）: 保存に失敗しました")
                st.stop()
            finally:
                # 一時ファイル削除
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        if result.returncode == 0:
            stdout = result.stdout

            # signal / score / entry_price を stdout から抽出
            signal_match = re.search(r'シグナル\s*[:：]\s*(\S+)', stdout)
            score_match = re.search(r'総合スコア\s*[:：]\s*([0-9.]+)', stdout)
            entry_match = re.search(r'エントリー\s*[:：]\s*([0-9.,]+)', stdout)

            signal_val = signal_match.group(1) if signal_match else "N/A"
            score_val = score_match.group(1) if score_match else "N/A"
            entry_val = entry_match.group(1) if entry_match else "N/A"

            st.success("✅ 保存完了")

            m1, m2, m3 = st.columns(3)
            m1.metric("シグナル", signal_val)
            m2.metric("スコア", f"{score_val}/10" if score_val != "N/A" else "N/A")
            m3.metric("エントリー価格", entry_val)

            st.balloons()

            # confirm_no_json フラグをリセット
            if "confirm_no_json" in st.session_state:
                del st.session_state["confirm_no_json"]
        else:
            st.error(f"❌ 保存失敗: {result.stderr[:200] if result.stderr else '（エラーなし）'}")
            with st.expander("エラーログ"):
                st.code(result.stderr or result.stdout or "（出力なし）")


# ============================================================
# フッター — エンドツーエンドフロー図
# ============================================================
st.divider()
st.caption("📖 使い方フロー")
st.info(
    "**[STEP 1]** ティッカー入力 → プロンプト生成  \n"
    "　　↓ 生成されたプロンプトをコピー  \n"
    "**[STEP 2]** Claude Web UI に貼り付けて実行  \n"
    "　　↓ 回答全体をコピー  \n"
    "**[STEP 3]** 右カラムに貼り付け → 保存ボタン  \n"
    "　　↓ ダッシュボードに反映"
)
