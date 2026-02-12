"""
main.py - CIO司令塔 エントリーポイント
=======================================
銘柄コードを入力すると：
1. yfinanceで財務・テクニカルデータを取得
2. GeminiAPIが比較対象（外資競合）を自動選定
3. 外資との対戦表を生成
4. 地力分析 × タイミング分析の2層で分析
5. BUY/WATCH/SELLの最終判断をGoogle Sheetsに出力

使い方:
  python main.py              # 対話モード
  python main.py 7203.T       # 銘柄を引数で指定
  python main.py 7203.T AAPL  # 複数銘柄
"""

import os
import sys
import re
import json
import time
import gspread
import yfinance as yf
from datetime import datetime, timedelta
from google import genai
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 環境変数
# ==========================================
GEMINI_API_KEY            = os.environ.get('GEMINI_API_KEY')
SPREADSHEET_ID            = os.environ.get('SPREADSHEET_ID')
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')

try:
    with open("config.json", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {
        "competitor_selection": {"direct_count": 3, "substitute_count": 2, "benchmark_count": 2},
        "sheets": {"output": "分析結果"}
    }

# ==========================================
# 1. yfinance データ取得
# ==========================================

def fetch_stock_data(ticker: str) -> dict:
    """
    yfinanceから財務・テクニカル・ニュースを一括取得し、
    Geminiに渡す「統一データ構造」を返す。
    """
    print(f"  📊 {ticker} データ取得中...")
    stock = yf.Ticker(ticker)
    info  = stock.info
    hist  = stock.history(period="1y")
    fin   = stock.financials
    cf    = stock.cashflow
    bs    = stock.balance_sheet

    metrics = {}

    def safe_get_metric(df, row_name):
        try:
            return df.loc[row_name].iloc[0]
        except (KeyError, IndexError, AttributeError):
            return None

    # 営業利益率
    op = safe_get_metric(fin, 'Operating Income')
    rev = safe_get_metric(fin, 'Total Revenue')
    if op and rev: metrics['op_margin'] = round(op / rev * 100, 1)

    # 純利益率
    ni = safe_get_metric(fin, 'Net Income')
    if ni and rev: metrics['net_margin'] = round(ni / rev * 100, 1)

    # R&D / 売上比
    rd = safe_get_metric(fin, 'Research And Development')
    if rd and rev: metrics['rd_ratio'] = round(abs(rd) / rev * 100, 1)

    # CF品質
    ocf = safe_get_metric(cf, 'Operating Cash Flow')
    if ocf and ni: metrics['cf_quality'] = round(ocf / ni, 2)

    # 自己資本比率
    eq = safe_get_metric(bs, 'Stockholders Equity')
    ta = safe_get_metric(bs, 'Total Assets')
    if eq and ta: metrics['equity_ratio'] = round(eq / ta * 100, 1)

    # info から取得
    metrics['roe']             = round(info.get('returnOnEquity', 0) * 100, 1) if info.get('returnOnEquity') else None
    metrics['revenue_growth']  = round(info.get('revenueGrowth', 0) * 100, 1)  if info.get('revenueGrowth')  else None
    metrics['earnings_growth'] = round(info.get('earningsGrowth', 0) * 100, 1) if info.get('earningsGrowth') else None
    metrics['per']             = info.get('forwardPE')
    metrics['pbr']             = info.get('priceToBook')
    metrics['dividend_yield']  = round(info.get('dividendYield', 0) * 100, 2)  if info.get('dividendYield')  else None

    # ── テクニカル指標 ───────────────────────
    technical = {}
    if not hist.empty:
        cur  = hist['Close'].iloc[-1]
        ma25 = hist['Close'].rolling(25).mean().iloc[-1]
        ma75 = hist['Close'].rolling(75).mean().iloc[-1]

        delta = hist['Close'].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        
        rsi = 50.0
        if not loss.empty and loss.iloc[-1] != 0:
            rsi = round(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1]), 1)

        std   = hist['Close'].rolling(25).std().iloc[-1]
        bb_u  = ma25 + 2 * std
        bb_l  = ma25 - 2 * std

        technical = {
            'current_price':   round(cur, 2),
            'ma25':            round(ma25, 2),
            'ma75':            round(ma75, 2),
            'ma25_deviation':  round((cur - ma25) / ma25 * 100, 1) if ma25 else 0,
            'ma75_deviation':  round((cur - ma75) / ma75 * 100, 1) if ma75 else 0,
            'rsi':             rsi,
            'bb_position':     round((cur - bb_l) / (bb_u - bb_l) * 100, 1) if (bb_u - bb_l) != 0 else 50,
            'volatility':      round(hist['Close'].pct_change().std() * (252**0.5) * 100, 1),
            'volume_ratio':    round(info.get('volume', 0) / info.get('averageVolume', 1), 2),
            'analyst_target':  info.get('targetMeanPrice'),
        }

    # ── ニュース（過去7日）───────────────────
    cutoff = datetime.now() - timedelta(days=7)
    news = []
    for n in (stock.news or [])[:10]:
        pub = datetime.fromtimestamp(n.get('providerPublishTime', 0))
        if pub >= cutoff:
            news.append(f"[{pub.strftime('%m/%d')}] {n.get('title','')} ({n.get('publisher','')})")

    return {
        'ticker':    ticker,
        'name':      info.get('longName', ticker),
        'sector':    info.get('sector', '不明'),
        'industry':  info.get('industry', '不明'),
        'country':   info.get('country', '不明'),
        'currency':  info.get('currency', 'USD'),
        'market_cap': info.get('marketCap'),
        'description': (info.get('longBusinessSummary') or '')[:200],
        'metrics':   metrics,
        'technical': technical,
        'news':      news,
    }

# ==========================================
# 2. Gemini API 呼び出し
# ==========================================

def call_gemini(prompt: str, parse_json: bool = False, max_retries: int = 5):
    """Gemini API の呼び出し（429自動リトライ付き）"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(max_retries):
        try:
            res  = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=prompt
            )
            text = res.text
            if parse_json:
                m = re.search(r'\{.*\}', text, re.DOTALL)
                return json.loads(m.group(0)) if m else json.loads(text)
            return text

        except Exception as e:
            err = str(e)
            if '429' in err or 'RESOURCE_EXHAUSTED' in err:
                m = re.search(r'retry in (\d+\.?\d*)s', err)
                wait = float(m.group(1)) + 2 if m else 60
                if attempt < max_retries - 1:
                    print(f"⏳ レート制限 {wait:.0f}秒待機... ({attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
            elif '503' in err and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 15)
                continue
            print(f"❌ Gemini エラー: {e}")
            return None
    return None

# ==========================================
# 3. Gemini で比較対象を自動選定
# ==========================================

def select_competitors(target: dict) -> dict:
    cfg = CONFIG['competitor_selection']
    prompt = f"""
あなたは投資委員会のCIOです。以下の銘柄の「真の競争力」を評価するため、
最適な比較対象をJSON形式で選定してください。

【対象銘柄】
- ティッカー: {target['ticker']}
- 企業名: {target['name']}
- 概要: {target['description']}

【選定カテゴリ】
1. direct（直接競合）: {cfg['direct_count']}社
2. substitute（機能代替）: {cfg['substitute_count']}社
3. benchmark（資本効率比較用）: {cfg['benchmark_count']}社

【制約】
- yfinanceで取得可能なティッカーのみ（日本株は「7203.T」形式）
- JSONのみ返答（説明不要）

{{
  "direct":    ["TICKER1", "TICKER2"],
  "substitute": ["TICKER3"],
  "benchmark": ["TICKER4"],
  "reasoning": "選定理由"
}}
"""
    print("🧠 Gemini が比較対象を選定中...")
    result = call_gemini(prompt, parse_json=True)
    return result if result else {"direct": [], "substitute": [], "benchmark": [], "reasoning": "選定失敗"}

# ==========================================
# 4. 対戦表の生成
# ==========================================

def build_comparison_table(target_ticker: str, all_data: dict) -> str:
    labels = {
        'op_margin': '営業利益率(%)', 'roe': 'ROE(%)', 'revenue_growth': '売上成長率(%)',
        'cf_quality': 'CF品質', 'per': 'PER(倍)', 'pbr': 'PBR(倍)'
    }
    tickers = list(all_data.keys())
    header  = f"{'指標':<20} | " + " | ".join(f"{t:<10}" for t in tickers)
    sep     = "-" * len(header)
    rows    = [f"\n{'='*70}", f"📊 対戦表: {all_data[target_ticker].get('name', target_ticker)}", f"{'='*70}", header, sep]

    for key, label in labels.items():
        vals = [f"{all_data[t].get('metrics', {}).get(key) or 'N/A':<10}" for t in tickers]
        rows.append(f"{label:<20} | " + " | ".join(vals))
    return "\n".join(rows)

# ==========================================
# 5. Layer1: 地力分析
# ==========================================

def analyze_fundamental(target_ticker: str, all_data: dict, competitors: dict) -> dict:
    table = build_comparison_table(target_ticker, all_data)
    prompt = f"あなたは外資系ヘッジファンドのCIOです。以下の対戦表を分析し、競争優位性と市場のバグを発見してください。\n{table}\n【出力】箇条書き、本質的価値スコア(X/10)"
    print("⚔️  Layer1: 地力分析...")
    return {"analysis": call_gemini(prompt), "table": table}

# ==========================================
# 6. Layer2: タイミング分析
# ==========================================

def analyze_timing(target_ticker: str, target_data: dict, fundamental: dict) -> dict:
    tech = target_data.get('technical', {})
    prompt = f"地力分析結果を踏まえ、テクニカル指標 {tech} とニュース {target_data.get('news')} から、今がエントリーすべきか判断してください。タイミングスコア(X/10)"
    print("⏱️  Layer2: タイミング分析...")
    return {"analysis": call_gemini(prompt)}

# ==========================================
# 7. 最終投資判断
# ==========================================

def make_final_decision(target_ticker: str, target_data: dict, fundamental: dict, timing: dict) -> dict:
    prompt = f"地力分析: {fundamental['analysis']}\nタイミング分析: {timing['analysis']}\n以上を統合し、BUY/WATCH/SELLの最終判断を下してください。"
    print("✅  最終投資判断を生成中...")
    return {"decision": call_gemini(prompt)}

# ==========================================
# 8. Google Sheets 出力
# ==========================================

def write_to_sheets(gc, target_ticker: str, target_data: dict, competitors: dict, fundamental: dict, timing: dict, final: dict):
    try:
        sp = gc.open_by_key(SPREADSHEET_ID)
        sheet = sp.worksheet(CONFIG['sheets']['output'])
        dec = final.get('decision', '')
        sig = (re.search(r'(BUY|WATCH|SELL)', dec))
        score = re.search(r'(\d+)/10', dec)
        
        row = [
            datetime.now().strftime('%Y/%m/%d %H:%M'),
            target_ticker,
            f"{target_data['technical'].get('current_price')} {target_data.get('currency')}",
            sig.group(1) if sig else "N/A",
            score.group(0) if score else "N/A",
            str(competitors.get('direct', [])),
            fundamental.get('analysis'),
            timing.get('analysis'),
            dec,
            fundamental.get('table')
        ]
        sheet.append_row(row)
        print("✅ スプレッドシート書き込み完了")
    except Exception as e: print(f"❌ Sheetsエラー: {e}")

# ==========================================
# 9. メインフロー
# ==========================================

def run(ticker: str, gc=None):
    target_data = fetch_stock_data(ticker)
    competitors = select_competitors(target_data)
    
    all_tickers = list(set([ticker] + competitors.get('direct', []) + competitors.get('substitute', []) + competitors.get('benchmark', [])))
    all_data = {}
    for t in all_tickers:
        all_data[t] = fetch_stock_data(t) if t != ticker else target_data
        time.sleep(0.3)

    fundamental = analyze_fundamental(ticker, all_data, competitors)
    timing = analyze_timing(ticker, target_data, fundamental)
    final = make_final_decision(ticker, target_data, fundamental, timing)

    if gc:
        write_to_sheets(gc, ticker, target_data, competitors, fundamental, timing, final)
    
    print("\n" + "="*60 + "\n" + final.get('decision', '') + "\n" + "="*60)

def main():
    if not GEMINI_API_KEY: sys.exit(1)
    gc = None
    if GOOGLE_SERVICE_ACCOUNT_JSON and SPREADSHEET_ID:
        try:
            creds = Credentials.from_service_account_info(json.loads(GOOGLE_SERVICE_ACCOUNT_JSON), 
                    scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
            gc = gspread.authorize(creds)
        except Exception: pass

    args = sys.argv[1:]
    combined = " ".join(args).replace('　', ' ')
    raw_list = combined.split()
    tickers, skip_next = [], False

    for i, arg in enumerate(raw_list):
        if skip_next:
            skip_next = False; continue
        if arg.lower() == "--ticker":
            if i + 1 < len(raw_list):
                tickers.append(raw_list[i+1].upper()); skip_next = True
        elif not arg.startswith("--"):
            tickers.append(arg.upper())

    if not tickers: sys.exit(1)

    for i, t in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}] {t}")
        try: run(t, gc)
        except Exception as e: print(f"❌ {t} 失敗: {e}")
        if i < len(tickers) - 1: time.sleep(5)

if __name__ == "__main__":
    main()
