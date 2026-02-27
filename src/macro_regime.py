"""
macro_regime.py - マクロ環境（Regime）判定モジュール v2.0
====================================================
金利, 為替, VIX, 原油, 信用スプレッドから現在の相場環境を自動判定し、
セクター別のスコア重み補正テーブルを返す。

v2.0 Update (案C):
- 日本株向け独自マクロ判定 (_determine_jp_regime)
- US/JP キャッシュ完全分離 (_macro_cache_us / _macro_cache_jp)
- ticker引数による自動ルーティング
"""

import yfinance as yf
import pandas as pd
from datetime import datetime


# ---------------------------------------------------------
# 日本株判定ヘルパー (edinet_client.py にもあるが循環 import 回避)
# ---------------------------------------------------------
def _is_japanese_stock(ticker: str) -> bool:
    return ticker.endswith('.T')


# =========================================================
# US マクロ指標の取得・判定 (既存ロジック)
# =========================================================

def _fetch_macro_data() -> dict:
    """
    米国マクロ指標をyfinanceから取得。
    """
    indicators = {}

    tickers = {
        'us10y':  '^TNX',       # 米10年債利回り
        'us3m':   '^IRX',       # 米3ヶ月物T-Bill (逆イールド判定用)
        'vix':    '^VIX',       # 恐怖指数
        'usdjpy': 'JPY=X',      # ドル円
        'oil':    'CL=F',       # WTI原油先物
        'hyg':    'HYG',        # ハイイールド債ETF (信用リスク)
    }

    for key, symbol in tickers.items():
        try:
            data = yf.Ticker(symbol)
            hist = data.history(period="3mo")
            if not hist.empty:
                current = hist['Close'].iloc[-1]
                ma20 = hist['Close'].rolling(20).mean().iloc[-1]
                
                # 1ヶ月前との変化
                change_1m = 0
                if len(hist) >= 20:
                    prev = hist['Close'].iloc[-20]
                    if key in ['us10y', 'us3m']:
                        # A-4: 金利の場合は相対変化率ではなく、絶対差分（bp相当）を使用する
                        change_1m = current - prev
                    else:
                        change_1m = (current - prev) / prev * 100

                indicators[key] = {
                    'current': round(current, 2),
                    'ma20': round(ma20, 2),
                    'change_1m': round(change_1m, 2),
                }
        except Exception:
             indicators[key] = {'current': 0, 'ma20': 0, 'change_1m': 0}

    return indicators


def _determine_regime(indicators: dict) -> tuple[str, str]:
    """
    米国マクロ指標から相場環境を判定する (優先度順)
    1. YIELD_INVERSION (逆イールド)
    2. RISK_OFF (VIX高騰 or HYG急落)
    3. RATE_HIKE / RATE_CUT (金利動向)
    4. RISK_ON (VIX安定)
    """

    vix = indicators.get('vix', {}).get('current', 20)
    us10y = indicators.get('us10y', {}).get('current', 4.0)
    us3m = indicators.get('us3m', {}).get('current', 4.0)
    hyg_curr = indicators.get('hyg', {}).get('current', 0)
    hyg_ma20 = indicators.get('hyg', {}).get('ma20', 0)
    
    rate_change = indicators.get('us10y', {}).get('change_1m', 0)

    # 1. 逆イールド判定 (10Y - 3M < -0.1%)
    yield_spread = us10y - us3m
    if yield_spread <= -0.1:
        return "YIELD_INVERSION", f"逆イールド発生 (10Y-3M: {yield_spread:.2f}%) — 景気後退シグナル"

    # 2. 信用リスク判定 (HYGが20日移動平均から -3% 以上乖離)
    if hyg_ma20 > 0:
        hyg_drop = (hyg_curr - hyg_ma20) / hyg_ma20 * 100
        if hyg_drop <= -3.0:
            return "RISK_OFF", f"信用スプレッド拡大 (HYG急落: {hyg_drop:.1f}%) — 資金収縮警戒"

    # 3. VIX判定
    if vix >= 25:
        if rate_change > 0.5:
             return "RISK_OFF", f"スタグフレーション警戒 (VIX: {vix:.0f}, 10Y上昇 +{rate_change:.2f}pt) — 金利・恐怖の同時高騰"
        return "RISK_OFF", f"VIX高騰 ({vix:.0f}) — 恐怖指数上昇"

    # 4. 金利トレンド判定
    if rate_change > 0.50:
        return "RATE_HIKE", f"金利上昇基調 (10Y: {us10y}%, 1M: +{rate_change:.2f}pt)"
    elif rate_change < -0.50:
        return "RATE_CUT", f"金利低下基調 (10Y: {us10y}%, 1M: {rate_change:.2f}pt)"

    # 5. 平時
    if vix < 18:
        return "RISK_ON", f"VIX安定 ({vix:.0f}) — リスクオン環境"
    
    return "NEUTRAL", f"ニュートラル (VIX {vix:.0f}, 10Y {us10y}%)"


# =========================================================
# JP マクロ指標の取得・判定 (v2.0 案C)
# =========================================================

def _fetch_jp_macro_data() -> dict:
    """
    日本株向けマクロ指標をyfinanceから取得。
    取得対象: ドル円(JPY=X), 日経平均(^N225), VIX(^VIX)
    """
    indicators = {}

    tickers = {
        'usdjpy': 'JPY=X',     # ドル円
        'nikkei': '^N225',      # 日経平均
        'vix':    '^VIX',       # VIX (グローバル共通)
    }

    for key, symbol in tickers.items():
        try:
            data = yf.Ticker(symbol)
            # MA200 計算のために 1年分取得
            hist = data.history(period="1y")
            if not hist.empty:
                current = hist['Close'].iloc[-1]
                ma20 = hist['Close'].rolling(20).mean().iloc[-1]
                ma75 = hist['Close'].rolling(75).mean().iloc[-1] if len(hist) >= 75 else current
                ma200 = hist['Close'].rolling(200).mean().iloc[-1] if len(hist) >= 200 else current

                # 1ヶ月前との変化率 (%)
                change_1m = 0
                if len(hist) >= 20:
                    prev = hist['Close'].iloc[-20]
                    if prev != 0:
                        change_1m = (current - prev) / prev * 100

                indicators[key] = {
                    'current': round(float(current), 2),
                    'ma20': round(float(ma20), 2),
                    'ma75': round(float(ma75), 2),
                    'ma200': round(float(ma200), 2),
                    'change_1m': round(change_1m, 2),
                }
        except Exception:
            indicators[key] = {'current': 0, 'ma20': 0, 'ma75': 0, 'ma200': 0, 'change_1m': 0}

    return indicators


def _determine_jp_regime(indicators: dict) -> tuple[str, str]:
    """
    日本株向けマクロ指標から相場環境を判定する (優先度順)
    1. RISK_OFF — VIX >= 25 (グローバル共通)
    2. BOJ_HIKE — ドル円1ヶ月変化率 <= -3% (急激な円高 = 日銀利上げシグナル)
    3. YEN_WEAK — ドル円 > MA200 かつ変化率 > 0 (円安トレンド)
    4. YEN_STRONG — ドル円 < MA200 かつ変化率 < -1% (円高トレンド)
    5. NIKKEI_BULL — 日経 > MA20 かつ MA75 かつ騰落率 > 3% (明確な上昇)
    6. NEUTRAL
    """
    vix = indicators.get('vix', {}).get('current', 20)
    usdjpy = indicators.get('usdjpy', {}).get('current', 150)
    usdjpy_ma200 = indicators.get('usdjpy', {}).get('ma200', 150)
    usdjpy_change = indicators.get('usdjpy', {}).get('change_1m', 0)

    nikkei = indicators.get('nikkei', {}).get('current', 30000)
    nikkei_ma20 = indicators.get('nikkei', {}).get('ma20', 30000)
    nikkei_ma75 = indicators.get('nikkei', {}).get('ma75', 30000)
    nikkei_change = indicators.get('nikkei', {}).get('change_1m', 0)

    # 1. グローバル RISK_OFF (最優先)
    if vix >= 25:
        return "RISK_OFF", f"グローバルリスクオフ (VIX: {vix:.0f}) — 恐怖指数上昇"

    # 2. BOJ_HIKE: 急激な円高 (1ヶ月で-3%以上のドル円下落)
    # VIX < 25 の状態での円高 = 日銀主導の可能性が高い
    if usdjpy_change <= -3.0:
        return "BOJ_HIKE", (
            f"日銀利上げシグナル (ドル円: {usdjpy:.1f}円, "
            f"1M: {usdjpy_change:+.1f}%) — 急激な円高"
        )

    # 3. YEN_WEAK: ドル円 > MA200 かつ上昇中
    if usdjpy > usdjpy_ma200 and usdjpy_change > 0:
        return "YEN_WEAK", (
            f"円安局面 (ドル円: {usdjpy:.1f}円 > MA200: {usdjpy_ma200:.1f}円, "
            f"1M: {usdjpy_change:+.1f}%) — 輸出企業に有利"
        )

    # 4. YEN_STRONG: ドル円 < MA200 かつ下落中
    if usdjpy < usdjpy_ma200 and usdjpy_change < -1.0:
        return "YEN_STRONG", (
            f"円高局面 (ドル円: {usdjpy:.1f}円 < MA200: {usdjpy_ma200:.1f}円, "
            f"1M: {usdjpy_change:+.1f}%) — 内需企業に有利"
        )

    # 5. NIKKEI_BULL: 日経がMA20 & MA75を上回り、かつ騰落率+3%以上
    if nikkei > nikkei_ma20 and nikkei > nikkei_ma75 and nikkei_change > 3.0:
        return "NIKKEI_BULL", (
            f"日経上昇トレンド (日経: {nikkei:,.0f}, MA20: {nikkei_ma20:,.0f}, "
            f"MA75: {nikkei_ma75:,.0f}, 1M: {nikkei_change:+.1f}%) — リスクオン"
        )

    # 6. 平時
    return "NEUTRAL", (
        f"ニュートラル (ドル円: {usdjpy:.1f}円, "
        f"日経: {nikkei:,.0f}, VIX: {vix:.0f})"
    )


# =========================================================
# セクター × 環境 の重み補正テーブル
# =========================================================

# --- US 用 (既存) ---
REGIME_WEIGHT_TABLE = {
    "YIELD_INVERSION": {
        "_default":         {"fundamental": +0.15, "valuation": +0.05, "technical": -0.10, "qualitative": -0.10},
        "Financial Services": {"fundamental": +0.20, "valuation": 0, "technical": -0.10, "qualitative": -0.10},
    },
    "RATE_HIKE": {
        "Technology":       {"fundamental": 0, "valuation": +0.10, "technical": 0, "qualitative": -0.10},
        "Financial Services": {"fundamental": 0, "valuation": -0.05, "technical": +0.10, "qualitative": +0.05},
        "_default":         {"fundamental": 0, "valuation": +0.05, "technical": 0, "qualitative": -0.05},
    },
    "RATE_CUT": {
        "Technology":       {"fundamental": -0.05, "valuation": -0.05, "technical": +0.05, "qualitative": +0.05},
        "Financial Services": {"fundamental": +0.05, "valuation": +0.10, "technical": -0.10, "qualitative": -0.05},
        "_default":         {"fundamental": 0, "valuation": -0.05, "technical": +0.05, "qualitative": 0},
    },
    "RISK_OFF": {
        "Consumer Defensive": {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
        "_default":         {"fundamental": +0.10, "valuation": 0, "technical": +0.05, "qualitative": -0.15},
    },
    "RISK_ON": {
        "Financial Services": {"fundamental": 0, "valuation": -0.05, "technical": +0.05, "qualitative": 0},
        "_default":         {"fundamental": -0.05, "valuation": 0, "technical": 0, "qualitative": +0.05},
    },
    "NEUTRAL": {
        "_default":         {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
    },
}

# --- JP 用 (v2.0) ---
JP_REGIME_WEIGHT_TABLE = {
    "BOJ_HIKE": {
        "_default":           {"fundamental": +0.10, "valuation": 0, "technical": +0.05, "qualitative": -0.15},
        "Financial Services": {"fundamental": +0.20, "valuation": -0.05, "technical": +0.10, "qualitative": -0.15},
        "Real Estate":        {"fundamental": -0.10, "valuation": +0.10, "technical": 0, "qualitative": 0},
        "Technology":         {"fundamental": 0, "valuation": +0.05, "technical": +0.10, "qualitative": -0.15},
    },
    "YEN_WEAK": {
        "_default":           {"fundamental": 0, "valuation": 0, "technical": +0.05, "qualitative": -0.05},
        "Industrials":        {"fundamental": +0.10, "valuation": -0.05, "technical": +0.05, "qualitative": -0.10},
        "Consumer Defensive": {"fundamental": -0.05, "valuation": +0.05, "technical": 0, "qualitative": 0},
    },
    "YEN_STRONG": {
        "_default":           {"fundamental": 0, "valuation": +0.05, "technical": 0, "qualitative": -0.05},
        "Industrials":        {"fundamental": -0.10, "valuation": +0.10, "technical": 0, "qualitative": 0},
        "Consumer Defensive": {"fundamental": +0.10, "valuation": -0.05, "technical": 0, "qualitative": -0.05},
    },
    "NIKKEI_BULL": {
        "_default":           {"fundamental": -0.05, "valuation": 0, "technical": +0.05, "qualitative": 0},
    },
    "RISK_OFF": {
        # グローバル RISK_OFF — US と同じ重み補正
        "Consumer Defensive": {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
        "_default":           {"fundamental": +0.10, "valuation": 0, "technical": +0.05, "qualitative": -0.15},
    },
    "NEUTRAL": {
        "_default":           {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
    },
}

# JP レジーム名の集合 (テーブル選択に使用)
_JP_REGIMES = {"BOJ_HIKE", "YEN_WEAK", "YEN_STRONG", "NIKKEI_BULL"}


# セクター別の環境適性
SECTOR_REGIME_AFFINITY = {
    "Financial Services": {
        "positive": ["RATE_HIKE", "NEUTRAL", "BOJ_HIKE"],
        "negative": ["RATE_CUT", "RISK_OFF"]
    },
    "Technology": {
        "positive": ["RATE_CUT", "RISK_ON"],
        "negative": ["RATE_HIKE"]
    }
}

def get_sector_adjusted_regime(base_regime: str, sector: str) -> str:
    """
    セクター特性を考慮してRegimeを実効的に調整する。
    """
    return base_regime


def get_weight_adjustments(regime: str, sector: str) -> dict:
    """環境×セクターに応じた重み補正値を返す (US/JP 自動選択)"""
    # JP レジームなら JP テーブル、それ以外は US テーブルを参照
    if regime in _JP_REGIMES:
        table_source = JP_REGIME_WEIGHT_TABLE
    else:
        table_source = REGIME_WEIGHT_TABLE
    
    table = table_source.get(regime, table_source.get("NEUTRAL", {"_default": {}}))
    adjustments = table.get(sector, table.get("_default", {}))
    return adjustments


# =========================================================
# 公開API: detect_regime (ライブ分析用)
# =========================================================

def detect_regime(ticker: str = "") -> dict:
    """
    マクロ環境を判定して重み補正データを返す。
    ticker に .T サフィックスがあれば日本株向け判定を使用。
    
    Returns:
        dict: regime, description, indicators, summary
    """
    is_jp = _is_japanese_stock(ticker)
    version = "v2.0-JP" if is_jp else "v2.0-US"
    print(f"  🌍 マクロ環境を判定中 ({version})...")
    
    if is_jp:
        indicators = _fetch_jp_macro_data()
        regime, description = _determine_jp_regime(indicators)
        summary_keys = ['usdjpy', 'nikkei', 'vix']
    else:
        indicators = _fetch_macro_data()
        regime, description = _determine_regime(indicators)
        summary_keys = ['us10y', 'us3m', 'vix', 'hyg']
    
    print(f"  📊 Regime: {regime} — {description}")

    # サマリー作成
    summary_parts = []
    for k in summary_keys:
        if k in indicators:
            val = indicators[k]['current']
            summary_parts.append(f"{k.upper()}: {val}")
    
    return {
        "regime": regime,
        "description": description,
        "indicators": indicators,
        "summary": " | ".join(summary_parts),
    }


# テスト実行
if __name__ == "__main__":
    import json
    # US
    print("=== US Regime ===")
    result_us = detect_regime("AAPL")
    print(json.dumps(result_us, indent=2, ensure_ascii=False))
    # JP
    print("\n=== JP Regime ===")
    result_jp = detect_regime("7203.T")
    print(json.dumps(result_jp, indent=2, ensure_ascii=False))


# ---------------------------------------------------------
# v1.3/v2.0: Historical Regime Detection (For Backtest)
# A-2: キャッシュのクラス化（TTL + clear() + Mock汚染防止）
# v2.0: US/JP キャッシュ完全分離
# ---------------------------------------------------------

class MacroHistoryCache:
    """マクロ指標の履歴キャッシュ。TTL付きで再取得をサポート。"""
    def __init__(self, name: str = ""):
        self._name = name
        self._cache: dict = {}
        self._fetched_at: datetime | None = None
        self._has_mock: bool = False

    def clear(self):
        """キャッシュを明示的にクリア"""
        self._cache = {}
        self._fetched_at = None
        self._has_mock = False

    def is_valid(self, ttl_hours: int = 12) -> bool:
        """キャッシュが有効期限内かどうか"""
        if not self._fetched_at or not self._cache:
            return False
        elapsed = (datetime.now() - self._fetched_at).total_seconds()
        return elapsed < ttl_hours * 3600

    @property
    def data(self) -> dict:
        return self._cache

    @data.setter
    def data(self, value: dict):
        self._cache = value
        self._fetched_at = datetime.now()

    def set_mock(self, key: str, df):
        """Mock データを注入（フラグ付き）"""
        self._cache[key] = df
        self._has_mock = True


# US/JP キャッシュの完全分離 (v2.0)
_macro_cache_us = MacroHistoryCache("US")
_macro_cache_jp = MacroHistoryCache("JP")


def _ensure_cache_us(current_date, config: dict = None):
    """US マクロ指標の履歴キャッシュを取得/更新する"""
    from datetime import timedelta
    global _macro_cache_us
    
    tickers = {
        'us10y':  '^TNX',
        'us3m':   '^IRX',
        'vix':    '^VIX',
        'hyg':    'HYG',
    }

    if not _macro_cache_us.is_valid():
        _macro_cache_us.clear()
        print("  📥 Fetching US Macro Data for Backtest (Once)...")
        start_cache = (current_date - timedelta(days=365*10)).strftime('%Y-%m-%d')
        end_cache = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        cache_data = {}
        for key, symbol in tickers.items():
            try:
                df = yf.download(symbol, start=start_cache, end=end_cache, progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    try:
                        df = df.xs(symbol, axis=1, level=1)
                    except Exception:
                        df.columns = df.columns.get_level_values(0)
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                if df.empty: raise Exception("Empty Data")
                cache_data[key] = df
            except Exception as e:
                print(f"  ⚠️ US Macro Fetch Error ({symbol}): {e} -> Using Mock Data")
                dates = pd.date_range(start=start_cache, end=end_cache, freq='D')
                mock_vals = {
                    'us10y': 4.0, 'us3m': 4.0, 'vix': 20.0, 'hyg': 75.0
                }
                cache_data[key] = pd.DataFrame(
                    {'Close': [mock_vals.get(key, 0.0)] * len(dates)},
                    index=dates
                )
                _macro_cache_us._has_mock = True
        
        _macro_cache_us.data = cache_data


def _ensure_cache_jp(current_date, config: dict = None):
    """JP マクロ指標の履歴キャッシュを取得/更新する"""
    from datetime import timedelta
    global _macro_cache_jp
    
    tickers = {
        'usdjpy': 'JPY=X',
        'nikkei': '^N225',
        'vix':    '^VIX',
    }

    if not _macro_cache_jp.is_valid():
        _macro_cache_jp.clear()
        print("  📥 Fetching JP Macro Data for Backtest (Once)...")
        start_cache = (current_date - timedelta(days=365*10)).strftime('%Y-%m-%d')
        end_cache = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        cache_data = {}
        for key, symbol in tickers.items():
            try:
                df = yf.download(symbol, start=start_cache, end=end_cache, progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    try:
                        df = df.xs(symbol, axis=1, level=1)
                    except Exception:
                        df.columns = df.columns.get_level_values(0)
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                if df.empty: raise Exception("Empty Data")
                cache_data[key] = df
            except Exception as e:
                print(f"  ⚠️ JP Macro Fetch Error ({symbol}): {e} -> Using Mock Data")
                dates = pd.date_range(start=start_cache, end=end_cache, freq='D')
                mock_vals = {
                    'usdjpy': 150.0, 'nikkei': 35000.0, 'vix': 20.0
                }
                cache_data[key] = pd.DataFrame(
                    {'Close': [mock_vals.get(key, 0.0)] * len(dates)},
                    index=dates
                )
                _macro_cache_jp._has_mock = True
        
        _macro_cache_jp.data = cache_data


def _build_indicators_from_cache(cache: MacroHistoryCache, current_date,
                                  rate_keys: set = None) -> dict:
    """
    キャッシュから指定日のインジケーターを構築する。
    rate_keys: 金利のように絶対差分で change_1m を計算するキーの集合。
    """
    if rate_keys is None:
        rate_keys = set()
    
    indicators = {}
    for key, df in cache.data.items():
        if df.empty:
            indicators[key] = {'current': 0, 'ma20': 0, 'ma75': 0, 'ma200': 0, 'change_1m': 0}
            continue

        past_df = df[df.index <= pd.Timestamp(current_date)]
        if past_df.empty:
            indicators[key] = {'current': 0, 'ma20': 0, 'ma75': 0, 'ma200': 0, 'change_1m': 0}
            continue
            
        try:
            closes = past_df['Close']
            current_val = float(closes.iloc[-1])
            
            ma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else current_val
            ma75 = float(closes.rolling(75).mean().iloc[-1]) if len(closes) >= 75 else current_val
            ma200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else current_val
            
            change_1m = 0
            if len(closes) >= 20:
                prev = float(closes.iloc[-20])
                if prev != 0:
                    if key in rate_keys:
                        change_1m = current_val - prev
                    else:
                        change_1m = (current_val - prev) / prev * 100
                    
            indicators[key] = {
                'current': current_val,
                'ma20': ma20,
                'ma75': ma75,
                'ma200': ma200,
                'change_1m': change_1m
            }
        except Exception:
             indicators[key] = {'current': 0, 'ma20': 0, 'ma75': 0, 'ma200': 0, 'change_1m': 0}
    
    return indicators


def get_macro_regime(current_date, config: dict = None, ticker: str = "") -> str:
    """
    指定日のマクロレジームを判定して返す（バックテスト用）。
    全期間のデータを一度だけ取得し、メモリにキャッシュして高速化。
    v2.0: ticker に応じて US/JP を自動選択、キャッシュ分離。
    """
    if _is_japanese_stock(ticker):
        _ensure_cache_jp(current_date, config)
        indicators = _build_indicators_from_cache(_macro_cache_jp, current_date)
        regime, _ = _determine_jp_regime(indicators)
    else:
        _ensure_cache_us(current_date, config)
        indicators = _build_indicators_from_cache(
            _macro_cache_us, current_date, rate_keys={'us10y', 'us3m'}
        )
        regime, _ = _determine_regime(indicators)
    
    return regime
