"""
main.py - CIO司令塔 エントリーポイント
=======================================
API呼び出し: 2回のみ
  1回目: Geminiが比較対象を自動選定（JSON）
  2回目: 対戦表 + 地力分析 + タイミング分析 + 最終判断を一括生成

使い方:
  python main.py 7203.T
  python main.py 7203.T 8306.T AAPL
  python main.py --ticker AMAT
"""

import os, sys, re, json, time, gspread, yfinance as yf
from datetime import datetime, timedelta
from google import genai
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY              = os.environ.get('GEMINI_API_KEY')
SPREADSHEET_ID              = os.environ.get('SPREADSHEET_ID')
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
# Gemini API（429自動リトライ）
# ==========================================

def call_gemini(prompt: str, parse_json: bool = False, max_retries: int = 5):
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(max_retries):
        try:
            res  = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
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
                return None
            elif '503' in err and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 15)
                continue
            print(f"❌ Gemini エラー: {e}")
            return None
    return None


# ==========================================
# yfinance データ取得
# ==========================================

def fetch_stock_data(ticker: str) -> dict:
    print(f"  📊 {ticker} データ取得中...")
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        hist  = stock.history(period="1y")
        fin   = stock.financials
        cf    = stock.cashflow
        bs    = stock.balance_sheet
    except Exception as e:
        print(f"  ⚠️ {ticker} 取得失敗: {e}")
        return {"ticker": ticker, "name": ticker, "currency": "USD",
                "metrics": {}, "technical": {}, "news": [], "description": ""}

    def sg(df, row):
        try: return df.loc[row].iloc[0]
        except: return None

    metrics = {}
    op, rev, ni = sg(fin,'Operating Income'), sg(fin,'Total Revenue'), sg(fin,'Net Income')
    ocf, eq, ta = sg(cf,'Operating Cash Flow'), sg(bs,'Stockholders Equity'), sg(bs,'Total Assets')
    rd = sg(fin, 'Research And Development')

    if op  and rev: metrics['op_margin']    = round(op  / rev * 100, 1)
    if ni  and rev: metrics['net_margin']   = round(ni  / rev * 100, 1)
    if rd  and rev: metrics['rd_ratio']     = round(abs(rd) / rev * 100, 1)
    if ocf and ni:  metrics['cf_quality']   = round(ocf / ni, 2)
    if eq  and ta:  metrics['equity_ratio'] = round(eq  / ta * 100, 1)

    metrics['roe']             = round(info.get('returnOnEquity',  0) * 100, 1) if info.get('returnOnEquity')  else None
    metrics['revenue_growth']  = round(info.get('revenueGrowth',   0) * 100, 1) if info.get('revenueGrowth')   else None
    metrics['earnings_growth'] = round(info.get('earningsGrowth',  0) * 100, 1) if info.get('earningsGrowth')  else None
    metrics['per']             = info.get('forwardPE')
    metrics['pbr']             = info.get('priceToBook')
    metrics['dividend_yield']  = round(info.get('dividendYield', 0) * 100, 2)   if info.get('dividendYield')   else None

    # テクニカル
    technical = {}
    if not hist.empty:
        cur  = hist['Close'].iloc[-1]
        ma25 = hist['Close'].rolling(25).mean().iloc[-1]
        ma75 = hist['Close'].rolling(75).mean().iloc[-1]
        delta = hist['Close'].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = round(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1]), 1) if loss.iloc[-1] != 0 else 50.0
        std   = hist['Close'].rolling(25).std().iloc[-1]
        bb_u, bb_l = ma25 + 2*std, ma25 - 2*std
        technical = {
            'current_price': round(cur, 2),
            'ma25_deviation': round((cur-ma25)/ma25*100, 1) if ma25 else 0,
            'ma75_deviation': round((cur-ma75)/ma75*100, 1) if ma75 else 0,
            'rsi':            rsi,
            'bb_position':    round((cur-bb_l)/(bb_u-bb_l)*100, 1) if (bb_u-bb_l) != 0 else 50,
            'volatility':     round(hist['Close'].pct_change().std() * (252**0.5) * 100, 1),
            'volume_ratio':   round(info.get('volume', 0) / max(info.get('averageVolume', 1), 1), 2),
            'analyst_target': info.get('targetMeanPrice'),
        }

    # ニュース（7日）
    cutoff = datetime.now() - timedelta(days=7)
    news = [
        f"[{datetime.fromtimestamp(n.get('providerPublishTime',0)).strftime('%m/%d')}] {n.get('title','')} ({n.get('publisher','')})"
        for n in (stock.news or [])[:8]
        if datetime.fromtimestamp(n.get('providerPublishTime', 0)) >= cutoff
    ]

    return {
        'ticker': ticker, 'name': info.get('longName', ticker),
        'sector': info.get('sector','不明'), 'country': info.get('country','不明'),
        'currency': info.get('currency','USD'),
        'description': (info.get('longBusinessSummary') or '')[:200],
        'metrics': metrics, 'technical': technical, 'news': news,
    }


# ==========================================
# API呼び出し 1/2: 比較対象の自動選定
# ==========================================

def select_competitors(target: dict) -> dict:
    cfg = CONFIG['competitor_selection']
    prompt = f"""
投資委員会CIOとして、以下の銘銘柄の「真の競争力」を評価するための比較対象をJSONで選定せよ。

銘柄: {target['ticker']} / {target['name']} / {target.get('sector','不明')} / {target.get('country','不明')}
概要: {target.get('description','')[:150]}

カテゴリ:
- direct（直接競合）: {cfg['direct_count']}社
- substitute（機能代替）: {cfg['substitute_count']}社
- benchmark（資本効率比較）: {cfg['benchmark_count']}社

制約: yfinanceで取得可能なティッカーのみ。日本株は「7203.T」形式。JSONのみ返答。

{{"direct":["T1","T2","T3"],"substitute":["T4","T5"],"benchmark":["T6","T7"],"reasoning":"理由1行"}}
"""
    print("🧠 [API 1/2] 比較対象を選定中...")
    result = call_gemini(prompt, parse_json=True)
    if not result:
        return {"direct": [], "substitute": [], "benchmark": [], "reasoning": "選定失敗"}
    all_c = result.get('direct',[]) + result.get('substitute',[]) + result.get('benchmark',[])
    print(f"✅ 比較対象: {all_c}")
    return result


# ==========================================
# API呼び出し 2/2: 全分析を一括生成
# ==========================================

def analyze_all(target_ticker: str, all_data: dict, competitors: dict) -> tuple[str, str]:
    """
    地力分析 + タイミング分析 + 最終判断を1回のAPIで一括生成。
    (report_text, table_str) を返す。
    """
    labels = {
        'op_margin':'営業利益率(%)', 'net_margin':'純利益率(%)', 'roe':'ROE(%)',
        'revenue_growth':'売上成長率(%)', 'rd_ratio':'R&D/売上(%)',
        'cf_quality':'CF品質', 'equity_ratio':'自己資本比率(%)',
        'per':'PER(倍)', 'pbr':'PBR(倍)', 'dividend_yield':'配当利回り(%)',
    }
    tickers = list(all_data.keys())
    table_lines = [
        "=" * 70,
        f"📊 対戦表: {all_data[target_ticker].get('name', target_ticker)}",
        "=" * 70,
        f"{'指標':<22} | " + " | ".join(f"{t:<10}" for t in tickers),
        "-" * 70,
    ]
    for key, label in labels.items():
        vals = [f"{str(all_data[t].get('metrics',{}).get(key) or 'N/A'):<10}" for t in tickers]
        table_lines.append(f"{label:<22} | " + " | ".join(vals))
    table_lines.append("=" * 70)
    table_str = "\n".join(table_lines)

    target   = all_data[target_ticker]
    tech     = target.get('technical', {})
    news_text = "\n".join(target.get('news', [])) or "ニュースなし"
    cur      = tech.get('current_price', 'N/A')
    currency = target.get('currency', 'USD')

    print("🚀 [API 2/2] 全分析を一括生成中...")
    prompt = f"""
あなたは外資系ヘッジファンドのCIOです。
以下のデータをすべて使い、投資レポートを1つのレスポンスで完成させてください。

【比較の文脈】{competitors.get('reasoning', '')}

{table_str}

【テクニカル（{target_ticker}）】
現在価格:{cur} {currency} / MA25乖離:{tech.get('ma25_deviation')}% / MA75乖離:{tech.get('ma75_deviation')}%
RSI:{tech.get('rsi')} / BB位置:{tech.get('bb_position')}% / ボラ:{tech.get('volatility')}% / 出来高比:{tech.get('volume_ratio')}x
アナリスト目標:{tech.get('analyst_target')}

【ニュース（7日）】
{news_text}

【出力形式（厳守）】

━━━ ⚔️ Layer1: 地力分析 ━━━
💪 競争優位性: [数値根拠付き3項目]
⚠️ 競争劣位性: [2項目]
🐛 市場のバグ: [「PER〇倍はXXと比べ〇倍過小評価」など数値で]
📊 本質的価値スコア: X/10 [根拠2行]

━━━ ⏱️ Layer2: タイミング分析 ━━━
📰 センチメント: [ポジティブ/中立/ネガティブ] 強度[高/中/低] [根拠2行]
📈 テクニカル: [過熱/適正/割安] [根拠2行]
⚠️ 指標の矛盾: [あれば記載、なければ「矛盾なし」]
📅 カタリスト: [具体的イベント・日付]
⏱️ タイミングスコア: X/10

━━━ ✅ 最終投資判断 ━━━
🎯 シグナル: BUY / WATCH / SELL
📊 地力スコア: X/10
⏱️ タイミングスコア: X/10
🔢 総合スコア: X/10
【根拠】[3行]
【アクション】
- エントリー価格: {currency} XXX
- 損切りライン:   {currency} XXX（理由:）
- 利確ライン:     {currency} XXX（理由:）
- ポジションサイズ: ポートフォリオの X%
【出口戦略】
- 利確条件: [価格 or イベント]
- 損切り条件: [価格 AND ファンダメンタル変化]
【監視ポイント】1. 2.
"""
    report = call_gemini(prompt) or "分析失敗"
    return report, table_str


# ==========================================
# Google Sheets 出力
# ==========================================

def write_to_sheets(gc, target_ticker: str, target_data: dict,
                    competitors: dict, report: str, table_str: str):
    try:
        sp = gc.open_by_key(SPREADSHEET_ID)
        sname = CONFIG['sheets']['output']
        try:
            sheet = sp.worksheet(sname)
        except:
            sheet = sp.add_worksheet(sname, rows=1000, cols=8)
            sheet.append_row(["日付","銘柄","価格","シグナル","総合スコア","比較対象","レポート","対戦表"])

        sig_m   = re.search(r'シグナル.*?(BUY|WATCH|SELL)', report) or re.search(r'\b(BUY|WATCH|SELL)\b', report)
        score_m = re.search(r'総合スコア.*?(\d+)/10', report)
        tech    = target_data.get('technical', {})

        row = [
            datetime.now().strftime('%Y/%m/%d %H:%M'),
            target_ticker,
            f"{tech.get('current_price','N/A')} {target_data.get('currency','')}",
            sig_m.group(1)   if sig_m   else "N/A",
            score_m.group(1) if score_m else "N/A",
            str(competitors.get('direct',[]) + competitors.get('substitute',[])),
            report,
            table_str,
        ]
        sheet.append_row(row)
        last = len(sheet.get_all_values())
        sheet.format(f"G{last}:H{last}", {"wrapStrategy": "WRAP"})
        print(f"✅ スプレッドシート書き込み完了（行 {last}）")
    except Exception as e:
        print(f"❌ Sheetsエラー: {e}")


# ==========================================
# メインフロー
# ==========================================

def run(ticker: str, gc=None):
    print(f"\n{'='*60}\n🚀 {ticker} の司令塔分析を開始\n{'='*60}")

    target_data = fetch_stock_data(ticker)
    competitors = select_competitors(target_data)  # API 1/2

    comp_tickers = list(set(
        competitors.get('direct',    []) +
        competitors.get('substitute', []) +
        competitors.get('benchmark',  [])
    ))
    print(f"📈 比較対象 {len(comp_tickers)} 銘柄のデータ取得中...")
    all_data = {ticker: target_data}
    for t in comp_tickers:
        all_data[t] = fetch_stock_data(t)
        time.sleep(0.3)

    report, table_str = analyze_all(ticker, all_data, competitors)  # API 2/2

    if gc:
        write_to_sheets(gc, ticker, target_data, competitors, report, table_str)

    print("\n" + "="*60 + "\n" + report + "\n" + "="*60)
    return report


def main():
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY が未設定")
        sys.exit(1)

    gc = None
    if GOOGLE_SERVICE_ACCOUNT_JSON and SPREADSHEET_ID:
        try:
            creds = Credentials.from_service_account_info(
                json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
                scopes=['https://www.googleapis.com/auth/spreadsheets',
                        'https://www.googleapis.com/auth/drive'])
            gc = gspread.authorize(creds)
            print("✅ Google Sheets 認証成功")
        except Exception as e:
            print(f"⚠️ Sheets認証失敗（出力なしで続行）: {e}")

    # 銘柄コード取得（--ticker AMAT / 7203.T / 複数対応）
    args = sys.argv[1:]
    tickers, skip = [], False
    for i, arg in enumerate(args):
        if skip: skip = False; continue
        if arg.lower() == '--ticker':
            if i + 1 < len(args): tickers.append(args[i+1].upper()); skip = True
        elif not arg.startswith('--'):
            tickers.append(arg.upper())

    if not tickers:
        raw = input("銘柄コードを入力（例: 7203.T AAPL）> ").strip()
        tickers = [t.upper() for t in raw.replace(',', ' ').split() if t]

    if not tickers:
        print("❌ 銘柄コードが入力されていません")
        sys.exit(1)

    print(f"🎯 分析対象: {', '.join(tickers)}")
    for i, ticker in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}] {ticker}")
        try:
            run(ticker, gc)
        except Exception as e:
            print(f"❌ {ticker} 失敗: {e}")
        if i < len(tickers) - 1:
            print("⏳ 5秒待機...")
            time.sleep(5)

    if gc:
        print(f"\n📊 結果: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")


if __name__ == "__main__":
    main()
