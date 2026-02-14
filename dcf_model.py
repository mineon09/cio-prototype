"""
dcf_model.py - DCF理論株価算出モジュール
==========================================
yfinanceから過去のフリーキャッシュフロー(FCF)を取得し、
Gemini AIで成長シナリオを予測させて理論株価を算出する。

出力:
  {
    "fair_value": 340.0,       # 基本シナリオの理論株価
    "current_price": 285.0,
    "upside": 19.3,            # 上昇余地 (%)
    "margin_of_safety": 16.2,  # 安全域 (%)
    "scenarios": {
      "bull": {"growth": 15, "fair_value": 420},
      "base": {"growth": 10, "fair_value": 340},
      "bear": {"growth": 5,  "fair_value": 260},
    },
    "wacc": 9.5,
    "fcf_history": [...]
  }
"""

import math
import yfinance as yf

try:
    from data_fetcher import call_gemini
except ImportError:
    def call_gemini(prompt, parse_json=False):
        return None


def _get_fcf_history(ticker: str) -> list[float]:
    """過去のフリーキャッシュフロー（FCF）を取得する"""
    try:
        stock = yf.Ticker(ticker)
        cf = stock.cashflow
        if cf is None or cf.empty:
            return []

        fcf_list = []
        ocf_row = None
        capex_row = None

        # Operating Cash Flow
        for name in ['Operating Cash Flow', 'Total Cash From Operating Activities']:
            if name in cf.index:
                ocf_row = name
                break

        # Capital Expenditures
        for name in ['Capital Expenditure', 'Capital Expenditures']:
            if name in cf.index:
                capex_row = name
                break

        if ocf_row and capex_row:
            for col in cf.columns:
                ocf = cf.loc[ocf_row, col]
                capex = cf.loc[capex_row, col]
                if ocf is not None and capex is not None:
                    try:
                        fcf = float(ocf) + float(capex)  # capex is negative
                        fcf_list.append(fcf)
                    except (TypeError, ValueError):
                        pass
        elif ocf_row:
            # capex が取れない場合は OCF の 80% を FCF として推定
            for col in cf.columns:
                ocf = cf.loc[ocf_row, col]
                if ocf is not None:
                    try:
                        fcf_list.append(float(ocf) * 0.8)
                    except (TypeError, ValueError):
                        pass

        return fcf_list[:5]  # 直近5年分
    except Exception as e:
        print(f"  ⚠️ FCF取得失敗: {e}")
        return []


def _estimate_wacc(ticker: str) -> float:
    """簡易WACC（加重平均資本コスト）の推定"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        beta = info.get('beta', 1.0) or 1.0

        # CAPM: Ke = Rf + β × (Rm - Rf)
        risk_free = 4.3   # 米10年債利回り（概算）
        market_premium = 5.5  # 市場リスクプレミアム
        cost_of_equity = risk_free + beta * market_premium

        # 簡易WACC（株式のみ、有利子負債は無視）
        # 本格的には D/E ratio を使うが、簡略化
        return round(cost_of_equity, 1)
    except Exception:
        return 10.0  # デフォルト


def _dcf_valuation(fcf_latest: float, growth_rate: float, wacc: float,
                   terminal_growth: float = 2.5, years: int = 5,
                   shares_outstanding: int = 1) -> float:
    """DCF法で理論株価を算出"""
    if fcf_latest <= 0 or wacc <= terminal_growth:
        return 0.0

    # Phase 1: 予測期間のFCF現在価値
    pv_fcf = 0.0
    fcf = fcf_latest
    for year in range(1, years + 1):
        fcf *= (1 + growth_rate / 100)
        pv_fcf += fcf / (1 + wacc / 100) ** year

    # Phase 2: 永久成長モデル（ターミナルバリュー）
    terminal_fcf = fcf * (1 + terminal_growth / 100)
    terminal_value = terminal_fcf / ((wacc - terminal_growth) / 100)
    pv_terminal = terminal_value / (1 + wacc / 100) ** years

    # 企業価値
    enterprise_value = pv_fcf + pv_terminal

    # 1株あたり理論株価
    fair_value = enterprise_value / shares_outstanding
    if math.isnan(fair_value) or math.isinf(fair_value):
        return 0.0
    return round(fair_value, 2)


def _get_growth_scenarios(ticker: str, fcf_history: list) -> dict:
    """過去FCF成長率から機械的に3シナリオを算出する（API不使用）"""
    if not fcf_history or len(fcf_history) < 2:
        return {"bull": 15, "base": 8, "bear": 2}

    # FCFの成長率を計算
    growths = []
    for i in range(len(fcf_history) - 1):
        if fcf_history[i+1] != 0:
            g = (fcf_history[i] - fcf_history[i+1]) / abs(fcf_history[i+1]) * 100
            growths.append(round(g, 1))

    avg_growth = sum(growths) / len(growths) if growths else 8
    return {
        "bull": round(min(avg_growth * 1.5, 25), 1),
        "base": round(avg_growth, 1),
        "bear": round(max(avg_growth * 0.3, -5), 1),
    }


def estimate_fair_value(ticker: str) -> dict:
    """
    DCF法で理論株価を算出する。

    Returns:
        dict: fair_value, upside, scenarios, wacc, fcf_history
    """
    print(f"  💰 DCF理論株価を算出中...")

    # 1. FCF履歴の取得
    fcf_history = _get_fcf_history(ticker)
    if not fcf_history:
        print(f"  ⚠️ FCFデータなし — DCFスキップ")
        return {"available": False, "reason": "FCFデータなし"}

    fcf_latest = fcf_history[0]
    if fcf_latest <= 0:
        print(f"  ⚠️ 直近FCFがマイナス — DCFスキップ")
        return {"available": False, "reason": "FCFマイナス"}

    # 2. WACC推定
    wacc = _estimate_wacc(ticker)

    # 3. 発行済株式数
    try:
        stock = yf.Ticker(ticker)
        shares = stock.info.get('sharesOutstanding', 1) or 1
        current_price = stock.info.get('currentPrice') or stock.info.get('previousClose', 0)
    except Exception:
        shares = 1
        current_price = 0

    # 4. 成長シナリオの予測
    scenarios = _get_growth_scenarios(ticker, fcf_history)

    # 5. 各シナリオのDCF算出
    results = {}
    for scenario_name, growth in scenarios.items():
        fv = _dcf_valuation(fcf_latest, growth, wacc, shares_outstanding=shares)
        results[scenario_name] = {
            "growth_rate": growth,
            "fair_value": fv,
        }

    base_fv = results.get("base", {}).get("fair_value", 0) or 0
    if math.isnan(base_fv) or math.isinf(base_fv):
        base_fv = 0
    upside = round((base_fv - current_price) / current_price * 100, 1) if current_price > 0 and base_fv > 0 else 0
    mos = round(max(0, (base_fv - current_price) / base_fv * 100), 1) if base_fv > 0 else 0

    if base_fv > 0:
        print(f"  📊 理論株価: ${base_fv:,.0f} (現在: ${current_price:,.0f}, 上昇余地: {upside:+.1f}%)")
    else:
        print(f"  ⚠️ DCF算出失敗 — デフォルト値を使用")

    return {
        "available": True,
        "fair_value": base_fv,
        "current_price": current_price,
        "upside": upside,
        "margin_of_safety": mos,
        "scenarios": results,
        "wacc": wacc,
        "fcf_latest": fcf_latest,
        "fcf_history": [round(f/1e9, 2) for f in fcf_history],
    }


# テスト実行
if __name__ == "__main__":
    import sys, json
    from dotenv import load_dotenv
    load_dotenv()
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    result = estimate_fair_value(ticker)
    print(json.dumps(result, indent=2, ensure_ascii=False))
