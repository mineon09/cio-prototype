"""
verify_predictions.py - 予測vs実績トラッキング

分析時の予測（signal, entry_price）を 30/90/180 日後の実際の株価と照合して
results.json に書き戻す。

使い方:
  ./venv/bin/python3 verify_predictions.py                    # 全銘柄・全ウィンドウ
  ./venv/bin/python3 verify_predictions.py --ticker 8306.T   # 特定銘柄のみ
  ./venv/bin/python3 verify_predictions.py --window 30       # 30日のみ
  ./venv/bin/python3 verify_predictions.py --dry-run         # 書き込みなし確認
"""

import argparse
import json
import os
import pathlib
import tempfile
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

DATA_DIR = pathlib.Path(__file__).parent / "data"
RESULTS_FILE = DATA_DIR / "results.json"
WINDOWS = [30, 90, 180]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_results() -> dict:
    if not RESULTS_FILE.exists():
        return {}
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


def save_results(data: dict):
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False,
        dir=str(DATA_DIR), suffix=".tmp",
    )
    json.dump(data, tmp, indent=2, ensure_ascii=False)
    tmp.close()
    if RESULTS_FILE.exists():
        os.remove(str(RESULTS_FILE))
    os.rename(tmp.name, str(RESULTS_FILE))


# ---------------------------------------------------------------------------
# Price lookup
# ---------------------------------------------------------------------------

def get_price_on_date(ticker: str, target_date: datetime) -> Optional[float]:
    """target_date に最も近い営業日の終値を返す（±5日ウィンドウ）。"""
    try:
        start = (target_date - timedelta(days=7)).strftime("%Y-%m-%d")
        end   = (target_date + timedelta(days=7)).strftime("%Y-%m-%d")
        hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        if hist.empty:
            return None
        idx = hist.index.tz_localize(None) if hist.index.tzinfo else hist.index
        idx = pd.to_datetime(idx)
        diffs = abs(idx - target_date)
        closest = idx[diffs.argmin()]
        return float(hist.loc[hist.index[diffs.argmin()], "Close"])
    except Exception as e:
        print(f"    ⚠️ {ticker} 価格取得エラー: {e}")
        return None


# ---------------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------------

def _parse_analyzed_at(entry: dict) -> Optional[datetime]:
    """analyzed_at または date フィールドを datetime に変換。"""
    raw = entry.get("analyzed_at") or entry.get("date", "")
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:len(fmt)], fmt)
        except ValueError:
            continue
    return None


def verify_entry(ticker: str, entry: dict, windows: list,
                 dry_run: bool) -> tuple:
    """
    1エントリーの検証を行い (updated_entry, changed) を返す。
    既に verified_{w}d が存在するウィンドウはスキップ。
    """
    analyzed_at = _parse_analyzed_at(entry)
    if analyzed_at is None:
        return entry, False

    signal = entry.get("signal", "WATCH")
    # entry_price がなければ分析時点の現在価格をベースに使う
    entry_price = (entry.get("entry_price")
                   or entry.get("technical_data", {}).get("current_price"))

    changed = False
    for w in windows:
        key = f"verified_{w}d"
        if key in entry:
            continue  # 既検証

        target_date = analyzed_at + timedelta(days=w)
        if target_date > datetime.now():
            continue  # まだ検証時期でない

        print(f"    📅 {w}日後 ({target_date.strftime('%Y-%m-%d')}) を照合中...")
        actual_price = get_price_on_date(ticker, target_date)
        if actual_price is None:
            continue

        price_change_pct = None
        signal_hit = None
        if entry_price and entry_price > 0:
            price_change_pct = round(
                (actual_price - float(entry_price)) / float(entry_price) * 100, 2
            )
            if signal == "BUY":
                signal_hit = price_change_pct > 0
            elif signal == "SELL":
                signal_hit = price_change_pct < 0
            # WATCH は signal_hit = None のまま

        verification = {
            "verified_at":      target_date.isoformat(),
            "actual_price":     actual_price,
            "price_change_pct": price_change_pct,
            "signal_hit":       signal_hit,
        }

        if dry_run:
            hit_str = "✅" if signal_hit else ("❌" if signal_hit is False else "—")
            print(f"    [DRY RUN] {hit_str} {key}: 実績 {actual_price:.0f} "
                  f"({price_change_pct:+.1f}% if price_change_pct is not None else 'N/A')")
        else:
            entry[key] = verification
            changed = True
            hit_str = "✅" if signal_hit else ("❌" if signal_hit is False else "—")
            pct_str = f"{price_change_pct:+.1f}%" if price_change_pct is not None else "N/A"
            print(f"    {hit_str} {key}: 実績 {actual_price:.0f} ({pct_str})")

    return entry, changed


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def compute_accuracy_stats(results: dict) -> dict:
    """
    全銘柄の verified_*d データを集計して精度統計を返す。

    Returns:
        {
          30: {"total": N, "hits": N, "win_rate": 0.0-1.0, "avg_return": float},
          90: ...,
          180: ...,
        }
    """
    stats: dict = {w: {"total": 0, "hits": 0, "returns": []} for w in WINDOWS}

    for ticker, tdata in results.items():
        for entry in tdata.get("history", []):
            for w in WINDOWS:
                v = entry.get(f"verified_{w}d")
                if not v:
                    continue
                stats[w]["total"] += 1
                if v.get("signal_hit") is True:
                    stats[w]["hits"] += 1
                if v.get("price_change_pct") is not None:
                    stats[w]["returns"].append(v["price_change_pct"])

    out = {}
    for w, s in stats.items():
        returns = s["returns"]
        out[w] = {
            "total":      s["total"],
            "hits":       s["hits"],
            "win_rate":   round(s["hits"] / s["total"], 3) if s["total"] > 0 else None,
            "avg_return": round(sum(returns) / len(returns), 2) if returns else None,
        }
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="予測 vs 実績トラッキング — results.json に verified_{30/90/180}d を追記"
    )
    parser.add_argument("--ticker",  help="特定銘柄コードのみ対象（例: 8306.T）")
    parser.add_argument("--window",  type=int, choices=WINDOWS, help="検証ウィンドウ（日）")
    parser.add_argument("--dry-run", action="store_true", help="書き込みなしで確認のみ")
    parser.add_argument("--stats",   action="store_true", help="現在の精度統計を表示して終了")
    args = parser.parse_args()

    results = load_results()
    if not results:
        print("❌ data/results.json が見つかりません")
        return

    if args.stats:
        stats = compute_accuracy_stats(results)
        print("\n📊 予測精度統計")
        print(f"{'期間':>6}  {'件数':>4}  {'勝率':>6}  {'平均リターン':>10}")
        print("-" * 35)
        for w in WINDOWS:
            s = stats[w]
            wr  = f"{s['win_rate']*100:.1f}%" if s["win_rate"] is not None else "—"
            ret = f"{s['avg_return']:+.1f}%"  if s["avg_return"] is not None else "—"
            print(f"{w:>4}日  {s['total']:>4}  {wr:>6}  {ret:>10}")
        return

    windows = [args.window] if args.window else WINDOWS
    tickers = [args.ticker] if args.ticker else list(results.keys())

    total_checked  = 0
    total_verified = 0

    for ticker in tickers:
        if ticker not in results:
            print(f"⚠️ {ticker} は results.json にありません")
            continue

        history = results[ticker].get("history", [])
        print(f"\n🔍 {ticker}: {len(history)} エントリーを確認")

        ticker_changed = False
        for i, entry in enumerate(history):
            updated, changed = verify_entry(ticker, entry, windows, args.dry_run)
            if changed:
                results[ticker]["history"][i] = updated
                ticker_changed = True
                total_verified += 1
            total_checked += 1

        if ticker_changed and not args.dry_run:
            print(f"  💾 {ticker} の検証結果を results.json に保存")

    if not args.dry_run:
        save_results(results)

    suffix = " [DRY RUN]" if args.dry_run else ""
    print(f"\n✅ 完了{suffix}: {total_checked} エントリー確認, {total_verified} 件新規検証")

    # 完了後に統計表示
    if not args.dry_run and total_verified > 0:
        stats = compute_accuracy_stats(results)
        print("\n📊 更新後の予測精度統計")
        print(f"{'期間':>6}  {'件数':>4}  {'勝率':>6}  {'平均リターン':>10}")
        print("-" * 35)
        for w in WINDOWS:
            s = stats[w]
            wr  = f"{s['win_rate']*100:.1f}%" if s["win_rate"] is not None else "—"
            ret = f"{s['avg_return']:+.1f}%"  if s["avg_return"] is not None else "—"
            print(f"{w:>4}日  {s['total']:>4}  {wr:>6}  {ret:>10}")


if __name__ == "__main__":
    main()
