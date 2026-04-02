"""
pages/01_prompt_studio.py - Prompt Studio (Streamlit マルチページ)
=====================================================================
STEP 1: ティッカー入力 → generate_prompt.py でプロンプト生成 → 画面表示
STEP 3: Claude 回答を貼り付け → save_claude_result.py 経由で results.json に保存
"""

import os
import queue as queue_module
import re
import sys
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

# ============================================================
# Secrets Bridge: Streamlit Cloud → os.environ（サブプロセスへ継承）
# ============================================================
_ALL_SECRET_KEYS = [
    # AI
    "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY",
    # Data sources
    "EDINET_API_KEY", "EDINETDB_API_KEY", "JQUANTS_API_KEY",
    "FINNHUB_API_KEY", "EXA_API_KEY", "PERPLEXITY_API_KEY", "TAVILY_API_KEY",
    "SEC_USER_AGENT",
    # Google Sheets
    "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SHEETS_KEY_PATH", "SPREADSHEET_ID",
    # LINE
    "LINE_CHANNEL_ACCESS_TOKEN", "LINE_USER_ID", "LINE_NOTIFY_TOKEN",
    # Notion
    "NOTION_API_KEY", "NOTION_DATABASE_ID",
]
try:
    for _key in _ALL_SECRET_KEYS:
        if _key in st.secrets and _key not in os.environ:
            os.environ[_key] = st.secrets[_key]
except Exception:
    pass  # ローカル環境では st.secrets が無い場合あり

# ============================================================
# Helpers
# ============================================================

def get_python_cmd() -> str:
    """venv が存在すれば優先、なければ sys.executable にフォールバック"""
    venv_py = Path("./venv/bin/python3")
    return str(venv_py) if venv_py.exists() else sys.executable


import base64


def render_copy_button(text: str, key: str = "copy_btn"):
    """クリップボードコピーボタン。
    navigator.clipboard（HTTPS必須）が使えない場合は textarea を全選択して
    手動コピーしやすくするフォールバックを提供する（iOS Safari 対応）。"""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    fallback_id = f"{key}_fallback"
    html = f"""
    <button id="{key}" onclick="
        const txt = new TextDecoder().decode(Uint8Array.from(atob('{encoded}'), c => c.charCodeAt(0)));
        if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(txt)
                .then(() => {{
                    document.getElementById('{key}').innerText = '✅ コピー完了';
                    document.getElementById('{fallback_id}').style.display = 'none';
                }})
                .catch(() => {{
                    document.getElementById('{key}').innerText = '❌ コピー失敗 — 下のテキストを全選択してコピー';
                    document.getElementById('{fallback_id}').style.display = 'block';
                    document.getElementById('{fallback_id}').select();
                }});
        }} else {{
            document.getElementById('{key}').innerText = '❌ コピー不可 — 下のテキストを全選択してコピー';
            document.getElementById('{fallback_id}').style.display = 'block';
            document.getElementById('{fallback_id}').select();
        }}
    " style="padding:8px 16px; background:#FF4B4B; color:white; border:none; border-radius:4px;
             cursor:pointer; font-size:14px; font-family:sans-serif;">
        📋 クリップボードにコピー
    </button>
    <textarea id="{fallback_id}" style="display:none; width:100%; height:60px; margin-top:8px;
              font-size:12px; resize:none;"
              onfocus="this.select()"
              readonly>{text.replace('<', '&lt;').replace('>', '&gt;')}</textarea>
    """
    st.components.v1.html(html, height=80)


def validate_ticker(ticker: str) -> bool:
    """英数字・ドット・ハイフンのみ許可（最大20文字）"""
    return bool(re.match(r'^[A-Za-z0-9.\-]{1,20}$', ticker))


_GEN_TIMEOUT = 300  # プロンプト生成の最大待機秒数


def _run_cmd_in_thread(cmd: list, cwd: str, result_queue):
    """バックグラウンドスレッドでサブプロセスを実行し結果をキューに入れる"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        result_queue.put(("ok", result))
    except Exception as e:
        result_queue.put(("error", str(e)))


def run_with_progress(cmd: list, cwd: str, timeout: int = _GEN_TIMEOUT):
    """
    サブプロセスをバックグラウンドスレッドで実行し、
    経過時間をリアルタイム表示する。
    Returns: subprocess.CompletedProcess | None（タイムアウト/エラー時）
    """
    rq = queue_module.Queue()
    thread = threading.Thread(
        target=_run_cmd_in_thread, args=(cmd, cwd, rq), daemon=True
    )
    thread.start()

    status_text = st.empty()
    progress_bar = st.progress(0.0)
    start = time.time()

    while thread.is_alive():
        elapsed = int(time.time() - start)
        if elapsed >= timeout:
            status_text.empty()
            progress_bar.empty()
            return None  # タイムアウト
        status_text.caption(f"⏳ データ取得中... {elapsed}秒経過（最大 {timeout}秒）")
        progress_bar.progress(min(elapsed / timeout, 0.95))
        time.sleep(1)

    status_text.empty()
    progress_bar.empty()

    try:
        status, result = rq.get_nowait()
    except queue_module.Empty:
        return None

    if status == "ok":
        return result
    st.error(f"実行エラー: {result}")
    return None


def extract_prompt_text(stdout: str) -> str:
    """
    generate_prompt.py の stdout から本文を抽出する。
    1つ目の "====" 区切り行の直後から、2つ目の "====" 行の直前まで。
    2つ目が見つからない場合は "💡 使用方法" 行の前までをフォールバックとする。
    """
    lines = stdout.splitlines()
    start_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if re.match(r'^=+$', line.strip()):
            if start_idx is None:
                start_idx = i + 1  # 1つ目の ==== の次行からプロンプト開始
            else:
                end_idx = i        # 2つ目の ==== の直前でプロンプト終了
                break
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
    layout="centered",
)

# セッションステートの初期化
if "generated_prompt" not in st.session_state:
    st.session_state["generated_prompt"] = ""
if "last_ticker" not in st.session_state:
    st.session_state["last_ticker"] = ""
if "save_ticker" not in st.session_state:
    st.session_state["save_ticker"] = ""

st.title("🧠 Prompt Studio")
st.caption("STEP 1 でプロンプトを生成し、Claude に貼り付けた後、STEP 3 で結果を保存します。")

tab1, tab2 = st.tabs(["📝 STEP 1 — プロンプト生成", "💾 STEP 3 — 結果保存"])

# ============================================================
# STEP 1: プロンプト生成
# ============================================================
with tab1:

    ticker_gen = st.text_input(
        "ティッカーコード",
        placeholder="例: 7203.T, AAPL",
        key="gen_ticker",
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

        cmd = [py_cmd, "generate_prompt.py", ticker_gen_upper]
        if simple_mode:
            cmd.append("--simple")

        with st.spinner("プロンプト生成中..."):
            result = run_with_progress(cmd, str(Path(__file__).parent.parent))
            if result is None:
                st.error(
                    f"⏰ タイムアウト（{_GEN_TIMEOUT}秒）: データ取得に時間がかかりすぎました。\n"
                    "「シンプルモード」をオンにして再試行してください。"
                )
                st.stop()

        if result.returncode == 0:
            prompt_text = extract_prompt_text(result.stdout)
            st.session_state["generated_prompt"] = prompt_text
            st.session_state["last_ticker"] = ticker_gen_upper
            st.session_state["save_ticker"] = ticker_gen_upper  # STEP3フィールドを自動入力
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

        render_copy_button(prompt_text, key="copy_btn")

        # コンテキストJSON 確認（simple=False の場合のみ）
        if not st.session_state.get("gen_simple", False):
            last_t = st.session_state["last_ticker"]
            context_path = f"prompts/{last_t.replace('.', '_')}_context.json"
            if os.path.exists(context_path):
                st.info(f"📋 コンテキスト保存済み: {context_path}")
            else:
                st.warning("⚠️ コンテキストJSONが見つかりません")


# ============================================================
# STEP 3: 結果保存
# ============================================================
with tab2:

    save_ticker = st.text_input(
        "ティッカーコード",
        key="save_ticker",
        placeholder="STEP 1 と同じコードを入力",
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

        # クロスプラットフォーム対応の一時ファイル
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
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
            result = run_with_progress(cmd, str(Path(__file__).parent.parent), timeout=60)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            if result is None:
                st.error("⏰ タイムアウト（60秒）: 保存に失敗しました")
                st.stop()

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

            # Notion 保存結果を表示
            notion_url_match = re.search(r'Notionに保存完了[:：]\s*(https://\S+)', stdout)
            notion_skip_match = re.search(r'Notion\s*保存スキップ[:：]\s*(.+)', stdout)
            if notion_url_match:
                notion_url = notion_url_match.group(1).strip()
                st.markdown(f"📝 [Notion に保存済み]({notion_url})")
            elif notion_skip_match:
                st.warning(f"⚠️ Notion 保存スキップ: {notion_skip_match.group(1).strip()}")

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
    "**[STEP 1タブ]** ティッカー入力 → プロンプト生成  \n"
    "　　↓ 生成されたプロンプトをコピー  \n"
    "**[STEP 2]** Claude Web UI に貼り付けて実行  \n"
    "　　↓ 回答全体をコピー  \n"
    "**[STEP 3タブ]** 回答を貼り付け → 保存ボタン  \n"
    "　　↓ ダッシュボードに反映"
)
