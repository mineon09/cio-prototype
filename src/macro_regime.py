"""
macro_regime.py - マクロ環境（Regime）判定モジュール v1.2
====================================================
金利, 為替, VIX, 原油, 信用スプレッドから現在の相場環境を自動判定し、
セクター別のスコア重み補正テーブルを返す。

v1.2 Update:
- 逆イールド (Yield Curve Inversion) の検出
- 信用スプレッド (HYG) の急落検出
"""

import yfinance as yf
import pandas as pd
from datetime import datetime

def _fetch_macro_data() -> dict:
    """
    マクロ指標をyfinanceから取得。
    v1.2: ^IRX (2年債), HYG (ハイイールド債) を追加
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
                        # 例) 4.0% -> 4.2% の場合、0.2ポイント差 (+20bps)となる
                        change_1m = current - prev
                    else:
                        change_1m = (current - prev) / prev * 100

                indicators[key] = {
                    'current': round(current, 2),
                    'ma20': round(ma20, 2),
                    'change_1m': round(change_1m, 2),  # 金利はポイント差、他は%
                }
        except Exception:
             # print(f"  ⚠️ {key} 取得失敗: {e}")
             indicators[key] = {'current': 0, 'ma20': 0, 'change_1m': 0}

    return indicators


def _determine_regime(indicators: dict) -> tuple[str, str]:
    """
    マクロ指標から相場環境を判定する (優先度順)
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
    # ^TNX, ^IRX は "4.2" (=4.2%) のように返ってくるためそのまま差分計算
    yield_spread = us10y - us3m
    if yield_spread <= -0.1:
        return "YIELD_INVERSION", f"逆イールド発生 (10Y-3M: {yield_spread:.2f}%) — 景気後退シグナル"

    # 2. 信用リスク判定 (HYGが20日移動平均から -3% 以上乖離)
    if hyg_ma20 > 0:
        hyg_drop = (hyg_curr - hyg_ma20) / hyg_ma20 * 100
        if hyg_drop <= -3.0:
            return "RISK_OFF", f"信用スプレッド拡大 (HYG急落: {hyg_drop:.1f}%) — 資金収縮警戒"

    # 3. VIX判定 (優先度高)
    if vix >= 25:
        # A-4: VIX高騰と金利急騰が同時発生した場合、スタグフレーション的 RISK_OFF として扱う
        if rate_change > 0.5:
             return "RISK_OFF", f"スタグフレーション警戒 (VIX: {vix:.0f}, 10Y上昇 +{rate_change:.2f}pt) — 金利・恐怖の同時高騰"
        return "RISK_OFF", f"VIX高騰 ({vix:.0f}) — 恐怖指数上昇"

    # 4. 金利トレンド判定
    # A-4: 変化率はポイント差 (0.5pt = 50bps) で判定する
    if rate_change > 0.50: # 1ヶ月で0.5% (50bps) 以上上昇 (例 4.0% -> 4.5%)
        return "RATE_HIKE", f"金利上昇基調 (10Y: {us10y}%, 1M: +{rate_change:.2f}pt)"
    elif rate_change < -0.50:
        return "RATE_CUT", f"金利低下基調 (10Y: {us10y}%, 1M: {rate_change:.2f}pt)"

    # 5. 平時
    if vix < 18:
        return "RISK_ON", f"VIX安定 ({vix:.0f}) — リスクオン環境"
    
    return "NEUTRAL", f"ニュートラル (VIX {vix:.0f}, 10Y {us10y}%)"


# セクター × 環境 の重み補正テーブル
REGIME_WEIGHT_TABLE = {
    "YIELD_INVERSION": {
        # 逆イールド: 将来の景気後退 → ファンダメンタル(財務健全性)を最重視
        "_default":         {"fundamental": +0.15, "valuation": +0.05, "technical": -0.10, "qualitative": -0.10},
        "Financial Services": {"fundamental": +0.20, "valuation": 0, "technical": -0.10, "qualitative": -0.10}, # 銀行は逆イールドで利鞘縮小
    },
    "RATE_HIKE": {
        "Technology":       {"fundamental": 0, "valuation": +0.10, "technical": 0, "qualitative": -0.10},
        "Financial Services": {"fundamental": 0, "valuation": -0.05, "technical": +0.10, "qualitative": +0.05}, # 銀行は金利上昇で有利
        "_default":         {"fundamental": 0, "valuation": +0.05, "technical": 0, "qualitative": -0.05},
    },
    "RATE_CUT": {
        "Technology":       {"fundamental": -0.05, "valuation": -0.05, "technical": +0.05, "qualitative": +0.05},
        "Financial Services": {"fundamental": +0.05, "valuation": +0.10, "technical": -0.10, "qualitative": -0.05}, # 銀行は金利低下で弱体化
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

# セクター別の環境適性（銀行株などは特定環境で閾値を調整するために使用可能）
SECTOR_REGIME_AFFINITY = {
    "Financial Services": {
        "positive": ["RATE_HIKE", "NEUTRAL"],
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
    例：全体は RATE_CUT でも、銀行株にとってはネガティブなので 
    ロジック上でリスク許容度を下げるなどの判断に使える。
    """
    # 銀行株で RATE_CUT の場合、内部的に "慎重" な判定を促すフラグとして扱えるが
    # ここではシンプルにベースを返す。
    return base_regime


def get_weight_adjustments(regime: str, sector: str) -> dict:
    """環境×セクターに応じた重み補正値を返す"""
    table = REGIME_WEIGHT_TABLE.get(regime, REGIME_WEIGHT_TABLE["NEUTRAL"])
    # セクター特有の設定があればそれを、なければ _default を使う
    adjustments = table.get(sector, table.get("_default", {}))
    return adjustments


def detect_regime() -> dict:
    """
    マクロ環境を判定して重み補正データを返す。
    Returns:
        dict: regime, description, indicators, summary
    """
    print(f"  🌍 マクロ環境を判定中 (v1.2)...")
    indicators = _fetch_macro_data()
    regime, description = _determine_regime(indicators)
    print(f"  📊 Regime: {regime} — {description}")

    # サマリー作成
    summary_parts = []
    # 主な指標だけ抜粋
    for k in ['us10y', 'us3m', 'vix', 'hyg']:
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
    result = detect_regime()
    print(json.dumps(result, indent=2, ensure_ascii=False))


# ---------------------------------------------------------
# v1.3: Historical Regime Detection (For Backtest)
# A-2: キャッシュのクラス化（TTL + clear() + Mock汚染防止）
# ---------------------------------------------------------

class MacroHistoryCache:
    """マクロ指標の履歴キャッシュ。TTL付きで再取得をサポート。"""
    def __init__(self):
        self._cache: dict = {}
        self._fetched_at: datetime | None = None
        self._has_mock: bool = False  # Mock データの混入フラグ

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


_macro_cache = MacroHistoryCache()

def get_macro_regime(current_date, config: dict = None) -> str:
    """
    指定日のマクロレジームを判定して返す（バックテスト要）。
    全期間のデータを一度だけ取得し、メモリにキャッシュして高速化。
    A-2: グローバル dict → クラスベースのキャッシュに変更。
    """
    from datetime import timedelta
    
    global _macro_cache
    
    tickers = {
        'us10y':  '^TNX',
        'us3m':   '^IRX',
        'vix':    '^VIX',
        'hyg':    'HYG',
    }

    # キャッシュが無効なら一括取得 (過去10年分)
    if not _macro_cache.is_valid():
        _macro_cache.clear()  # 古い Mock データも含めてクリア
        print("  📥 Fetching Macro Data for Backtest (Once)...")
        start_cache = (current_date - timedelta(days=365*10)).strftime('%Y-%m-%d')
        end_cache = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        cache_data = {}
        for key, symbol in tickers.items():
            try:
                df = yf.download(symbol, start=start_cache, end=end_cache, progress=False)
                # MultiIndex handling
                if isinstance(df.columns, pd.MultiIndex):
                    try:
                        df = df.xs(symbol, axis=1, level=1)
                    except:
                        df.columns = df.columns.get_level_values(0)
                        
                # Timezone remove
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                
                if df.empty: raise Exception("Empty Data")
                cache_data[key] = df
            except Exception as e:
                print(f"  ⚠️ Macro Fetch Error ({symbol}): {e} -> Using Mock Data")
                # Mock Data Generation
                dates = pd.date_range(start=start_cache, end=end_cache, freq='D')
                mock_vals = {
                    'us10y': 4.0, 'us2y': 4.0, 'vix': 20.0, 'hyg': 75.0
                }
                cache_data[key] = pd.DataFrame(
                    {'Close': [mock_vals.get(key, 0.0)] * len(dates)},
                    index=dates
                )
                _macro_cache._has_mock = True
        
        _macro_cache.data = cache_data

    indicators = {}
    
    # メモリから検索
    for key, df in _macro_cache.data.items():
        if df.empty:
            indicators[key] = {'current': 0, 'ma20': 0, 'change_1m': 0}
            continue

        # current_date以前のデータ
        past_df = df[df.index <= pd.Timestamp(current_date)]
        if past_df.empty:
            indicators[key] = {'current': 0, 'ma20': 0, 'change_1m': 0}
            continue
            
        try:
            closes = past_df['Close']
            current_val = float(closes.iloc[-1])
            
            # MA20
            ma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else current_val
            
            # Change 1M
            change_1m = 0
            if len(closes) >= 20:
                prev = float(closes.iloc[-20])
                if prev != 0:
                    if key in ['us10y', 'us3m']:
                        change_1m = current_val - prev
                    else:
                        change_1m = (current_val - prev) / prev * 100
                    
            indicators[key] = {
                'current': current_val,
                'ma20': ma20,
                'change_1m': change_1m
            }
        except Exception:
             indicators[key] = {'current': 0, 'ma20': 0, 'change_1m': 0}
            
    regime, _ = _determine_regime(indicators)
    return regime
