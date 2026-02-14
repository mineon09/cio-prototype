"""
app.py - CIO Intelligence Dashboard (Streamlit GUI)
=====================================================
ブラウザベースの対話型株式分析ダッシュボード。
ターミナル不要で銘柄入力→分析実行→結果表示を完結。

起動: streamlit run app.py
"""

import os
import sys
import json
import time
import threading
import streamlit as st
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(__file__))

# ============================================================
# Secrets Bridge: Streamlit Cloud ↔ ローカル .env
# ============================================================
# Streamlit Cloud では st.secrets から、ローカルでは .env から読み込む
try:
    for key in ["GEMINI_API_KEY", "EDINET_API_KEY", "SPREADSHEET_ID",
                 "GOOGLE_SERVICE_ACCOUNT_JSON",
                 "LINE_CHANNEL_ACCESS_TOKEN", "LINE_USER_ID"]:
        if key in st.secrets:
            os.environ[key] = st.secrets[key]
except Exception:
    pass  # st.secrets が使えない場合（ローカル）はスキップ

from dotenv import load_dotenv
load_dotenv()

from data_fetcher import fetch_stock_data, select_competitors, call_gemini
from analyzers import generate_scorecard, format_yuho_for_prompt
from edinet_client import extract_yuho_data, is_japanese_stock

try:
    from sec_client import extract_sec_data, is_us_stock
except ImportError:
    def is_us_stock(ticker): return not ticker.endswith('.T')
    def extract_sec_data(ticker): return {}

try:
    from dcf_model import estimate_fair_value
except ImportError:
    def estimate_fair_value(ticker): return {"available": False}

try:
    from macro_regime import detect_regime
except ImportError:
    def detect_regime(): return {}

from notifier import send_line_push


# ============================================================
# Page Config
# ============================================================
st.set_page_config(
    page_title="CIO Intelligence Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# Styling
# ============================================================
st.markdown("""
<style>
    .stApp { background-color: #0f172a; }
    .score-big { font-size: 3rem; font-weight: 800; text-align: center; }
    .signal-buy { background: #22c55e20; border: 1px solid #22c55e; color: #22c55e;
                  padding: 8px 20px; border-radius: 8px; font-weight: 700; text-align: center; }
    .signal-sell { background: #ef444420; border: 1px solid #ef4444; color: #ef4444;
                   padding: 8px 20px; border-radius: 8px; font-weight: 700; text-align: center; }
    .signal-watch { background: #eab30820; border: 1px solid #eab308; color: #eab308;
                    padding: 8px 20px; border-radius: 8px; font-weight: 700; text-align: center; }
    .metric-card { background: #1e293b; border-radius: 8px; padding: 12px; text-align: center; }
    .metric-label { color: #94a3b8; font-size: 0.75rem; }
    .metric-value { color: #f1f5f9; font-size: 1.1rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# Load results data
# ============================================================
def load_results():
    path = os.path.join(os.path.dirname(__file__), "data", "results.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def get_latest(ticker_data):
    if ticker_data.get("history"):
        latest = ticker_data["history"][-1]
        latest["name"] = ticker_data.get("name", "")
        latest["sector"] = ticker_data.get("sector", "")
        latest["currency"] = ticker_data.get("currency", "USD")
        return latest
    return ticker_data

def score_color(score):
    if score >= 7: return "#22c55e"
    if score >= 4: return "#eab308"
    return "#ef4444"

# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.title("🤖 CIO Intelligence")
    st.markdown("---")

    # Ticker Input
    st.subheader("📈 銘柄分析")
    ticker_input = st.text_input(
        "ティッカー入力",
        placeholder="例: AMAT, 7203.T",
        help="米国株はそのまま、日本株は .T 付きで入力"
    )

    run_analysis = st.button("🚀 分析実行", type="primary", width="stretch")

    st.markdown("---")

    # Past Analysis History
    st.subheader("📋 分析履歴")
    results = load_results()
    if results:
        for t in reversed(list(results.keys())):
            d = get_latest(results[t])
            signal = d.get("signal", "WATCH")
            emoji = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡"}.get(signal, "⚪")
            score = d.get("total_score", 0)
            hist_count = len(results[t].get("history", []))
            if st.sidebar.button(
                f"{emoji} {t} — {d.get('name', '')[:15]} ({score:.1f}) [{hist_count}件]",
                key=f"hist_{t}",
                width="stretch",
            ):
                st.session_state["view_ticker"] = t
    else:
        st.info("まだ分析データがありません")

    st.markdown("---")

    # LINE Test
    if st.button("🔔 LINE通知テスト（Messaging API）", width="stretch"):
        if send_line_push("\n🧪 CIO Intelligence — Messaging API テスト通知"):
            st.success("送信成功! (LINEアプリを確認してください)")
        else:
            st.error("送信失敗。line_secret.txt (Token, UserID) を確認してください。")


# ============================================================
# Run Analysis
# ============================================================
if run_analysis and ticker_input:
    ticker = ticker_input.strip().upper()
    st.session_state["view_ticker"] = ticker

    with st.status(f"🔍 {ticker} を分析中...", expanded=True) as status:
        # Step 1: Fetch stock data
        st.write("📊 株価データ取得中...")
        target_data = fetch_stock_data(ticker)

        # Step 2: Select competitors
        st.write("🧠 比較対象を選定中...")
        competitors = select_competitors(target_data)

        # Step 3: EDINET / SEC
        yuho_data = {}
        if is_japanese_stock(ticker):
            st.write("🇯🇵 EDINET 有報を検索中...")
            yuho_data = extract_yuho_data(ticker)
        elif is_us_stock(ticker):
            st.write("🇺🇸 SEC 10-K/10-Q を検索中...")
            yuho_data = extract_sec_data(ticker)

        # Step 4: DCF
        st.write("💰 DCF理論株価を算出中...")
        dcf_data = estimate_fair_value(ticker)

        # Step 5: Macro
        st.write("🌍 マクロ環境を判定中...")
        macro_data = detect_regime()

        # Step 6: Scorecard
        st.write("📋 4軸スコア算出中...")
        sector = target_data.get("sector", "")
        scorecard = generate_scorecard(
            target_data.get("metrics", {}),
            target_data.get("technical", {}),
            yuho_data,
            sector=sector,
            dcf_data=dcf_data,
            macro_data=macro_data,
        )

        # Step 7: Report (Gemini)
        st.write("📝 最終レポート生成中...")
        from main import analyze_all, save_to_dashboard_json
        report, table_str = analyze_all(
            ticker, {ticker: target_data}, competitors,
            yuho_data=yuho_data, scorecard=scorecard,
        )

        # Save
        save_to_dashboard_json(ticker, target_data, scorecard, report,
                               dcf_data=dcf_data, macro_data=macro_data)

        status.update(label=f"✅ {ticker} 分析完了!", state="complete")

    # Reload results
    results = load_results()

# ============================================================
# Main View
# ============================================================
view_ticker = st.session_state.get("view_ticker")

if view_ticker and view_ticker in results:
    raw = results[view_ticker]
    data = get_latest(raw)
    scores = data.get("scores", {})
    metrics = data.get("metrics", {})
    tech = data.get("technical_data", {})
    dcf = data.get("dcf", {})
    macro = data.get("macro", {})

    # ── Header ──
    col1, col2, col3, col4 = st.columns([3, 1, 1, 2])
    with col1:
        st.title(f"{view_ticker}")
        st.caption(f"{data.get('name', '')} | {data.get('sector', '')} | {data.get('date', '')}")
    with col2:
        total = data.get("total_score", 0)
        color = score_color(total)
        st.markdown(f'<div class="score-big" style="color:{color}">{total:.1f}</div>', unsafe_allow_html=True)
        st.caption("総合スコア")
    with col3:
        signal = data.get("signal", "WATCH")
        st.markdown(f'<div class="signal-{signal.lower()}">{signal}</div>', unsafe_allow_html=True)
    with col4:
        if macro:
            regime = macro.get("regime", "")
            st.metric("🌍 Regime", regime)
            st.caption(macro.get("description", "")[:60])

    st.markdown("---")

    # ── Score Cards ──
    cols = st.columns(4)
    for i, (axis, label) in enumerate([
        ("fundamental", "📊 地力"), ("valuation", "💰 割安度"),
        ("technical", "⏱️ タイミング"), ("qualitative", "📋 定性")
    ]):
        with cols[i]:
            s = scores.get(axis, 0)
            st.metric(label, f"{s:.1f} / 10")
            st.progress(s / 10)

    # ── DCF & Key Metrics ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📊 Key Metrics")
        m_cols = st.columns(3)
        items = [
            ("ROE", f"{metrics.get('roe', '-')}%"),
            ("PER", f"{float(metrics.get('per', 0)):.1f}x" if metrics.get('per') else "-"),
            ("PBR", f"{float(metrics.get('pbr', 0)):.2f}x" if metrics.get('pbr') else "-"),
            ("OP Margin", f"{metrics.get('op_margin', '-')}%"),
            ("RSI", f"{float(tech.get('rsi', 0)):.1f}" if tech.get('rsi') else "-"),
            ("Price", f"${float(tech.get('current_price', 0)):,.0f}" if tech.get('current_price') else "-"),
        ]
        for j, (label, val) in enumerate(items):
            with m_cols[j % 3]:
                st.metric(label, val)

    with col_right:
        if dcf and dcf.get("fair_value"):
            st.subheader("💰 DCF理論株価")
            fv = dcf.get("fair_value", 0)
            cp = dcf.get("current_price", 0)
            upside = dcf.get("upside", 0)
            mos = dcf.get("margin_of_safety", 0)

            dcf_cols = st.columns(3)
            with dcf_cols[0]:
                st.metric("理論株価", f"${fv:,.0f}")
            with dcf_cols[1]:
                st.metric("現在株価", f"${cp:,.0f}")
            with dcf_cols[2]:
                st.metric("上昇余地", f"{upside:+.1f}%",
                          delta=f"安全域 {mos:.0f}%")

            # Scenarios
            scenarios = dcf.get("scenarios", {})
            if scenarios:
                for name, sc in scenarios.items():
                    emoji = {"bull": "🐂", "base": "📊", "bear": "🐻"}.get(name, "")
                    label = {"bull": "楽観", "base": "基本", "bear": "悲観"}.get(name, name)
                    st.caption(f"{emoji} {label}: 成長率 {sc.get('growth_rate', 0)}% → ${sc.get('fair_value', 0):,.0f}")
        else:
            st.subheader("📈 テクニカル")
            st.metric("RSI", f"{float(tech.get('rsi', 0)):.1f}" if tech.get('rsi') else "-")
            st.metric("MA25乖離", f"{float(tech.get('ma25_deviation', 0)):.1f}%" if tech.get('ma25_deviation') else "-")

    st.markdown("---")

    # ── Trend Chart ──
    history = raw.get("history", [])
    if len(history) >= 2:
        st.subheader("📈 Score Trend")
        import pandas as pd
        trend_data = {
            "日付": [h.get("date", "").split(" ")[0] for h in history],
            "総合": [h.get("total_score", 0) for h in history],
            "地力": [h.get("scores", {}).get("fundamental", 0) for h in history],
            "割安度": [h.get("scores", {}).get("valuation", 0) for h in history],
            "タイミング": [h.get("scores", {}).get("technical", 0) for h in history],
            "定性": [h.get("scores", {}).get("qualitative", 0) for h in history],
        }
        df = pd.DataFrame(trend_data).set_index("日付")
        st.line_chart(df, height=250)

    # ── Report ──
    st.subheader("📝 Analysis Report")
    report_text = data.get("report", "")
    if report_text:
        st.markdown(report_text.replace("\n", "\n\n"))
    else:
        st.info("レポートがありません")

elif not results:
    st.title("🤖 CIO Intelligence Dashboard")
    st.info("👈 サイドバーからティッカーを入力して分析を実行してください")
else:
    st.title("🤖 CIO Intelligence Dashboard")

    # Overview table
    st.subheader("📊 全銘柄サマリー")
    rows = []
    for t, raw in results.items():
        d = get_latest(raw)
        rows.append({
            "銘柄": t,
            "企業名": d.get("name", ""),
            "セクター": d.get("sector", ""),
            "地力": d.get("scores", {}).get("fundamental", 0),
            "割安度": d.get("scores", {}).get("valuation", 0),
            "タイミング": d.get("scores", {}).get("technical", 0),
            "定性": d.get("scores", {}).get("qualitative", 0),
            "総合": d.get("total_score", 0),
            "判定": d.get("signal", "WATCH"),
            "履歴": len(raw.get("history", [])),
        })

    import pandas as pd
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True)
