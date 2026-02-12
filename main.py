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

with open("config.json", encoding="utf-8") as f:
    CONFIG = json.load(f)


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

    # ── 財務指標 ────────────────────────────
    metrics = {}

    # 営業利益率
    try:
        op  = fin.loc['Operating Income'].iloc[0]
        rev = fin.loc['Total Revenue'].iloc[0]
        metrics['op_margin'] = round(op / rev * 100, 1) if rev else None
    except: pass

    # 純利益率
    try:
        ni  = fin.loc['Net Income'].iloc[0]
        rev = fin.loc['Total Revenue'].iloc[0]
        metrics['net_margin'] = round(ni / rev * 100, 1) if rev else None
    except: pass

    # R&D / 売上比
    try:
        rd  = abs(fin.loc['Research And Development'].iloc[0])
        rev = fin.loc['Total Revenue'].iloc[0]
        metrics['rd_ratio'] = round(rd / rev * 100, 1) if rev else None
    except: pass

    # CF品質（利益の質）= 営業CF / 純利益
    try:
        ocf = cf.loc['Operating Cash Flow'].iloc[0]
        ni  = fin.loc['Net Income'].iloc[0]
        metrics['cf_quality'] = round(ocf / ni, 2) if ni else None
    except: pass

    # 自己資本比率
    try:
        eq = bs.loc['Stockholders Equity'].iloc[0]
        ta = bs.loc['Total Assets'].iloc[0]
        metrics['equity_ratio'] = round(eq / ta * 100, 1) if ta else None
    except: pass

    # info から取れる指標
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
        rsi   = round(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1]), 1)

        std   = hist['Close'].rolling(25).std().iloc[-1]
        bb_u  = ma25 + 2 * std
        bb_l  = ma25 - 2 * std

        technical = {
            'current_price':   round(cur, 2),
            'ma25':            round(ma25, 2),
            'ma75':            round(ma75, 2),
            'ma25_deviation':  round((cur - ma25) / ma25 * 100, 1),
            'ma75_deviation':  round((cur - ma75) / ma75 * 100, 1),
            'rsi':             rsi,
            'bb_position':     round((cur - bb_l) / (bb_u - bb_l) * 100, 1),
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
    """
    対象銘柄の基本情報を渡し、Geminiに外資競合を選ばせる。
    直接競合 / 機能代替 / 資本効率ベンチマーク の3カテゴリ。
    """
    cfg = CONFIG['competitor_selection']
    prompt = f"""
あなたは投資委員会のCIOです。以下の銘柄の「真の競争力」を評価するため、
最適な比較対象をJSON形式で選定してください。

【対象銘柄】
- ティッカー: {target['ticker']}
- 企業名: {target['name']}
- 業種: {target['sector']} / {target['industry']}
- 国: {target['country']}
- 概要: {target['description']}

【選定カテゴリ】
1. direct（直接競合）: {cfg['direct_count']}社
2. substitute（機能代替）: {cfg['substitute_count']}社
3. benchmark（資本効率比較用）: {cfg['benchmark_count']}社

【制約】
- yfinanceで取得可能なティッカーのみ（日本株は「7203.T」形式）
- JSONのみ返答（説明不要）

{{
  "direct":    ["TICKER1", "TICKER2", "TICKER3"],
  "substitute": ["TICKER4", "TICKER5"],
  "benchmark": ["TICKER6", "TICKER7"],
  "reasoning": "選定理由を1-2行"
}}
"""
    print("🧠 Gemini が比較対象を選定中...")
    result = call_gemini(prompt, parse_json=True)
    if not result:
        return {"direct": [], "substitute": [], "benchmark": [], "reasoning": "選定失敗"}

    all_c = result.get('direct', []) + result.get('substitute', []) + result.get('benchmark', [])
    print(f"✅ 比較対象: {all_c}")
    print(f"   理由: {result.get('reasoning', '')}")
    return result


# ==========================================
# 4. 対戦表の生成
# ==========================================

def build_comparison_table(target_ticker: str, all_data: dict) -> str:
    """全銘柄の財務指標を横並びにした対戦表を文字列で生成"""
    labels = {
        'op_margin':       '営業利益率(%)',
        'net_margin':      '純利益率(%)',
        'roe':             'ROE(%)',
        'revenue_growth':  '売上成長率(%)',
        'rd_ratio':        'R&D/売上比(%)',
        'cf_quality':      'CF品質',
        'equity_ratio':    '自己資本比率(%)',
        'per':             'PER(倍)',
        'pbr':             'PBR(倍)',
        'dividend_yield':  '配当利回り(%)',
    }
    tickers = list(all_data.keys())
    header  = f"{'指標':<20} | " + " | ".join(f"{t:<10}" for t in tickers)
    sep     = "-" * len(header)
    rows    = [f"\n{'='*70}", f"📊 対戦表: {all_data[target_ticker].get('name', target_ticker)}", f"{'='*70}", header, sep]

    for key, label in labels.items():
        vals = []
        for t in tickers:
            v = all_data[t].get('metrics', {}).get(key)
            vals.append(f"{v:<10}" if v is not None else f"{'N/A':<10}")
        rows.append(f"{label:<20} | " + " | ".join(vals))

    rows.append("=" * 70)
    return "\n".join(rows)


# ==========================================
# 5. Layer1: 地力分析（外資対戦表をGeminiに渡す）
# ==========================================

def analyze_fundamental(target_ticker: str, all_data: dict, competitors: dict) -> dict:
    table = build_comparison_table(target_ticker, all_data)
    prompt = f"""
あなたは外資系ヘッジファンドのCIOです。
以下の対戦表を分析し、「市場が見落としている本質的価値のバグ」を発見してください。

【比較の文脈】
{competitors.get('reasoning', '')}

{table}

【出力形式】
💪 競争優位性:
[箇条書き3項目・数値根拠必須]

⚠️ 競争劣位性:
[箇条書き2項目]

🐛 市場のバグ（非効率性）:
[「PER〇倍はXXと比較して〇倍過小評価」など数値で表現]

📊 本質的価値スコア: X/10
[根拠2行]
"""
    print("⚔️  Layer1: 地力分析（外資対戦表）...")
    result = call_gemini(prompt)
    return {"analysis": result, "table": table}


# ==========================================
# 6. Layer2: タイミング分析（ニュース×テクニカル）
# ==========================================

def analyze_timing(target_ticker: str, target_data: dict, fundamental: dict) -> dict:
    tech = target_data.get('technical', {})
    news_text = "\n".join(target_data.get('news', [])) or "ニュースなし"

    prompt = f"""
あなたは外資系ヘッジファンドのCIOです。
地力分析の結果を踏まえ、「今がエントリーすべきタイミングか」を判断してください。

【Layer1 地力分析の結果】
{fundamental.get('analysis', 'N/A')}

【テクニカル指標】
現在価格: {tech.get('current_price')} {target_data.get('currency')}
MA25乖離: {tech.get('ma25_deviation')}% / MA75乖離: {tech.get('ma75_deviation')}%
RSI: {tech.get('rsi')} / ボリンジャー位置: {tech.get('bb_position')}%
ボラティリティ(年率): {tech.get('volatility')}% / 出来高比: {tech.get('volume_ratio')}x
アナリスト目標: {tech.get('analyst_target')}

【最近のニュース（7日）】
{news_text}

【出力形式】
📰 センチメント: [ポジティブ/ネガティブ/中立] 強度[高/中/低]
[根拠2行]

📈 テクニカル: [過熱/適正/割安]
[根拠2行]
⚠️ 指標の矛盾: [あれば記載、なければ「矛盾なし」]

📅 今後のカタリスト: [具体的イベント・日付]

⏱️ タイミングスコア: X/10
"""
    print("⏱️  Layer2: タイミング分析（ニュース×テクニカル）...")
    result = call_gemini(prompt)
    return {"analysis": result}


# ==========================================
# 7. 最終投資判断
# ==========================================

def make_final_decision(target_ticker: str, target_data: dict,
                         fundamental: dict, timing: dict) -> dict:
    tech = target_data.get('technical', {})
    prompt = f"""
あなたは外資系ヘッジファンドのCIOです。
2層の分析を統合し、最終投資判断を下してください。

【Layer1 地力分析】
{fundamental.get('analysis', 'N/A')}

【Layer2 タイミング分析】
{timing.get('analysis', 'N/A')}

現在価格: {tech.get('current_price')} {target_data.get('currency')}

【判断基準】
BUY:   地力7以上 かつ タイミング7以上
WATCH: 地力5〜7、またはタイミング待ち
SELL:  地力4以下、または致命的リスク発見

【出力形式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏆 最終判断: {target_ticker}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 シグナル: BUY / WATCH / SELL
📊 地力スコア: X/10
⏱️ タイミングスコア: X/10
🔢 総合スコア: X/10

【根拠】[3行]

【アクション】
- エントリー価格: XXX
- 損切りライン:   XXX（理由:）
- 利確ライン:     XXX（理由:）
- ポジションサイズ: ポートフォリオの X%

【出口戦略】
- 利確条件: [価格 or イベント]
- 損切り条件: [価格 AND ファンダメンタル変化]

【監視ポイント】
1. 
2. 
"""
    print("✅  最終投資判断を生成中...")
    result = call_gemini(prompt)
    return {"decision": result}


# ==========================================
# 8. Google Sheets 出力
# ==========================================

def write_to_sheets(gc, target_ticker: str, target_data: dict,
                    competitors: dict, fundamental: dict,
                    timing: dict, final: dict):
    try:
        sp    = gc.open_by_key(SPREADSHEET_ID)
        sname = CONFIG['sheets']['output']
        try:
            sheet = sp.worksheet(sname)
        except:
            sheet = sp.add_worksheet(sname, rows=1000, cols=10)
            sheet.append_row(["日付", "銘柄", "価格", "シグナル", "総合スコア",
                               "比較対象", "地力分析", "タイミング分析", "最終判断", "対戦表"])

        dec   = final.get('decision', '')
        sig   = (re.search(r'シグナル.*?(BUY|WATCH|SELL)', dec) or re.search(r'(BUY|WATCH|SELL)', dec))
        score = re.search(r'総合スコア.*?(\d+)/10', dec)
        tech  = target_data.get('technical', {})

        row = [
            datetime.now().strftime('%Y/%m/%d %H:%M'),
            target_ticker,
            f"{tech.get('current_price','N/A')} {target_data.get('currency','')}",
            sig.group(1) if sig else "N/A",
            f"{score.group(1)}/10" if score else "N/A",
            str(competitors.get('direct', []) + competitors.get('substitute', [])),
            fundamental.get('analysis', ''),
            timing.get('analysis', ''),
            dec,
            fundamental.get('table', ''),
        ]
        sheet.append_row(row)

        last = len(sheet.get_all_values())
        sheet.format(f"G{last}:J{last}", {"wrapStrategy": "WRAP"})
        print(f"✅ スプレッドシート書き込み完了（行 {last}）")

    except Exception as e:
        print(f"❌ スプレッドシートエラー: {e}")


# ==========================================
# 9. メインフロー
# ==========================================

def run(ticker: str, gc=None):
    print(f"\n{'='*60}")
    print(f"🚀 {ticker} の司令塔分析を開始")
    print(f"{'='*60}")

    # Step1: 対象銘柄のデータ取得
    target_data = fetch_stock_data(ticker)

    # Step2: Geminiが比較対象を自動選定
    competitors = select_competitors(target_data)

    # Step3: 比較対象のデータを一括取得
    all_tickers = list(set(
        competitors.get('direct', []) +
        competitors.get('substitute', []) +
        competitors.get('benchmark', [])
    ))
    print(f"\n📈 比較対象 {len(all_tickers)} 銘柄のデータ取得中...")
    all_data = {ticker: target_data}
    for t in all_tickers:
        all_data[t] = fetch_stock_data(t)
        time.sleep(0.3)

    # Step4: Layer1 地力分析（外資対戦表 → Gemini）
    fundamental = analyze_fundamental(ticker, all_data, competitors)

    # Step5: Layer2 タイミング分析（ニュース×テクニカル → Gemini）
    timing = analyze_timing(ticker, target_data, fundamental)

    # Step6: 最終判断
    final = make_final_decision(ticker, target_data, fundamental, timing)

    # Step7: Google Sheetsに出力
    if gc:
        write_to_sheets(gc, ticker, target_data, competitors, fundamental, timing, final)

    print("\n" + "="*60)
    print(final.get('decision', ''))
    print("="*60)
    return final


def main():
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY が未設定です")
        sys.exit(1)

    # Google Sheets 認証
    gc = None
    if GOOGLE_SERVICE_ACCOUNT_JSON and SPREADSHEET_ID:
        try:
            scopes = ['https://www.googleapis.com/auth/spreadsheets',
                      'https://www.googleapis.com/auth/drive']
            # JSON文字列を正しくパースして認証
            creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
            creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
            gc = gspread.authorize(creds)
            print("✅ Google Sheets 認証成功")
        except Exception as e:
            print(f"⚠️ Google Sheets 認証失敗（出力なしで続行）: {e}")

    # --- 修正ポイント：ここから ---
    # GitHub Actions から "--ticker 7203.T" のように渡されるケースに対応
# --- 修正ポイント：ここから ---
    args = sys.argv[1:]
    tickers = []
    
    if args:
        # 引数リスト全体を一度文字列として結合し、全角スペースを考慮して分割し直す
        # これにより "AMAT　XOM" (全角) も ["AMAT", "XOM"] に分解されます
        combined_args = " ".join(args).replace('　', ' ')
        raw_list = combined_args.split()
        
        temp_tickers = []
        skip_next = False
        for i, arg in enumerate(raw_list):
            if skip_next:
                skip_next = False
                continue
            if arg.lower() == "--ticker":
                if i + 1 < len(raw_list):
                    temp_tickers.append(raw_list[i+1].upper())
                    skip_next = True
            else:
                # -- から始まらない純粋な銘柄コードだけを追加
                if not arg.startswith("--"):
                    temp_tickers.append(arg.upper())
        tickers = temp_tickers
    else:
        # 対話モード
        print("\n🤖 AI投資司令")
    if not tickers:
        print("❌ 銘柄コードが入力されていません")
        sys.exit(1)

    # 全銘柄を分析
    for i, ticker in enumerate(tickers):
        # 万が一 "--TICKER" という文字列が混入していたらスキップ
        if ticker.startswith("--"):
            continue
            
        print(f"\n[{i+1}/{len(tickers)}] {ticker}")
        try:
            run(ticker, gc)
        except Exception as e:
            print(f"❌ {ticker} の分析中にエラーが発生しました: {e}")
            
        if i < len(tickers) - 1:
            print("⏳ 5秒待機...")
            time.sleep(5)

    if gc:
        print(f"\n📊 結果: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")