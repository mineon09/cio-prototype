"""
data_fetcher.py - データ取得モジュール
======================================
yfinance による株式データの取得と、Gemini API による比較対象の自動選定を担当。
"""

import os, re, json, time, math, unicodedata
import yfinance as yf
from datetime import datetime, timedelta
from google import genai

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

from groq import Groq

# ==========================================
# Groq API クライアント (Llama 3)
# ==========================================
def call_groq(prompt: str, parse_json: bool = False, model: str = "llama-3.3-70b-versatile") -> any:
    """
    Groq API (Llama 3) を呼び出す。
    Gemini の代替として使用。
    """
    if not GROQ_API_KEY:
        print("❌ Groq エラー: API キーが設定されていません。")
        return None

    client = Groq(api_key=GROQ_API_KEY)
    
    try:
        print(f"  🚀 Groq ({model}) に切り替えて実行中...")
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful financial analyst. Output valid JSON when requested."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=4096,
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
    if not GEMINI_API_KEY or "your_gemini" in GEMINI_API_KEY:
        print("⚠️ Gemini APIキー未設定 -> Groq (Llama 3) で試行します...")
        return call_groq(prompt, parse_json)

    client = genai.Client(api_key=GEMINI_API_KEY)

    # モデル名の解決
    # APIで確認された正規のモデルIDを使用
    MODEL_MAP = {
        "flash": "gemini-2.0-flash",
        "pro":   "gemini-1.5-pro",
    }
    target_model = MODEL_MAP.get(model, model)
    
    # フォールバック用
    stable_model = "gemini-1.5-flash"

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
# 比較対象の自動選定
# ==========================================

def select_competitors(target: dict, macro_data: dict = None) -> dict:
    cfg = CONFIG['competitor_selection']
    
    # マクロ環境情報の組み立て
    macro_context = ""
    if macro_data and macro_data.get("regime"):
        regime = macro_data.get("regime", "NEUTRAL")
        desc = macro_data.get("description", "")
        indicators = macro_data.get("indicators", {})
        macro_context = f"""
【現在のマクロ環境】
Regime: {regime} — {desc}
米10年債: {indicators.get('us10y', 'N/A')}% | VIX: {indicators.get('vix', 'N/A')} | USD/JPY: {indicators.get('usdjpy', 'N/A')} | WTI: {indicators.get('oil', 'N/A')}
"""

    # 地域判定
    ticker = target['ticker']
    country = target.get('country', '不明')
    is_jp = ticker.endswith('.T')
    region_rule = ""
    if is_jp:
        region_rule = """
【地域ルール（日本株）】
- direct（直接競合）は **必ず日本市場の同業（.T サフィックス）を2社以上** 含めること。
- 海外企業（米国銀行等）は、金利局面やマクロ環境が異なるため direct ではなく benchmark に配置すること。
- substitute（機能代替）は国内外問わず可。
"""
    else:
        region_rule = """
【地域ルール（米国株等）】
- direct（直接競合）は **同一市場・同一ビジネスモデルの企業を優先** すること。
- 異なる規制環境・金利局面にある海外企業は benchmark に配置し、直接比較は避けること。
"""

    prompt = f"""
投資委員会CIOとして、以下の銘柄の「真の競争力」を評価するための比較対象をJSONで選定せよ。

銘柄: {ticker} / {target['name']} / {target.get('sector','不明')} / {country}
概要: {target.get('description','')[:150]}
{macro_context}
{region_rule}
【カテゴリと役割】
- direct（直接競合）: {cfg['direct_count']}社 — 同一市場・同一ビジネスモデルで直接シェアを競う相手。マクロ環境が同等であること。
- substitute（機能代替）: {cfg['substitute_count']}社 — 異なるアプローチで同じ顧客ニーズを満たすプレイヤー。
- benchmark（資本効率比較）: {cfg['benchmark_count']}社 — グローバルベストプラクティスとの比較。異なる地域・金利環境の同業大手を含めてよい。

制約: yfinanceで取得可能なティッカーのみ。日本株は「7203.T」形式。JSONのみ返答。

{{"direct":["T1","T2","T3"],"substitute":["T4","T5"],"benchmark":["T6","T7"],"reasoning":"理由（マクロ環境の違いを踏まえた選定理由を1-2行）"}}
"""
    print("🧠 [API 1/2] 比較対象を選定中...")
    result = call_gemini(prompt, parse_json=True)
    if not result:
        return {"direct": [], "substitute": [], "benchmark": [], "reasoning": "選定失敗"}
    all_c = result.get('direct',[]) + result.get('substitute',[]) + result.get('benchmark',[])
    print(f"✅ 比較対象: {all_c}")
    return result

