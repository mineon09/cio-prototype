import os, re, json, time, math, unicodedata, sys, io
import pandas as pd

# 文字化け対策 (Windows環境用)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        pass

import yfinance as yf
from datetime import datetime, timedelta
import numpy as np
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from google import genai
from dotenv import load_dotenv

# .env ファイルから環境変数を読み込む
load_dotenv()

# APIキーは関数呼び出し時に毎回取得（Streamlit等での遅延ロードに対応）
def _get_gemini_key():
    return os.environ.get('GEMINI_API_KEY', '')

def _get_groq_key():
    return os.environ.get('GROQ_API_KEY', '')

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False
    Groq = None

# ==========================================
# Groq API クライアント (Llama 3)
# ==========================================
# ==========================================
# Groq API クライアント (Llama 3)
# ==========================================
def call_groq(prompt: str, parse_json: bool = False, model: str = "llama-3.3-70b-versatile") -> tuple:
    """
    Groq API (Llama 3) を呼び出す。
    Gemini の代替として使用。
    Returns: (result, model_name)
    """
    if not HAS_GROQ:
        print("❌ Groq エラー: groq パッケージがインストールされていません。 pip install groq を実行してください。")
        return None, None
    if not _get_groq_key():
        print("❌ Groq エラー: API キーが設定されていません。")
        return None, None

    client = Groq(api_key=_get_groq_key())
    
    try:
        print(f"  🚀 Groq ({model}) に切り替えて実行中...")
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "あなたは優秀な金融アナリストです。指定された際は有効なJSON形式で出力してください。また、レポートなどは日本語で出力してください。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=8192,
            top_p=1,
            stream=False,
            response_format={"type": "json_object"} if parse_json else None
        )
        
        text = completion.choices[0].message.content
        used_model = completion.model # 実際に使われたモデル名
        
        if parse_json:
            try:
                return json.loads(text), used_model
            except json.JSONDecodeError:
                # JSONモードでもマークダウンが含まれる場合のクリーニング
                cleaned = re.sub(r'```json\s*', '', text)
                cleaned = re.sub(r'```\s*$', '', cleaned)
                return json.loads(cleaned), used_model
        return text, used_model

    except Exception as e:
        print(f"❌ Groq エラー: {e}")
        return None, None


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


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)


# ==========================================
# Gemini API（429自動リトライ）
# ==========================================

def _extract_json(text: str):
    """テキストから最初の有効なJSONオブジェクト/配列を抽出する。
    JSONDecoder.raw_decode() を使用し、JSON後の余分なテキスト（Extra data）を無視する。
    """
    decoder = json.JSONDecoder()
    # '{' または '[' のすべての出現位置を取得して昇順にソート
    indices = [m.start() for m in re.finditer(r'[\{\[]', text)]
    for idx in indices:
        try:
            obj, _ = decoder.raw_decode(text, idx)
            return obj
        except json.JSONDecodeError:
            continue
    return None


def call_gemini(prompt: str, parse_json: bool = False, max_retries: int = 5,
                model: str = "flash", use_search: bool = False) -> tuple:
    """
    Gemini API を呼び出す。
    Returns: (result, model_name)
    """
    if not _get_gemini_key() or "your_gemini" in _get_gemini_key():
        print("⚠️ Gemini APIキー未設定 -> Groq (Llama 3) で試行します...")
        return call_groq(prompt, parse_json)

    client = genai.Client(api_key=_get_gemini_key())

    # モデル名の解決（quota効率化のため 2.5-flash をデフォルトに）
    MODEL_MAP = {
        "flash": "gemini-2.5-flash",
        "pro":   "gemini-2.0-pro-exp-0205", # 2.0の実験的プロモデル
        "flash-3.1": "gemini-3.1-flash",
    }
    target_model = MODEL_MAP.get(model, model)
    
    # フォールバック用
    stable_model = "gemini-2.5-flash"

    current_model = target_model
    
    for attempt in range(max_retries):
        try:
            # google_search ツール有効化（日本株ニュース取得等）
            gen_kwargs = {
                "model": current_model,
                "contents": prompt,
            }
            if use_search:
                from google.genai import types
                gen_kwargs["config"] = types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                )
            response = client.models.generate_content(**gen_kwargs)
            
            # google_search ツール使用時は response.text が空になる場合がある
            # その場合は candidates[0].content.parts からテキストを結合して取得
            text = ""
            try:
                text = response.text or ""
            except Exception:
                pass
            if not text and hasattr(response, 'candidates') and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        text += part.text
            if not text:
                raise ValueError("Empty response from Gemini")

            # JSONパースモード
            if parse_json:
                cleaned_text = re.sub(r'```json\s*', '', text)
                cleaned_text = re.sub(r'```\s*$', '', cleaned_text)
                # raw_decode で最初の有効なJSONを抽出（Extra data エラー回避）
                result = _extract_json(cleaned_text)
                if result is not None:
                    return result, current_model
                return json.loads(cleaned_text), current_model  # 最後の手段
                
            return text, current_model

        except Exception as e:
            err_msg = str(e)
            print(f"  ⚠️ Gemini リカバリ ({current_model}) ({attempt+1}/{max_retries}): {err_msg[:100]}...")
            
            if '429' in err_msg or 'RESOURCE_EXHAUSTED' in err_msg:
                is_quota_error = "quota" in err_msg.lower()
                
                if is_quota_error:
                    if current_model != stable_model:
                        print(f"    🚫 1日上限(Quota)に到達しました。待機時間をスキップして安定版 ({stable_model}) に切り替えます...")
                        current_model = stable_model
                        continue
                    
                    print(f"    🚫 Gemini 全モデル上限到達。Groq (Llama 3) にフォールバックします...")
                    return call_groq(prompt, parse_json)

                wait_time = 5 * (2 ** attempt)
                m = re.search(r'retry.*?in.*?(\d+)', err_msg)
                if m:
                    wait_time = max(wait_time, int(m.group(1)) + 2)
                
                print(f"    ⏳ レート制限待機: {wait_time}秒...")
                time.sleep(wait_time)
                
                if current_model != stable_model and attempt >= 1:
                    print(f"    🔄 レート制限が続いているため、安定版 ({stable_model}) に切り替えます...")
                    current_model = stable_model
                
                continue
            
            if '500' in err_msg or '503' in err_msg:
                time.sleep(5)
                continue
                
            print(f"❌ Gemini 致命的エラー: {e}")
            print(f"    🔄 Groq (Llama 3) でリトライします...")
            return call_groq(prompt, parse_json)
            
    print(f"❌ Gemini リトライ回数超過 ({max_retries}回) -> Groq (Llama 3) へフォールバック")
    return call_groq(prompt, parse_json)


def select_competitors(target_data: dict, macro_data: dict = None) -> dict:
    """
    対象銘柄の競合銘柄、代替資産、ベンチマークをAIに選定させる。
    マクロ環境が渡された場合、その影響を受けやすい競合や相関銘柄を含めるよう促す。
    """
    ticker = target_data.get('ticker')
    name = target_data.get('name')
    sector = target_data.get('sector')
    
    c_count = CONFIG.get("competitor_selection", {}).get("direct_count", 3)
    s_count = CONFIG.get("competitor_selection", {}).get("substitute_count", 2)
    b_count = CONFIG.get("competitor_selection", {}).get("benchmark_count", 2)

    is_jp = str(ticker).endswith('.T')

    if not macro_data and sector:
        rule_result = None
        if "Technology" in sector:
            if is_jp:
                rule_result = {"direct": ["6861.T", "8035.T", "9984.T"], "substitute": ["1321.T"], "benchmark": ["9984.T", "1306.T"]}
            else:
                rule_result = {"direct": ["MSFT", "AAPL", "GOOGL"], "substitute": ["XLK"], "benchmark": ["^IXIC", "SPY"]}
        elif "Financial" in sector or "Bank" in sector:
            if is_jp:
                rule_result = {"direct": ["8306.T", "8316.T", "8411.T"], "substitute": ["1321.T"], "benchmark": ["8306.T", "1306.T"]}
            else:
                rule_result = {"direct": ["JPM", "BAC", "WFC"], "substitute": ["XLF"], "benchmark": ["SPY"]}
        elif "Health" in sector or "Medical" in sector:
            if is_jp:
                rule_result = {"direct": ["4502.T", "4568.T", "4519.T"], "substitute": ["1321.T"], "benchmark": ["1306.T"]}
            else:
                rule_result = {"direct": ["JNJ", "UNH", "PFE"], "substitute": ["XLV"], "benchmark": ["SPY"]}

        if rule_result:
            print(f"🚀 [Rules] 比較対象をルールベースで選定中... ({sector})")
            for cat in ["direct", "substitute", "benchmark"]:
                rule_result[cat] = [t for t in rule_result[cat] if t != ticker]

            rule_result["reasoning"] = f"{sector}セクターの代表的な構成（API節約）"
            rule_result["ai_model"] = "Rule-based"
            return rule_result

    macro_text = ""
    if macro_data and macro_data.get("regime"):
        macro_text = f"現在のマクロ環境は '{macro_data['regime']}' です。この環境下で特に比較的重要となる競合、あるいは逆相関・ヘッジ先となる銘柄を優先的に含めてください。"

    prompt = f"""
あなたは機関投資家のポートフォリオマネージャーです。以下の銘柄を分析するための比較対象セットをJSONで出力してください。

対象銘柄: {name} ({ticker})
セクター: {sector}
{macro_text}

【出力内容】
1. 'direct': 直接競合する企業 ({c_count}件)
2. 'substitute': 代替となり得る資産、または逆相関の関係にある銘柄 ({s_count}件)
3. 'benchmark': 同じ経済圏・指数の代表銘柄 ({b_count}件)
4. 'reasoning': このセットを選んだプロの視点での短い日本語の解説 (100文字程度)

【書式】
{{
  "direct": ["TICKER1", "TICKER2"],
  "substitute": ["TICKER3"],
  "benchmark": ["TICKER4"],
  "reasoning": "解説文"
}}

※出力は有効なJSONのみ、余計な解説文は不要。米国株はティッカーのみ、日本株は.Tを付けること。yfinanceでデータ取得可能な実在するティッカーシンボルのみを使用してください（例: 日経平均は ^N225、TOPIXには必ず 1306.T を使用してください）。
"""
    print(f"🚀 [API] 比較対象を選定中...")
    result, model_name = call_gemini(prompt, parse_json=True)
    
    # デフォルト値
    default = {"direct": [], "substitute": [], "benchmark": [], "reasoning": "AI選定失敗。", "ai_model": model_name or "Unknown"}
    if not result: return default

    # ティッカーの実在確認（バリデーション層）
    print(f"  🔍 AI選定ティッカーの有効性を検証中...")
    validated = {"direct": [], "substitute": [], "benchmark": [], "reasoning": result.get("reasoning", "選定完了。"), "ai_model": model_name}
    for category in ["direct", "substitute", "benchmark"]:
        for t in result.get(category, []):
            try:
                # Bug #3 Fix: Force fallback for ^TOPX to 1306.T since ^TOPX is not valid via yfinance
                if t == '^TOPX':
                    print("    🔧 ^TOPX を 1306.T (TOPIX ETF) に自動変換しました")
                    t = '1306.T'
                
                hist = yf.Ticker(t).history(period="5d")
                if not hist.empty:
                    validated[category].append(t)
                else:
                    print(f"    ⚠️ データ取得不可なティッカーを除外: {t}")
            except Exception:
                print(f"    ⚠️ 無効なティッカーを除外: {t}")

    if not any(validated[c] for c in ["direct", "substitute", "benchmark"]):
        return default

    return validated


# ==========================================
# yfinance データ取得
# ==========================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((Exception,)),
    reraise=True
)
def _fetch_yf_with_retry(ticker: str, as_of_date: datetime = None):
    """
    yfinance API をリトライ付きで呼び出す内部関数
    """
    stock = yf.Ticker(ticker)
    
    if as_of_date:
        try:
            hist = yf.download(ticker, period="3y", progress=False)
            if hist.empty:
                 hist = stock.history(period="3y")
        except Exception:
            try:
                hist = yf.download(ticker, period="2y", progress=False)
            except Exception:
                 return None, None
        
        if isinstance(hist.columns, pd.MultiIndex):
            if len(hist.columns.levels) > 1:
                found = False
                for t_query in [ticker, ticker.upper(), ticker.lower()]:
                    try:
                        hist = hist.xs(t_query, axis=1, level=1)
                        found = True
                        break
                    except KeyError:
                        continue
                if not found:
                    hist.columns = hist.columns.get_level_values(0)
            else:
                hist.columns = hist.columns.get_level_values(0)

        if hist.index.tz is not None:
            hist.index = hist.index.tz_localize(None)
        
        end_dt = pd.Timestamp(as_of_date) + pd.Timedelta(days=1)
        start_dt = pd.Timestamp(as_of_date) - pd.Timedelta(days=400)
        hist = hist[(hist.index >= start_dt) & (hist.index < end_dt)] if not hist.empty else hist
    else:
        hist = stock.history(period="1y")

    return stock, hist

def fetch_stock_data(ticker: str, as_of_date: datetime = None, price_history: pd.DataFrame = None) -> dict:
    """
    指定した銘柄のデータを取得・計算して返す。
    as_of_date が指定された場合、その時点での過去データを返す（バックテスト用）。
    price_history が指定された場合、yf.downloadを行わずにそのデータを使用する（高速化）。
    """
    if price_history is not None:
        # バックテスト高速化用: 既存のDataFrameを使用
        # print(f"  ⚡ {ticker} 提供されたヒストリデータを使用 (基準日: {as_of_date})") # Verboseすぎるのでスキップ
        hist = price_history
    else:
        print(f"🔍 {ticker} データ取得開始... (基準日: {as_of_date.strftime('%Y-%m-%d') if as_of_date else '最新'})")
    
    # --- Macro Data Injection (v1.2) ---
    # DF-001: Redundant detect_regime() call removed to save API quota.
    # Macro data should be provided by the orchestrator (main.py / app.py) or fetched as needed.
    macro_info = None
    
    # キャッシュファイルパスの準備
    CACHE_DIR = "data/cache"
    os.makedirs(CACHE_DIR, exist_ok=True)
    date_str = as_of_date.strftime('%Y%m%d') if as_of_date else "latest"
    cache_file = os.path.join(CACHE_DIR, f"{ticker}_{date_str}.json")

    # キャッシュ確認 (price_historyがない場合のみ = Live/Latest mode)
    if price_history is None:
        # 24時間以内のキャッシュがあれば使用 (latestの場合)
        # バックテスト用(date指定あり)は永続的に使ってOK
        if os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if as_of_date or (time.time() - mtime < 24 * 3600):
                    with open(cache_file, "r", encoding="utf-8") as f:
                        print(f"  ⚡ {ticker} キャッシュを使用 ({date_str})")
                        return json.load(f)
            except Exception as e:
                print(f"  ⚠️ キャッシュ読み込みエラー: {e}")

    if price_history is None:
        msg = f"  📊 {ticker} データ取得中..."
        if as_of_date:
            msg += f" (基準日: {as_of_date.strftime('%Y-%m-%d')})"
        print(msg)
    
    try:
        if price_history is None:
            stock, hist = _fetch_yf_with_retry(ticker, as_of_date)
            if stock is None or hist is None or hist.empty:
                print(f"  ⚠️ {ticker}: No price data found")
                return {"ticker": ticker, "name": ticker, "metrics": {}, "technical": {}}
        else:
            stock = yf.Ticker(ticker)
        
        if hist.empty:
            print(f"  ⚠️ {ticker}: No price data found")
            return {"ticker": ticker, "name": ticker, "metrics": {}, "technical": {}}

        # 直近の株価
        latest = hist.iloc[-1]
        
        # Seriesの場合（MultiIndexが残っている等）はスカラー値を取り出す
        def _get_scalar(val):
            if isinstance(val, (pd.Series, pd.DataFrame)):
                return val.iloc[0] if not val.empty else 0.0
            return val

        current_price = _get_scalar(latest['Close'])
        
        # 財務データ（直近決算を採用）
        def get_latest_financial(df_quarterly):
            if df_quarterly is None or df_quarterly.empty: return None
            # 日付カラムを探してフィルタリング
            try:
                # yfinanceはカラムがTimestampの場合が多いが、文字列の可能性も考慮
                dates = pd.to_datetime(df_quarterly.columns)
            except Exception as e:
                return None
            
            valid_col_indices = []
            for i, d in enumerate(dates):
                if as_of_date:
                    # tz-naive同士で比較する
                    d_naive = d.tz_localize(None) if d.tzinfo else d
                    as_of_naive = pd.Timestamp(as_of_date).tz_localize(None) if pd.Timestamp(as_of_date).tzinfo else pd.Timestamp(as_of_date)
                    
                    # Point-in-Time: 決算日(d_naive)から発表まで約45日のラグを考慮する (Issue 03)
                    d_available = d_naive + pd.Timedelta(days=45)
                    
                    # 利用可能日がバックテスト時点より前の場合のみ採用
                    if d_available <= as_of_naive:
                        valid_col_indices.append(i)
                else:
                    valid_col_indices.append(i)
            
            if not valid_col_indices:
                return None
            
            valid_cols = df_quarterly.columns[valid_col_indices]
            # 日付としてソートして最新を取得
            sorted_cols = sorted(valid_cols, key=pd.to_datetime, reverse=True)
            return df_quarterly[sorted_cols[0]], sorted_cols  # B-1a: 有効カラムも返す

        # B-1a: get_latest_financial が (latest_series, sorted_valid_cols) のタプルを返すように変更
        fin_result = get_latest_financial(stock.quarterly_financials)
        fin_latest = fin_result[0] if fin_result else None
        fin_valid_cols = fin_result[1] if fin_result else []
        if fin_latest is None:
            fin_result = get_latest_financial(stock.financials)
            fin_latest = fin_result[0] if fin_result else None
            fin_valid_cols = fin_result[1] if fin_result else []

        bs_result = get_latest_financial(stock.quarterly_balance_sheet)
        bs_latest = bs_result[0] if bs_result else None
        if bs_latest is None:
            bs_result = get_latest_financial(stock.balance_sheet)
            bs_latest = bs_result[0] if bs_result else None

        cf_result = get_latest_financial(stock.quarterly_cashflow)
        cf_latest = cf_result[0] if cf_result else None
        if cf_latest is None:
            cf_result = get_latest_financial(stock.cashflow)
            cf_latest = cf_result[0] if cf_result else None

        # info
        info = stock.info if not as_of_date else {}
        
        # ヘルパー: 値の取得
        def get_val(series, keys, default=None):
            if series is None: return default
            for k in keys:
                if k in series.index:
                    val = series[k]
                    if pd.isna(val): continue
                    return val
            return default

        # 6. PER, PBR
        # B-1b 注意: yfinance は分割調整済み株価を返すため、過去のバックテスト時点のPER/PBRは
        # 當時の実際の核価と乖離する可能性がある（例: Nvidia 2024年10分割前の株価が1/10に修正済み）。
        # これは yfinance 固有の制限事項。
        
        # B-1a / Bug #2: TTM (Trailing Twelve Months) EPS / Net Income — 過去4四半期合計を使用
        # 季節性のある業種（小売・観光等）で単四半期×4の歪みを防ぐ。またROE計算でも利用するよう共通化。
        ttm_net_income = None
        if fin_valid_cols and stock.quarterly_financials is not None:
            qf = stock.quarterly_financials
            ttm_cols = fin_valid_cols[:4]  # 最新4四半期（PITフィルタ済み）
            ni_keys = ['Net Income', 'Net Income Common Stockholders', 'Net Income Including Noncontrolling Interests']
            ttm_values = []
            for col in ttm_cols:
                val = get_val(qf[col] if col in qf.columns else pd.Series(), ni_keys)
                if val is not None:
                    ttm_values.append(val)
            if ttm_values:
                if len(ttm_values) >= 4:
                    ttm_net_income = sum(ttm_values)  # 完全なTTM
                elif len(ttm_values) >= 2:
                    # 不完全な四半期→平均×4で推定
                    ttm_net_income = sum(ttm_values) / len(ttm_values) * 4
                else:
                    ttm_net_income = ttm_values[0] * 4  # フォールバック: 単四半期×4
        
        # TTM が取れなければ従来の単四半期×4にフォールバック
        # net_income: 直近四半期の純利益（フォールバック用）
        net_income = get_val(fin_latest, ['Net Income', 'Net Income Common Stockholders', 'Net Income Including Noncontrolling Interests'])
        if ttm_net_income is None:
            ttm_net_income = (net_income * 4) if net_income else None

        # equity: 自己資本（自己資本比率・ROE・BPS計算用）
        equity = get_val(bs_latest, ['Stockholders Equity', 'Total Equity Gross Minority Interest', 'Stockholders Equity Including Minority Interest', 'Common Stock Equity'])

        # --- Metrics 構築 ---
        metrics = {}
        
        # 1. ROE (Bug #2 Fixed: ROE uses consolidated TTM net income instead of single quarter)
        if ttm_net_income and equity and equity != 0:
            metrics['roe'] = round((ttm_net_income / equity) * 100, 2)
        else:
            # Fallback for some Japanese tickers
            metrics['roe'] = info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else None

        # 2. 営業利益率
        # DF-003: フォールバックから Revenue を除外し、誤認を防止
        op_income = get_val(fin_latest, ['Operating Income', 'EBIT'])
        revenue   = get_val(fin_latest, ['Total Revenue', 'Operating Revenue', 'Total Operating Income As Reported'])
        
        # Specific check: if op_income == revenue, try to find a cost to subtract or look for Operating Expense
        if op_income == revenue and revenue:
             op_exp = get_val(fin_latest, ['Operating Expense', 'Total Operating Expenses'])
             if op_exp:
                 op_income = revenue - op_exp
        
        if op_income and revenue and revenue != 0:
            metrics['op_margin'] = round((op_income / revenue) * 100, 2)
        else:
            metrics['op_margin'] = info.get('operatingMargins', 0) * 100 if info.get('operatingMargins') else None

        # 3. 自己資本比率
        assets = get_val(bs_latest, ['Total Assets'])
        if equity and assets and assets != 0:
            metrics['equity_ratio'] = round((equity / assets) * 100, 2)
        else:
            metrics['equity_ratio'] = None

        # 4. CF品質 (Operating CF / Net Income)
        op_cf = get_val(cf_latest, ['Operating Cash Flow', 'Total Cash From Operating Activities'])
        if op_cf and net_income and net_income != 0:
             metrics['cf_quality'] = round(op_cf / net_income, 2)
        else:
             metrics['cf_quality'] = None

        # 5. R&D比率 (DF-002: バックテスト時のみ省略、ライブ分析では取得試行)
        # CRIT-005注記: バックテスト時(as_of_date指定時)は yfinance の R&D データが
        # 過去断面では信頼性が低いため意図的にゼロ固定としている。
        # ライブ分析時は fin_latest / info から取得を試行する。
        if as_of_date:
            metrics['rd_ratio'] = 0  # バックテスト時: 過去R&Dデータ不安定のため省略
        else:
            rd_exp = get_val(fin_latest, ['Research And Development', 'Research Development'])
            if rd_exp and revenue and revenue != 0:
                metrics['rd_ratio'] = round((rd_exp / revenue) * 100, 2)
            else:
                 metrics['rd_ratio'] = info.get('researchAndDevelopmentRatio', 0) or 0
        
        if as_of_date:
            shares = get_val(bs_latest, ['Share Issued', 'Ordinary Shares Number'])
            
            eps = ttm_net_income / shares if ttm_net_income and shares else None
            
            if current_price and eps and eps > 0:
                metrics['per'] = round(current_price / eps, 2)
            else:
                metrics['per'] = None
                
            bps = equity / shares if equity and shares else None
            
            if current_price and bps and bps > 0:
                metrics['pbr'] = round(current_price / bps, 2)
            else:
                metrics['pbr'] = None
            
            metrics['dividend_yield'] = None
        else:
            metrics['per'] = info.get('trailingPE')
            metrics['pbr'] = info.get('priceToBook')
            # Bug #1 Fix: Prevent double conversion of dividend yield
            dy_raw = info.get('dividendYield') or 0
            if dy_raw > 0:
                # If dividend yield is unexpectedly high (e.g. >= 1.0 = 100%), it's already a percentage
                if dy_raw >= 1.0:
                    metrics['dividend_yield'] = dy_raw
                else: # Normal small decimal (e.g. 0.0215 -> 2.15)
                    metrics['dividend_yield'] = dy_raw * 100
            else:
                metrics['dividend_yield'] = 0

        # --- Technical 構築 ---
        technical = {}
        technical['current_price'] = current_price
        
        closes = hist['Close']
        
        # RSI (14)
        if len(closes) >= 15:
            delta = closes.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            technical['rsi'] = round(rsi.iloc[-1], 2)
        else:
            technical['rsi'] = 50.0

        # MA乖離
        if len(closes) >= 25:
            ma25 = closes.rolling(window=25).mean().iloc[-1]
            technical['ma25_deviation'] = round((current_price - ma25) / ma25 * 100, 2)
        
        if len(closes) >= 75:
            ma75 = closes.rolling(window=75).mean().iloc[-1]
            technical['ma75_deviation'] = round((current_price - ma75) / ma75 * 100, 2)

        # Raw MAs for Backtester
        if len(closes) >= 5:
            technical['ma5'] = round(closes.rolling(window=5).mean().iloc[-1], 2)
        if len(closes) >= 25:
            technical['ma25'] = round(closes.rolling(window=25).mean().iloc[-1], 2)
        if len(closes) >= 75:
            technical['ma75'] = round(closes.rolling(window=75).mean().iloc[-1], 2)

        # ボリンジャーバンド (20, 2)
        if len(closes) >= 20:
            ma20 = closes.rolling(window=20).mean().iloc[-1]
            sigma = closes.rolling(window=20).std().iloc[-1]
            upper = ma20 + 2 * sigma
            lower = ma20 - 2 * sigma
            if upper != lower:
                pos = (current_price - lower) / (upper - lower) * 100
                technical['bb_position'] = round(pos, 2)

        # 出来高倍率
        vols = hist['Volume']
        if len(vols) >= 21:
            vol_avg = vols.rolling(window=20).mean().iloc[-2]
            vol_cur = vols.iloc[-1]
            if vol_avg > 0:
                technical['volume_ratio'] = round(vol_cur / vol_avg, 2)
            technical['vol_ma20'] = round(vol_avg, 0)
            technical['volume'] = vol_cur
        
        # --- ATR (Average True Range) ---
        if len(hist) >= 15:
            high = hist['High']
            low = hist['Low']
            close = hist['Close'].shift(1)
            tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
            atr = tr.rolling(window=14).mean().iloc[-1]
            technical['atr'] = round(atr, 2)
            technical['atr_pct'] = round((atr / current_price) * 100, 2)
        else:
            # Fallback for ATR if data is missing (approx 3% of price)
            technical['atr'] = round(current_price * 0.03, 2)
            technical['atr_pct'] = 3.0
        
        if not as_of_date:
            technical['analyst_target'] = info.get('targetMeanPrice')

        name = info.get('longName', ticker) if not as_of_date else ticker
        sector = info.get('sector', "Unknown") if not as_of_date else "Unknown"
        currency = info.get('currency', 'USD') if not as_of_date else 'USD'

        # --- バリデーション (Invalid Data Check) ---
        # 必須指標のNaNチェックや極端な変化を検出する
        def validate_number(val, name, allow_nan=True):
            if val is None or pd.isna(val) or math.isinf(val):
                return None if allow_nan else 0.0
            return val
            
        metrics['roe'] = validate_number(metrics.get('roe'), 'roe', allow_nan=False) # ROEは必須として扱う(無い場合は0)
        technical['current_price'] = validate_number(technical.get('current_price'), 'current_price', allow_nan=False)
        
        # 前日比変化率のバリデーション (±50%超は異常値として警告)
        if len(closes) >= 2:
            prev_close = closes.iloc[-2]
            if prev_close > 0:
                pct_change = (current_price - prev_close) / prev_close
                if abs(pct_change) > 0.5:
                    print(f"  🚨 {ticker} 警告: 株価が前日から極端に変動しています ({pct_change*100:.1f}%)。株式分割等の補正漏れの可能性があります。")
                    technical['price_warning'] = True

        # ニュース取得: 日本株はスキップ（main.py で Gemini google_search から取得）
        news_items = []
        is_jp = ticker.endswith('.T')
        if not is_jp:
            try:
                raw_news = stock.news or []
                from datetime import timezone
                cutoff = datetime.now(tz=timezone.utc).timestamp() - (7 * 86400)
                for item in raw_news[:15]:
                    ts = item.get('providerPublishTime', 0)
                    title = item.get('title', '').strip()
                    source = item.get('publisher', item.get('providerDisplayName', ''))
                    if ts and title:
                        if ts < cutoff:
                            continue
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        news_items.append(f"[{dt.strftime('%m/%d')}] {title} ({source})")
                    elif title:
                        news_items.append(f"{title} ({source})")
                news_items = news_items[:10]
            except Exception:
                pass  # ニュース取得失敗はサイレントで続行

        result_data = {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "currency": currency,
            "metrics": metrics,
            "technical": technical,
            "macro": macro_info,
            "news": news_items,
            "description": ""
        }
        
        # --- Save to Cache ---
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        except Exception as e:
            print(f"  ⚠️ キャッシュ保存エラー: {e}")
            
        return result_data

    except Exception as e:
        print(f"  ⚠️ {ticker} 取得失敗: {e}")
        return {"ticker": ticker, "name": ticker, "currency": "USD",
                "metrics": {}, "technical": {}, "news": [], "description": ""}
