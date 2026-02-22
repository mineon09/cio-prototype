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
import re
import time
import streamlit as st
from datetime import datetime

# プロジェクトルートをパスに追加
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

# 環境変数を先にロード（明示的パス指定でStreamlit起動時のCWDずれに対応）
from dotenv import load_dotenv
_env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(_env_path, override=True)

# ============================================================
# Secrets Bridge: Streamlit Cloud ↔ ローカル .env
# ============================================================
# Streamlit Cloud では st.secrets から、ローカルでは .env から読み込む
try:
    for key in ["GEMINI_API_KEY", "GROQ_API_KEY", "EDINET_API_KEY", "SPREADSHEET_ID",
                 "GOOGLE_SERVICE_ACCOUNT_JSON",
                 "LINE_CHANNEL_ACCESS_TOKEN", "LINE_USER_ID"]:
        if key in st.secrets:
            os.environ[key] = st.secrets[key]
except Exception:
    pass  # st.secrets が使えない場合（ローカル）はスキップ

from src.data_fetcher import fetch_stock_data, select_competitors, call_gemini
from src.analyzers import generate_scorecard, format_yuho_for_prompt
from src.edinet_client import extract_yuho_data, is_japanese_stock

try:
    from src.sec_client import extract_sec_data, is_us_stock
except ImportError:
    def is_us_stock(ticker): return not ticker.endswith('.T')
    def extract_sec_data(ticker): return {}

try:
    from src.dcf_model import estimate_fair_value
except ImportError:
    def estimate_fair_value(ticker): return {"available": False}

try:
    from src.macro_regime import detect_regime
except ImportError:
    def detect_regime(): return {}

from src.notifier import send_line_push
from src.utils import load_config_with_overrides
from main import analyze_all, save_to_dashboard_json, run_strategy_analysis


# ============================================================
# Page Config
# ============================================================
st.set_page_config(
    page_title="CIO インテリジェンス分析",
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
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            st.error(f"⚠️ 分析結果データが破損しています: {e}")
            return {}
    return {}

def get_latest(ticker_data):
    if ticker_data.get("history"):
        # APP-002: 元のデータを壊さないようコピーを使用
        latest = dict(ticker_data["history"][-1])
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
    st.title("🤖 CIO インテリジェンス")
    st.markdown("---")

    # Ticker Input
    # Ticker Input
    st.subheader("📈 銘柄分析")
    ticker_input = st.text_input(
        "ティッカー入力",
        placeholder="例: AMAT, 7203.T",
        help="米国株はそのまま、日本株は .T 付きで入力"
    )

    # Strategy Selection
    st.caption("戦略設定")
    strategy = st.selectbox(
        "戦略を選択",
        ["long", "bounce", "breakout"],
        index=0,
        help="long: 割安優良株, bounce: 短期リバウンド, breakout: 高値ブレイク"
    )

    run_analysis = st.button("🚀 分析実行", type="primary", width="stretch")

    # Backtest Controls
    with st.expander("🛠️ バックテスト設定"):
        bt_days = st.number_input("期間 (日)", value=365, step=30)
        # start date defaults to 1 year ago? or manual?
        # backtester.py takes --start YYYY-MM-DD and --days (or months)
        # Let's use simple text or date input
        default_start = datetime.now().replace(year=datetime.now().year - 1)
        bt_start = st.date_input("開始日", value=default_start)

    run_backtest_btn = st.button("▶️ バックテスト実行", width="stretch")

    st.markdown("---")
    st.subheader("🔑 APIステータス")
    from src.data_fetcher import _get_gemini_key, _get_groq_key, HAS_GROQ
    gemini_ok = bool(_get_gemini_key())
    groq_ok = bool(_get_groq_key())
    
    st.write(f"Gemini: {'✅' if gemini_ok else '❌'}")
    st.write(f"Groq SDK: {'✅' if HAS_GROQ else '❌ (pip install groq)'}")
    st.write(f"Groq Key: {'✅' if groq_ok else '❌'}")

    if not gemini_ok and not groq_ok:
        st.error("APIキーが設定されていません。 .env またはクラウドの Secrets を確認してください。")

    # Groq接続テスト
    if HAS_GROQ and groq_ok:
        if st.button("🧪 Groq接続テスト"):
            try:
                from groq import Groq as GroqTest
                c = GroqTest(api_key=_get_groq_key())
                r = c.chat.completions.create(
                    model='llama-3.3-70b-versatile',
                    messages=[{'role':'user','content':'Say hello in Japanese'}],
                    max_tokens=20
                )
                st.success(f"✅ Groq接続OK: {r.choices[0].message.content}")
            except Exception as e:
                st.error(f"❌ Groq接続テスト失敗: {e}")

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
            
            # 履歴ボタンのラベルに戦略名も含めると分かりやすいかも
            strat_label = d.get("strategy", "long")
            
            if st.sidebar.button(
                f"{emoji} {t} ({strat_label}) — {d.get('name', '')[:10]} ({score:.1f})",
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
    # バリデーション: 英数字、ドット(.)、ハイフン(-)、スペースのみ許可
    if not re.match(r'^[A-Za-z0-9\.\-\s]+$', ticker_input):
        st.error("⚠️ 無効な文字が含まれています。英数字、ドット(.)、ハイフン(-) のみ使用可能です。")
        st.stop()
    
    ticker = ticker_input.strip().upper()
    st.session_state["view_ticker"] = ticker

    with st.status(f"🔍 {ticker} を分析中...", expanded=True) as status:
        # Step 0: Load Config
        st.write("⚙️ 設定読み込み中...")
        from src.utils import load_config_with_overrides
        config = load_config_with_overrides(ticker)
    
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
        base_scorecard = generate_scorecard(
            target_data.get("metrics", {}),
            target_data.get("technical", {}),
            yuho_data,
            sector=sector,
            dcf_data=dcf_data,
            macro_data=macro_data,
        )
        
        # Step 6.5: Run Strategy Analysis (Shared Logic)
        st.write(f"🔬 戦略分析実行中 ({strategy})...")
        # APP-007: config読み込みを統合（Step 0で実施済みだが、念のためこの文脈で使用する変数として保持）
        scorecard = run_strategy_analysis(ticker, strategy, base_scorecard, macro_data, config)
        
        # 保存用に戦略名を記録
        scorecard["strategy"] = strategy

        # Step 7: Report (Gemini)
        st.write("📝 最終レポート生成中...")
        from main import analyze_all, save_to_dashboard_json
        
        report, table_str, model_name = analyze_all(
            ticker, {ticker: target_data}, competitors,
            yuho_data=yuho_data, scorecard=scorecard,
        )

        # Save
        # APP-003: model_name を渡すよう修正
        save_to_dashboard_json(ticker, target_data, scorecard, report,
                               dcf_data=dcf_data, macro_data=macro_data, model_name=model_name)

        status.update(label=f"✅ {ticker} 分析完了!", state="complete")

    # Reload results
    results = load_results()

# ============================================================
# Run Backtest
# ============================================================
if run_backtest_btn and ticker_input:
    # APP-001: バックテスト実行時もティッカーをバリデーション
    if not re.match(r'^[A-Za-z0-9\.\-\s]+$', ticker_input):
        st.error("⚠️ 無効な文字が含まれています。英数字、ドット(.)、ハイフン(-) のみ使用可能です。")
        st.stop()
        
    ticker = ticker_input.strip().upper()
    st.session_state["view_ticker"] = ticker # Switch view to this ticker if needed, or just show result

    with st.status(f"🛠️ {ticker} のバックテストを実行中...", expanded=True) as status:
        st.write(f"Strategy: {strategy}, Start: {bt_start}, Duration: {bt_days} days")
        
        # Convert params
        start_str = bt_start.strftime("%Y-%m-%d")
        months = int(bt_days / 30)
        if months < 1: months = 1
        
        from src.backtester import run_backtest
        # CLI overrides are not needed here as we want to use the config.json + ticker_overrides
        # But run_backtest handles config loading internally. 
        # We might want to pass explicit overrides if we had UI controls for them.
        # For now, rely on config.json
        
        try:
            # Capture stdout to show logs? 
            # run_backtest prints to stdout provided by sys.stdout override in backtest.py, 
            # but here in Streamlit it goes to console.
            # We can rely on the return value.
            
            result = run_backtest(ticker, start_str, months, strategy=strategy)
            
            if "error" in result:
                st.error(f"バックテストエラー: {result['error']}")
                status.update(label="❌ エラー発生", state="error")
            else:
                st.session_state["backtest_result"] = result
                st.session_state["backtest_ticker"] = ticker
                st.session_state["backtest_strategy"] = strategy
                status.update(label="✅ バックテスト完了!", state="complete")
        except Exception as e:
            st.error(f"実行例外: {e}")
            status.update(label="❌ 例外発生", state="error")

# ============================================================
# Main View
# ============================================================
view_ticker = st.session_state.get("view_ticker")

# Check if we should show Backtest Results
if st.session_state.get("backtest_result") and st.session_state.get("backtest_ticker") == view_ticker:
    # ── Backtest View ──
    st.title(f"🛠️ バックテスト結果: {view_ticker}")
    res = st.session_state["backtest_result"]
    
    st.caption(f"Strategy: {st.session_state.get('backtest_strategy')} | Period: {res.get('period')}")
    
    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Return", f"{res.get('total_return_pct')}%")
    c2.metric("Alpha", f"{res.get('alpha')}%")
    c3.metric("Max Drawdown", f"{res.get('max_drawdown_pct')}%")
    c4.metric("Sharpe Ratio", res.get('sharpe_ratio'))
    
    # Chart
    # APP-004: 中国語 typo 修正 (资产 -> 資産)
    st.subheader("資産推移 (Equity Curve)")
    if "history" in res:
        import pandas as pd
        hist_df = pd.DataFrame(res["history"])
        if not hist_df.empty:
            hist_df['date'] = pd.to_datetime(hist_df['date'])
            hist_df = hist_df.set_index('date')
            st.line_chart(hist_df['value'])
    
    # Trades
    st.subheader("売買履歴")
    if "trades" in res:
        trades_df = pd.DataFrame(res["trades"])
        st.dataframe(trades_df, use_container_width=True)
        
    if st.button("🔙 分析結果に戻る"):
        del st.session_state["backtest_result"]
        st.rerun()
    
    st.markdown("---")

elif view_ticker and view_ticker in results:
    # 戻るボタン (メインエリア)
    if st.button("🔙 一覧に戻る", key="back_to_list_main"):
        del st.session_state["view_ticker"]
        st.rerun()

    raw = results[view_ticker]
    data = get_latest(raw)
    scores = data.get("scores", {})
    metrics = data.get("metrics", {})
    tech = data.get("technical_data", {})
    dcf = data.get("dcf", {})
    macro = data.get("macro", {})
    
    current_strategy = data.get("strategy", "long")

    # ── Header ──
    col1, col2, col3, col4 = st.columns([3, 1, 1, 2])
    with col1:
        st.title(f"{view_ticker}")
        st.caption(f"{data.get('name', '')} | {data.get('sector', '')} | {data.get('date', '')} | Strategy: {current_strategy}")
    with col2:
        total = data.get("total_score", 0)
        color = score_color(total)
        st.markdown(f'<div class="score-big" style="color:{color}">{total:.1f}</div>', unsafe_allow_html=True)
        st.caption("総合スコア")
    with col3:
        signal = data.get("signal", "WATCH")
        st.markdown(f'<div class="signal-{signal.lower()}">{signal}</div>', unsafe_allow_html=True)
        
        # 個別銘柄の通知ボタン
        if st.button("📲 LINE送付", key=f"notify_{view_ticker}", width="stretch"):
            msg = f"\n🤖 CIO Analysis: {view_ticker}\n判定: {signal}\nスコア: {total:.1f}/10\n\n{data.get('report', '')[:200]}..."
            if send_line_push(msg):
                st.success("LINEに送信しました")
            else:
                st.error("送信失敗。Secrets設定を確認してください")

    with col4:
        if macro:
            regime = macro.get("regime", "")
            st.metric("🌍 Regime", regime)
            st.caption(macro.get("description", "")[:60])

    st.markdown("---")
    
    # ── Strategy Details (New) ──
    if "strategy_details" in data:
        with st.expander("🔬 戦略判定の詳細 (Strategy Details)", expanded=True):
            st.info(f"適用戦略: {current_strategy.upper()}")
            
            # シンプルなリスト表示
            for detail in data["strategy_details"]:
                if "OK" in detail:
                    st.markdown(f"- ✅ {detail}")
                elif "NG" in detail:
                    st.markdown(f"- ❌ {detail}")
                else:
                    st.markdown(f"- {detail}")
            
            # メトリクスがあれば表示
            if "strategy_metrics" in data:
                sm = data["strategy_metrics"]
                st.json(sm) # デバッグ用にJSON表示、あるいは綺麗に整形しても良い

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
            ("営業利益率", f"{metrics.get('op_margin', '-')}%"),
            ("RSI", f"{float(tech.get('rsi', 0)):.1f}" if tech.get('rsi') else "-"),
            ("株価", f"${float(tech.get('current_price', 0)):,.0f}" if tech.get('current_price') else "-"),
        ]
        for j, (label, val) in enumerate(items):
            with m_cols[j % 3]:
                st.metric(label, val)

    with col_right:
        _fv_raw = dcf.get("fair_value", 0) if dcf else 0
        _fv_valid = isinstance(_fv_raw, (int, float)) and _fv_raw > 0 and not (isinstance(_fv_raw, float) and (_fv_raw != _fv_raw))  # NaN check
        if dcf and _fv_valid:
            st.subheader("💰 DCF理論株価")
            fv = _fv_raw
            cp = dcf.get("current_price", 0) or 0
            upside = dcf.get("upside", 0) or 0
            mos = dcf.get("margin_of_safety", 0) or 0

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
                    sc_gr = sc.get('growth_rate', 0) or 0
                    sc_fv = sc.get('fair_value', 0) or 0
                    if isinstance(sc_fv, float) and sc_fv != sc_fv:  # NaN check
                        sc_fv = 0
                    st.caption(f"{emoji} {label}: 成長率 {sc_gr}% → ${sc_fv:,.0f}")
        else:
            st.subheader("📈 テクニカル")
            st.metric("RSI", f"{float(tech.get('rsi', 0)):.1f}" if tech.get('rsi') else "-")
            st.metric("MA25乖離", f"{float(tech.get('ma25_deviation', 0)):.1f}%" if tech.get('ma25_deviation') else "-")

    st.markdown("---")

    # ── Trend Chart ──
    history = raw.get("history", [])
    if len(history) >= 2:
        st.subheader("📈 スコア推移")
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
    st.subheader("📝 分析レポート")
    report_text = data.get("report", "")
    if report_text:
        st.markdown(report_text.replace("\n", "\n\n"))
    else:
        st.info("レポートがありません")

elif not results:
    st.title("🤖 CIO Intelligence Dashboard")
    st.info("👈 サイドバーからティッカーを入力して分析を実行してください")
else:
    st.title("🤖 CIO インテリジェンス・ダッシュボード")

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

    # st.dataframe の selection 機能を使用 (Streamlit 1.35+)
    event = st.dataframe(
        df,
        width=1000,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    if event and event.selection and event.selection.rows:
        selected_index = event.selection.rows[0]
        selected_ticker = df.iloc[selected_index]["銘柄"]
        st.session_state["view_ticker"] = selected_ticker
        st.rerun()
