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

def _fetch_macro_data() -> dict:
    """
    マクロ指標をyfinanceから取得。
    v1.2: ^IRX (2年債), HYG (ハイイールド債) を追加
    """
    indicators = {}

    tickers = {
        'us10y':  '^TNX',       # 米10年債利回り
        'us2y':   '^IRX',       # 米2年債利回り (逆イールド判定用)
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
                
                # 1ヶ月前との変化率
                change_1m = 0
                if len(hist) >= 20:
                    prev = hist['Close'].iloc[-20]
                    change_1m = (current - prev) / prev * 100

                indicators[key] = {
                    'current': round(current, 2),
                    'ma20': round(ma20, 2),
                    'change_1m': round(change_1m, 1),
                }
        except Exception as e:
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
    us2y = indicators.get('us2y', {}).get('current', 4.0)
    hyg_curr = indicators.get('hyg', {}).get('current', 0)
    hyg_ma20 = indicators.get('hyg', {}).get('ma20', 0)
    
    rate_change = indicators.get('us10y', {}).get('change_1m', 0)

    # 1. 逆イールド判定 (10Y - 2Y < -0.1%)
    # ^TNX, ^IRX は "4.2" (=4.2%) のように返ってくるためそのまま差分計算
    yield_spread = us10y - us2y
    if yield_spread <= -0.1:
        return "YIELD_INVERSION", f"逆イールド発生 (10Y-2Y: {yield_spread:.2f}%) — 景気後退シグナル"

    # 2. 信用リスク判定 (HYGが20日移動平均から -3% 以上乖離)
    if hyg_ma20 > 0:
        hyg_drop = (hyg_curr - hyg_ma20) / hyg_ma20 * 100
        if hyg_drop <= -3.0:
            return "RISK_OFF", f"信用スプレッド拡大 (HYG急落: {hyg_drop:.1f}%) — 資金収縮警戒"

    # 3. VIX判定
    if vix >= 25:
        return "RISK_OFF", f"VIX高騰 ({vix:.0f}) — 恐怖指数上昇"

    # 4. 金利トレンド判定
    if rate_change > 5.0: # 1ヶ月で5%以上上昇 (例 4.0% -> 4.2%)
        return "RATE_HIKE", f"金利上昇基調 (10Y: {us10y}%, 1M: +{rate_change}%)"
    elif rate_change < -5.0:
        return "RATE_CUT", f"金利低下基調 (10Y: {us10y}%, 1M: {rate_change}%)"

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
        "_default":         {"fundamental": 0, "valuation": +0.05, "technical": 0, "qualitative": -0.05},
    },
    "RATE_CUT": {
        "Technology":       {"fundamental": -0.05, "valuation": -0.05, "technical": +0.05, "qualitative": +0.05},
        "_default":         {"fundamental": 0, "valuation": -0.05, "technical": +0.05, "qualitative": 0},
    },
    "RISK_OFF": {
        "Consumer Defensive": {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
        "_default":         {"fundamental": +0.10, "valuation": 0, "technical": +0.05, "qualitative": -0.15},
    },
    "RISK_ON": {
        "_default":         {"fundamental": -0.05, "valuation": 0, "technical": 0, "qualitative": +0.05},
    },
    "NEUTRAL": {
        "_default":         {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
    },
}


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
    for k in ['us10y', 'us2y', 'vix', 'hyg']:
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
