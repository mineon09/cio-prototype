"""
data_fetcher.py - データ取得モジュール
======================================
yfinance による株式データの取得と、Gemini API による比較対象の自動選定を担当。
"""

import os, re, json, time, math, unicodedata
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
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


# ==========================================
# Gemini API（429自動リトライ）
# ==========================================

def call_gemini(prompt: str, parse_json: bool = False, max_retries: int = 5,
                model: str = "flash") -> tuple:
    """
    Gemini API を呼び出す。
    Returns: (result, model_name)
    """
    if not _get_gemini_key() or "your_gemini" in _get_gemini_key():
        print("⚠️ Gemini APIキー未設定 -> Groq (Llama 3) で試行します...")
        return call_groq(prompt, parse_json)

    client = genai.Client(api_key=_get_gemini_key())

    # モデル名の解決
    MODEL_MAP = {
        "flash": "gemini-3-flash-preview",
        "pro":   "gemini-3-pro-preview",
    }
    target_model = MODEL_MAP.get(model, model)
    
    # フォールバック用
    stable_model = "gemini-2.5-flash"

    current_model = target_model
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=current_model,
                contents=prompt
            )
            
            text = response.text
            if not text:
                raise ValueError("Empty response from Gemini")

            # JSONパースモード
            if parse_json:
                cleaned_text = re.sub(r'```json\s*', '', text)
                cleaned_text = re.sub(r'```\s*$', '', cleaned_text)
                m = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
                if m:
                    return json.loads(m.group(0)), current_model
                return json.loads(cleaned_text), current_model
                
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
    
    # 既存の config から数を取得
    c_count = CONFIG.get("competitor_selection", {}).get("direct_count", 3)
    s_count = CONFIG.get("competitor_selection", {}).get("substitute_count", 2)
    b_count = CONFIG.get("competitor_selection", {}).get("benchmark_count", 2)

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

※出力は有効なJSONのみ、余計な解説文は不要。米国株はティッカーのみ、日本株は.Tを付けること。
"""
    print(f"🚀 [API] 比較対象を選定中...")
    result, model_name = call_gemini(prompt, parse_json=True)
    
    # デフォルト値
    default = {"direct": [], "substitute": [], "benchmark": [], "reasoning": "AI選定失敗。", "ai_model": model_name or "Unknown"}
    if not result: return default
    return {
        "direct": result.get("direct", []),
        "substitute": result.get("substitute", []),
        "benchmark": result.get("benchmark", []),
        "reasoning": result.get("reasoning", "選定完了。"),
        "ai_model": model_name
    }


# ==========================================
# yfinance データ取得
# ==========================================

def fetch_stock_data(ticker: str, as_of_date: datetime = None) -> dict:
    """
    指定した銘柄のデータを取得・計算して返す。
    as_of_date が指定された場合、その時点での過去データを返す（バックテスト用）。
    """
    print(f"🔍 {ticker} データ取得開始... (基準日: {as_of_date.strftime('%Y-%m-%d') if as_of_date else '最新'})")
    
    # --- Macro Data Injection (v1.2) ---
    macro_info = None
    if not as_of_date: # バックテスト中は毎回取得すると遅いので、最新分析時のみ取得（または別途キャッシュ管理）
        try:
            # 相対インポートと絶対インポートの両方を試行（実行環境依存の回避）
            try:
                from .macro_regime import detect_regime
            except ImportError:
                from src.macro_regime import detect_regime
            
            macro_info = detect_regime()
        except Exception as e:
            print(f"  ⚠️ マクロデータ取得失敗: {e}")
            macro_info = None
    
    # キャッシュ確認 (バックテスト時は日付込みで管理推奨だが、簡易実装としてticker単位)
    CACHE_DIR = "data/cache"
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # 日付を含むユニークなキャッシュキーを作成
    date_str = as_of_date.strftime('%Y%m%d') if as_of_date else "latest"
    cache_file = os.path.join(CACHE_DIR, f"{ticker}_{date_str}.json")
    
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

    msg = f"  📊 {ticker} データ取得中..."
    if as_of_date:
        msg += f" (基準日: {as_of_date.strftime('%Y-%m-%d')})"
    print(msg)
    
    try:
        stock = yf.Ticker(ticker)
        
        start_date = None
        end_date = None
        if as_of_date:
            # 過去1年分のデータ（テクニカル計算用）
            start_date = (as_of_date - timedelta(days=400)).strftime('%Y-%m-%d')
            end_date = (as_of_date + timedelta(days=1)).strftime('%Y-%m-%d')
            hist = stock.history(start=start_date, end=end_date)
            # yfinanceはtz-awareなindexを返す場合があるため、tz-naiveに変換
            if hist.index.tz is not None:
                hist.index = hist.index.tz_localize(None)
            hist = hist[hist.index <= pd.Timestamp(as_of_date)]
        else:
            hist = stock.history(period="1y")

        if hist.empty:
            print(f"  ⚠️ {ticker}: No price data found")
            return {"ticker": ticker, "name": ticker, "metrics": {}, "technical": {}}

        # 直近の株価
        latest = hist.iloc[-1]
        current_price = latest['Close']
        
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
                    
                    if d_naive <= as_of_naive:
                        valid_col_indices.append(i)
                else:
                    valid_col_indices.append(i)
            
            if not valid_col_indices:
                return None
            
            valid_cols = df_quarterly.columns[valid_col_indices]
            # 日付としてソートして最新を取得
            sorted_cols = sorted(valid_cols, key=pd.to_datetime, reverse=True)
            return df_quarterly[sorted_cols[0]]

        fin_latest = get_latest_financial(stock.quarterly_financials)
        if fin_latest is None:
            fin_latest = get_latest_financial(stock.financials)

        bs_latest  = get_latest_financial(stock.quarterly_balance_sheet)
        if bs_latest is None:
            bs_latest = get_latest_financial(stock.balance_sheet)

        cf_latest  = get_latest_financial(stock.quarterly_cashflow)
        if cf_latest is None:
            cf_latest = get_latest_financial(stock.cashflow)

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

        # --- Metrics 構築 ---
        metrics = {}
        
        # 1. ROE
        net_income = get_val(fin_latest, ['Net Income', 'Net Income Common Stockholders', 'Net Income Including Noncontrolling Interests'])
        equity     = get_val(bs_latest, ['Total Stockholder Equity', 'Stockholders Equity', 'Total Equity Gross Minority Interest', 'Total Equity'])
        if net_income and equity and equity != 0:
            metrics['roe'] = round((net_income / equity) * 100, 2)
        else:
            # Fallback for some Japanese tickers
            metrics['roe'] = info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else None

        # 2. 営業利益率
        op_income = get_val(fin_latest, ['Operating Income', 'EBIT', 'Operating Revenue', 'Total Revenue']) # Fallback to Revenue if Op Income missing (rare but happens)
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

        # 5. R&D比率
        # yfinanceではR&D取得が不安定なため、バックテストでは省略(0)
        metrics['rd_ratio'] = 0 
        
        # 6. PER, PBR
        if as_of_date:
            shares = get_val(bs_latest, ['Share Issued', 'Ordinary Shares Number'])
            eps = (net_income * 4) / shares if net_income and shares else None
            
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
            metrics['dividend_yield'] = (info.get('dividendYield') or 0) * 100

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
        
        # --- ATR (Average True Range) ---
        if len(hist) >= 15:
            high = hist['High']
            low = hist['Low']
            close = hist['Close'].shift(1)
            tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
            atr = tr.rolling(window=14).mean().iloc[-1]
            technical['atr'] = round(atr, 2)
            technical['atr_pct'] = round((atr / current_price) * 100, 2)
        
        if not as_of_date:
            technical['analyst_target'] = info.get('targetMeanPrice')

        name = info.get('longName', ticker) if not as_of_date else ticker
        sector = info.get('sector', "Unknown") if not as_of_date else "Unknown"
        currency = info.get('currency', 'USD') if not as_of_date else 'USD'

        result_data = {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "currency": currency,
            "metrics": metrics,
            "technical": technical,
            "technical": technical,
            "macro": macro_info,
            "news": [],
            "description": ""
        }
        
        # --- Save to Cache ---
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  ⚠️ キャッシュ保存エラー: {e}")
            
        return result_data

    except Exception as e:
        print(f"  ⚠️ {ticker} 取得失敗: {e}")
        return {"ticker": ticker, "name": ticker, "currency": "USD",
                "metrics": {}, "technical": {}, "news": [], "description": ""}
