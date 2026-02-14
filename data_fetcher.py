"""
data_fetcher.py - データ取得モジュール
======================================
yfinance による株式データの取得と、Gemini API による比較対象の自動選定を担当。
"""

import os, re, json, time, math, unicodedata
import yfinance as yf
from datetime import datetime, timedelta
from google import genai

# APIキーは関数呼び出し時に毎回取得（Streamlit等での遅延ロードに対応）
def _get_gemini_key():
    return os.environ.get('GEMINI_API_KEY', '')

def _get_groq_key():
    return os.environ.get('GROQ_API_KEY', '')

from groq import Groq

# ==========================================
# Groq API クライアント (Llama 3)
# ==========================================
def call_groq(prompt: str, parse_json: bool = False, model: str = "llama-3.3-70b-versatile") -> any:
    """
    Groq API (Llama 3) を呼び出す。
    Gemini の代替として使用。
    """
    if not _get_groq_key():
        print("❌ Groq エラー: API キーが設定されていません。")
        return None

    client = Groq(api_key=_get_groq_key())
    
    try:
        print(f"  🚀 Groq ({model}) に切り替えて実行中...")
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful financial analyst. Output valid JSON when requested."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=8192,
            top_p=1,
            stream=False,
            response_format={"type": "json_object"} if parse_json else None
        )
        
        text = completion.choices[0].message.content
        
        if parse_json:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # JSONモードでもマークダウンが含まれる場合のクリーニング
                cleaned = re.sub(r'```json\s*', '', text)
                cleaned = re.sub(r'```\s*$', '', cleaned)
                return json.loads(cleaned)
        return text

    except Exception as e:
        print(f"❌ Groq エラー: {e}")
        return None


try:
    with open("config.json", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {
        "competitor_selection": {"direct_count": 3, "substitute_count": 2, "benchmark_count": 2},
    }


# ==========================================
# ユーティリティ
# ==========================================

def get_east_asian_width_count(text: str) -> int:
    """全角文字を2、半角文字を1としてカウントする"""
    count = 0
    for char in text:
        if unicodedata.east_asian_width(char) in 'FWA':
            count += 2
        else:
            count += 1
    return count

def pad_east_asian(text: str, width: int) -> str:
    """全角文字を考慮して指定の幅まで半角スペースで埋める"""
    cur_len = get_east_asian_width_count(text)
    return text + ' ' * max(0, width - cur_len)

def clean_val(v) -> str:
    """nan / None / 空文字 をすべて '-' に統一して返す"""
    if v is None:
        return "-"
    try:
        if math.isnan(float(v)):
            return "-"
    except (TypeError, ValueError):
        pass
    if str(v).strip().lower() in ("nan", "none", "n/a", ""):
        return "-"
    return str(v)

def short_name(name: str) -> str:
    """企業名を対戦表に収まる略称（最大12文字）に短縮する。"""
    replacements = [
        (" Financial Group", ""), (" Financial", ""), (" Holdings", ""),
        (" Corporation", ""), (" Incorporated", ""), (", Inc.", ""),
        (" Inc.", ""), (" Ltd.", ""), (" Co.", ""), (" & Co.", ""),
        (" Group", ""), (" International", "Intl"), (" Technologies", "Tech"),
        (" Technology", "Tech"), (" Services", "Svc"), (" Solutions", "Sol"),
        ("Applied Materials", "AMAT"), ("Mitsubishi UFJ", "MUFG"),
        ("Sumitomo Mitsui", "SMFG"), ("Mizuho", "Mizuho"),
        ("Morgan Stanley", "M.Stanley"), ("JPMorgan Chase", "JPMorgan"),
        ("PayPal", "PayPal"), ("Orix", "ORIX"), ("Rakuten", "Rakuten"),
    ]
    result = name
    for old, new in replacements:
        result = result.replace(old, new)
    result = result.strip().strip(",").strip()
    return result[:12] if len(result) > 12 else result


# ==========================================
# Gemini API（429自動リトライ）
# ==========================================

def call_gemini(prompt: str, parse_json: bool = False, max_retries: int = 5,
                model: str = "flash"):
    """
    Gemini API を呼び出す。

    Args:
        model: "flash" (高速・低コスト), "pro" (高精度・高コスト),
               または直接モデル名を指定
    """
    if not _get_gemini_key() or "your_gemini" in _get_gemini_key():
        print("⚠️ Gemini APIキー未設定 -> Groq (Llama 3) で試行します...")
        return call_groq(prompt, parse_json)

    client = genai.Client(api_key=_get_gemini_key())

    # モデル名の解決
    # APIで確認された正規のモデルIDを使用
    MODEL_MAP = {
        "flash": "gemini-2.0-flash",
        "pro":   "gemini-2.5-pro",
    }
    target_model = MODEL_MAP.get(model, model)
    
    # フォールバック用
    stable_model = "gemini-2.0-flash-lite"

    current_model = target_model
    
    for attempt in range(max_retries):
        try:
            # generate_content の呼び出し
            response = client.models.generate_content(
                model=current_model,
                contents=prompt
            )
            
            # テキスト抽出
            text = response.text
            if not text:
                raise ValueError("Empty response from Gemini")

            # JSONパースモード
            if parse_json:
                cleaned_text = re.sub(r'```json\s*', '', text)
                cleaned_text = re.sub(r'```\s*$', '', cleaned_text)
                m = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
                if m:
                    return json.loads(m.group(0))
                return json.loads(cleaned_text)
                
            return text

        except Exception as e:
            err_msg = str(e)
            print(f"  ⚠️ Gemini リカバリ ({current_model}) ({attempt+1}/{max_retries}): {err_msg[:100]}...")
            
            # レート制限 (429) または 容量超過 (RESOURCE_EXHAUSTED)
            if '429' in err_msg or 'RESOURCE_EXHAUSTED' in err_msg:
                # "quota" (1日上限) エラーか判定
                is_quota_error = "quota" in err_msg.lower()
                
                # Quotaエラーなら待っても無駄なので、即座に安定版へ切り替え
                if is_quota_error:
                    if current_model != stable_model:
                        print(f"    🚫 1日上限(Quota)に到達しました。待機時間をスキップして安定版 ({stable_model}) に切り替えます...")
                        current_model = stable_model
                        continue  # sleepせずに即リトライ
                    
                    # 安定版も上限なら、Groq (Llama 3) に逃げる
                    print(f"    🚫 Gemini 全モデル上限到達。Groq (Llama 3) にフォールバックします...")
                    return call_groq(prompt, parse_json)

                # それ以外のレート制限(RPM)なら待機する
                wait_time = 5 * (2 ** attempt)
                m = re.search(r'retry.*?in.*?(\d+)', err_msg)
                if m:
                    wait_time = max(wait_time, int(m.group(1)) + 2)
                
                print(f"    ⏳ レート制限待機: {wait_time}秒...")
                time.sleep(wait_time)
                
                # Pro で失敗し続けている場合 (RPM制限)、回数を重ねたら切り替え
                if current_model != stable_model and attempt >= 1:
                    print(f"    🔄 レート制限が続いているため、安定版 ({stable_model}) に切り替えます...")
                    current_model = stable_model
                
                continue
            
            # サーバーエラー (5xx)
            if '500' in err_msg or '503' in err_msg:
                time.sleep(5)
                continue
                
            print(f"❌ Gemini 致命的エラー: {e}")
            print(f"    🔄 Groq (Llama 3) でリトライします...")
            return call_groq(prompt, parse_json)
            
    print(f"❌ Gemini リトライ回数超過 ({max_retries}回) -> Groq (Llama 3) へフォールバック")
    return call_groq(prompt, parse_json)


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
        try:
            v = df.loc[row].iloc[0]
            return None if (v is None or (isinstance(v, float) and math.isnan(v))) else v
        except:
            return None

    metrics = {}
    op, rev, ni = sg(fin,'Operating Income'), sg(fin,'Total Revenue'), sg(fin,'Net Income')
    ocf, eq, ta = sg(cf,'Operating Cash Flow'), sg(bs,'Stockholders Equity'), sg(bs,'Total Assets')
    rd = sg(fin, 'Research And Development')

    if op  and rev and rev != 0: metrics['op_margin']    = round(op  / rev * 100, 1)
    if ni  and rev and rev != 0: metrics['net_margin']   = round(ni  / rev * 100, 1)
    if rd  and rev and rev != 0: metrics['rd_ratio']     = round(abs(rd) / rev * 100, 1)
    if ocf and ni  and ni  != 0: metrics['cf_quality']   = round(ocf / ni, 2)
    if eq  and ta  and ta  != 0: metrics['equity_ratio'] = round(eq  / ta * 100, 1)

    def safe_pct(key, mult=100):
        v = info.get(key)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return round(v * mult, 1)

    metrics['roe']             = safe_pct('returnOnEquity')
    metrics['revenue_growth']  = safe_pct('revenueGrowth')
    metrics['earnings_growth'] = safe_pct('earningsGrowth')

    def safe_info(key):
        v = info.get(key)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return v

    metrics['per']            = safe_info('forwardPE')
    metrics['pbr']            = safe_info('priceToBook')
    metrics['dividend_yield'] = safe_pct('dividendYield')

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
            'volume_ratio':   round(safe_info('volume') / max(safe_info('averageVolume') or 1, 1), 2),
            'analyst_target': safe_info('targetMeanPrice'),
        }

    cutoff = datetime.now() - timedelta(days=7)
    news = [
        f"[{datetime.fromtimestamp(n.get('providerPublishTime',0)).strftime('%m/%d')}] {n.get('title','')} ({n.get('publisher','')})"
        for n in (stock.news or [])[:8]
        if datetime.fromtimestamp(n.get('providerPublishTime', 0)) >= cutoff
    ]

    return {
        'ticker':      ticker,
        'name':        info.get('longName', ticker),
        'sector':      info.get('sector', '不明'),
        'country':     info.get('country', '不明'),
        'currency':    info.get('currency', 'USD'),
        'description': (info.get('longBusinessSummary') or '')[:200],
        'metrics':     metrics,
        'technical':   technical,
        'news':        news,
    }


# ==========================================
# 比較対象の自動選定（ローカルロジック、API不使用）
# ==========================================

# セクター別の定型競合マッピング
SECTOR_COMPETITORS = {
    # Technology
    "Technology": {
        "us": {"direct": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN", "CRM", "ORCL", "ADBE", "INTC", "AMD", "AVGO", "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "MU", "IBM"],
               "benchmark": ["MSFT", "AAPL", "GOOGL"]},
        "jp": {"direct": ["6758.T", "6902.T", "6861.T", "6501.T", "6503.T", "4063.T", "6367.T", "7741.T", "6857.T", "6723.T"],
               "benchmark": ["AAPL", "MSFT"]},
    },
    "Communication Services": {
        "us": {"direct": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "SPOT"],
               "benchmark": ["GOOGL", "META"]},
        "jp": {"direct": ["9432.T", "9433.T", "9434.T", "4689.T", "3659.T"],
               "benchmark": ["GOOGL", "META"]},
    },
    # Financial Services
    "Financial Services": {
        "us": {"direct": ["JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "V", "MA", "PYPL"],
               "benchmark": ["JPM", "BLK"]},
        "jp": {"direct": ["8306.T", "8316.T", "8411.T", "8604.T", "8766.T", "8697.T", "8591.T"],
               "benchmark": ["JPM", "GS"]},
    },
    # Healthcare
    "Healthcare": {
        "us": {"direct": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "BMY", "AMGN", "GILD"],
               "benchmark": ["JNJ", "UNH"]},
        "jp": {"direct": ["4502.T", "4503.T", "4568.T", "4519.T", "4523.T", "4151.T"],
               "benchmark": ["JNJ", "PFE"]},
    },
    # Consumer Cyclical
    "Consumer Cyclical": {
        "us": {"direct": ["AMZN", "TSLA", "HD", "NKE", "MCD", "SBUX", "TGT", "LOW", "F", "GM"],
               "benchmark": ["AMZN", "TSLA"]},
        "jp": {"direct": ["7203.T", "7267.T", "7269.T", "9983.T", "3382.T", "7974.T", "9984.T"],
               "benchmark": ["AMZN", "TSLA"]},
    },
    # Industrials
    "Industrials": {
        "us": {"direct": ["CAT", "DE", "BA", "HON", "UPS", "RTX", "LMT", "GE", "MMM"],
               "benchmark": ["CAT", "HON"]},
        "jp": {"direct": ["6301.T", "7011.T", "6273.T", "6103.T", "7013.T", "6302.T"],
               "benchmark": ["CAT", "HON"]},
    },
    # Energy
    "Energy": {
        "us": {"direct": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "PSX", "VLO"],
               "benchmark": ["XOM", "CVX"]},
        "jp": {"direct": ["5020.T", "5019.T", "1605.T", "5021.T"],
               "benchmark": ["XOM", "CVX"]},
    },
    # Consumer Defensive
    "Consumer Defensive": {
        "us": {"direct": ["PG", "KO", "PEP", "COST", "WMT", "CL", "MDLZ", "PM"],
               "benchmark": ["PG", "KO"]},
        "jp": {"direct": ["2914.T", "2502.T", "2503.T", "4452.T", "2802.T"],
               "benchmark": ["PG", "KO"]},
    },
    # Real Estate
    "Real Estate": {
        "us": {"direct": ["AMT", "PLD", "CCI", "EQIX", "SPG", "O", "WELL"],
               "benchmark": ["AMT", "PLD"]},
        "jp": {"direct": ["8801.T", "8802.T", "3289.T", "8830.T", "3231.T"],
               "benchmark": ["AMT", "PLD"]},
    },
}


def select_competitors(target: dict, macro_data: dict = None) -> dict:
    """セクター情報を元にローカルで競合を選定する（API不使用）"""
    cfg = CONFIG['competitor_selection']
    ticker = target['ticker']
    sector = target.get('sector', '不明')
    is_jp = ticker.endswith('.T')
    region = "jp" if is_jp else "us"

    print(f"📋 比較対象をローカル選定中 (セクター: {sector})...")

    # セクターマッピングから取得
    sector_data = SECTOR_COMPETITORS.get(sector, {})
    region_data = sector_data.get(region, {})

    if not region_data:
        # セクターが見つからない場合、全セクターからフォールバック
        # 近いセクターを探す
        for s_name, s_data in SECTOR_COMPETITORS.items():
            if s_data.get(region):
                region_data = s_data[region]
                print(f"  ℹ️ セクター '{sector}' のマッピングなし → '{s_name}' で代替")
                break

    # 自分自身を除外
    candidates = [t for t in region_data.get("direct", []) if t != ticker]
    benchmarks = [t for t in region_data.get("benchmark", []) if t != ticker]

    direct = candidates[:cfg['direct_count']]
    substitute = candidates[cfg['direct_count']:cfg['direct_count'] + cfg['substitute_count']]
    benchmark = benchmarks[:cfg['benchmark_count']]

    # ベンチマークが空なら候補から補充
    if not benchmark and len(candidates) > cfg['direct_count'] + cfg['substitute_count']:
        benchmark = candidates[cfg['direct_count'] + cfg['substitute_count']:][:cfg['benchmark_count']]

    all_c = direct + substitute + benchmark
    print(f"✅ 比較対象: {all_c}")
    return {
        "direct": direct,
        "substitute": substitute,
        "benchmark": benchmark,
        "reasoning": f"セクター({sector})に基づくローカル選定",
    }

