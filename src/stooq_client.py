"""
stooq_client.py - Stooq 株価 OHLC 取得モジュール
==================================================
Stooq（https://stooq.com）から無料・無制限で日次 OHLC データを取得する。

pandas-datareader に依存せず、requests で直接 CSV エンドポイントを叩く実装。
Python 3.12 以降の distutils 削除問題を回避するための設計。

日本株フォールバック階層における位置付け:
  J-Quants (Free プラン: 403) → **Stooq** → yfinance

ティッカー変換:
  8306.T  → 8306.jp  （東証: .jp サフィックス）
  7203.T  → 7203.jp
  AAPL    → aapl.us  （米国株: .us サフィックス）
  XOM     → xom.us

Stooq CSV エンドポイント:
  https://stooq.com/q/d/l/?s={symbol}&i=d
  → Date,Open,High,Low,Close,Volume の CSV を返す

Note:
  Stooq は OHLC データのみ。ニュース・財務データは提供していない。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta


def to_stooq_symbol(ticker: str) -> str:
    """
    yfinance 形式のティッカーを Stooq シンボルに変換する。

    Examples
    --------
    "8306.T"   → "8306.jp"
    "7203.TYO" → "7203.jp"
    "AAPL"     → "aapl.us"
    "XOM"      → "xom.us"
    """
    t = ticker.strip().upper()

    # 日本株 (.T / .TYO / .OS / .JP)
    m = re.match(r"^(\d+)\.(T|TYO|OS|JP)$", t, re.IGNORECASE)
    if m:
        return f"{m.group(1)}.jp"

    # 米国株（アルファベットのみ 1〜6文字）
    if re.match(r"^[A-Z]{1,6}$", t):
        return f"{t.lower()}.us"

    # その他はそのまま小文字で返す
    return ticker.lower()


def get_price_history(ticker: str, days: int = 20) -> list[dict]:
    """
    Stooq CSV API から直近 N 日分の OHLC を取得する。

    pandas-datareader を使わず requests で直接取得するため、
    Python 3.12 以降の distutils 削除問題に影響されない。

    Parameters
    ----------
    ticker : yfinance 形式のティッカー（例: "8306.T", "AAPL"）
    days   : 取得日数（デフォルト 20 営業日分）

    Returns
    -------
    [{"date": "YYYY-MM-DD", "open": float, "high": float,
      "low": float, "close": float, "volume": float}, ...]
    失敗時は []
    """
    import requests

    symbol = to_stooq_symbol(ticker)
    # 営業日換算で余裕を持たせて暦日 × 1.5 で取得
    end = datetime.now()
    start = end - timedelta(days=int(days * 1.5) + 7)

    url = "https://stooq.com/q/d/l/"
    params = {
        "s": symbol,
        "d1": start.strftime("%Y%m%d"),
        "d2": end.strftime("%Y%m%d"),
        "i": "d",  # 日次
    }

    try:
        resp = requests.get(url, params=params, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; stock_analyze/1.0)"})
        resp.raise_for_status()
        content = resp.text.strip()

        # Stooq がデータなし・エラー時に返すパターン
        if not content or "No data" in content or len(content) < 30:
            print(f"  ⚠️ Stooq: データなし（{ticker} → {symbol}）")
            return []

        # CSV パース: Date,Open,High,Low,Close,Volume
        reader = csv.DictReader(io.StringIO(content))
        result = []
        for row in reader:
            try:
                result.append({
                    "date":   row.get("Date", ""),
                    "open":   float(row.get("Open",   0) or 0),
                    "high":   float(row.get("High",   0) or 0),
                    "low":    float(row.get("Low",    0) or 0),
                    "close":  float(row.get("Close",  0) or 0),
                    "volume": float(row.get("Volume", 0) or 0),
                })
            except (ValueError, TypeError):
                continue

        # 日付昇順に統一して最新 N 件に絞る
        result.sort(key=lambda r: r["date"])
        return result[-days:]

    except Exception as e:
        print(f"  ⚠️ Stooq OHLC 取得失敗（{ticker} → {symbol}）: {e}")
        return []


# ─── セルフテスト ─────────────────────────────────────────
if __name__ == "__main__":
    import sys

    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["8306.T", "7203.T", "AAPL"]
    for t in tickers:
        rows = get_price_history(t, days=5)
        print(f"\n{t} → {to_stooq_symbol(t)}: {len(rows)} 件")
        for r in rows[-3:]:
            print(f"  {r['date']}  終値={r['close']:,.1f}  出来高={r['volume']:,.0f}")
