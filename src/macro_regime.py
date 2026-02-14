"""
macro_regime.py - マクロ環境（Regime）判定モジュール
====================================================
金利, 為替, VIX, 原油から現在の相場環境を自動判定し、
セクター別のスコア重み補正テーブルを返す。

環境タイプ:
  RISK_ON    — VIX低位, 株価上昇基調
  RISK_OFF   — VIX高位, 資金退避ムード
  RATE_HIKE  — 金利上昇局面
  RATE_CUT   — 金利低下局面

出力:
  {
    "regime": "RATE_HIKE",
    "indicators": {"us10y": 4.3, "vix": 18, ...},
    "weight_adjustments": {"fundamental": 0, "valuation": +0.10, ...},
    "description": "金利上昇局面: グロース株のバリュエーション方面に厳しく"
  }
"""

import yfinance as yf


def _fetch_macro_data() -> dict:
    """マクロ指標をyfinanceから取得"""
    indicators = {}

    tickers = {
        'us10y': '^TNX',       # 米10年債利回り
        'vix':   '^VIX',       # 恐怖指数
        'usdjpy': 'USDJPY=X',  # ドル円
        'oil':   'CL=F',       # WTI原油先物
    }

    for key, symbol in tickers.items():
        try:
            data = yf.Ticker(symbol)
            hist = data.history(period="3mo")
            if not hist.empty:
                current = hist['Close'].iloc[-1]
                ma20 = hist['Close'].rolling(20).mean().iloc[-1]
                change_1m = 0
                if len(hist) >= 20:
                    prev = hist['Close'].iloc[-20]
                    change_1m = round((current - prev) / prev * 100, 1)

                indicators[key] = {
                    'current': round(current, 2),
                    'ma20': round(ma20, 2),
                    'change_1m': change_1m,
                }
        except Exception as e:
            print(f"  ⚠️ {key} 取得失敗: {e}")

    return indicators


def _determine_regime(indicators: dict) -> tuple[str, str]:
    """マクロ指標から相場環境を判定する"""

    vix = indicators.get('vix', {})
    us10y = indicators.get('us10y', {})

    vix_current = vix.get('current', 20)
    rate_change = us10y.get('change_1m', 0)
    rate_current = us10y.get('current', 4.0)

    # 判定ロジック
    if vix_current >= 30:
        return "RISK_OFF", f"VIX {vix_current:.0f} — 恐怖指数高位。リスク回避局面"
    elif rate_change > 0.3:
        return "RATE_HIKE", f"米10年債 {rate_current:.2f}% (1M: +{rate_change:.1f}%) — 金利上昇局面"
    elif rate_change < -0.3:
        return "RATE_CUT", f"米10年債 {rate_current:.2f}% (1M: {rate_change:.1f}%) — 金利低下局面"
    elif vix_current < 15:
        return "RISK_ON", f"VIX {vix_current:.0f} — 低ボラ環境。リスクオン"
    else:
        return "NEUTRAL", f"VIX {vix_current:.0f}, 金利 {rate_current:.2f}% — ニュートラル"


# セクター × 環境 の重み補正テーブル
# 値は各軸の重みに対する加減算（合計が0になるよう調整）
REGIME_WEIGHT_TABLE = {
    "RATE_HIKE": {
        # 金利上昇 → グロース株の割安度を厳しく、バリュー株に有利
        "Technology":       {"fundamental": 0, "valuation": +0.10, "technical": 0, "qualitative": -0.10},
        "Healthcare":       {"fundamental": 0, "valuation": +0.05, "technical": 0, "qualitative": -0.05},
        "Financial Services": {"fundamental": +0.05, "valuation": 0, "technical": -0.05, "qualitative": 0},
        "_default":         {"fundamental": 0, "valuation": +0.05, "technical": 0, "qualitative": -0.05},
    },
    "RATE_CUT": {
        # 金利低下 → グロース株に追い風
        "Technology":       {"fundamental": -0.05, "valuation": -0.05, "technical": +0.05, "qualitative": +0.05},
        "Financial Services": {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
        "_default":         {"fundamental": 0, "valuation": -0.05, "technical": +0.05, "qualitative": 0},
    },
    "RISK_OFF": {
        # リスク回避 → ディフェンシブ重視、テクニカルの比重up
        "Technology":       {"fundamental": +0.05, "valuation": 0, "technical": +0.05, "qualitative": -0.10},
        "Consumer Defensive": {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
        "_default":         {"fundamental": +0.05, "valuation": 0, "technical": +0.05, "qualitative": -0.10},
    },
    "RISK_ON": {
        # リスクオン → 定性・成長ストーリー重視
        "_default":         {"fundamental": -0.05, "valuation": 0, "technical": 0, "qualitative": +0.05},
    },
    "NEUTRAL": {
        "_default":         {"fundamental": 0, "valuation": 0, "technical": 0, "qualitative": 0},
    },
}


def get_weight_adjustments(regime: str, sector: str) -> dict:
    """環境×セクターに応じた重み補正値を返す"""
    table = REGIME_WEIGHT_TABLE.get(regime, REGIME_WEIGHT_TABLE["NEUTRAL"])
    adjustments = table.get(sector, table.get("_default", {}))
    return adjustments


def detect_regime() -> dict:
    """
    マクロ環境を判定して重み補正データを返す。

    Returns:
        dict: regime, indicators, description, get_adjustments(sector) 呼び出し可能
    """
    print(f"  🌍 マクロ環境を判定中...")
    indicators = _fetch_macro_data()
    regime, description = _determine_regime(indicators)
    print(f"  📊 Regime: {regime} — {description}")

    # 指標のサマリーを作成
    summary_parts = []
    for key, data in indicators.items():
        labels = {'us10y': '米10年債', 'vix': 'VIX', 'usdjpy': 'USD/JPY', 'oil': 'WTI原油'}
        label = labels.get(key, key)
        summary_parts.append(f"{label}: {data['current']} (1M: {data['change_1m']:+.1f}%)")

    return {
        "regime": regime,
        "description": description,
        "indicators": {k: v['current'] for k, v in indicators.items()},
        "indicator_details": indicators,
        "summary": " | ".join(summary_parts),
    }


# テスト実行
if __name__ == "__main__":
    import json
    result = detect_regime()
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # テスト: Technology × RATE_HIKE
    adj = get_weight_adjustments("RATE_HIKE", "Technology")
    print(f"\nTech × RATE_HIKE adjustments: {adj}")
