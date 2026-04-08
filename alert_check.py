"""
alert_check.py - LINE Notify アラート

保有銘柄を監視して以下のトリガーでLINE Notifyに通知する:
  1. 損切りライン接近: 現在価格が stop_loss の +3% 以内
  2. シグナル変化: 前回分析からシグナルが変化（BUY→WATCH 等）
  3. スコア急落: スコアが前回比 -1.5 以下

使い方:
  ./venv/bin/python3 alert_check.py           # 全銘柄チェック
  ./venv/bin/python3 alert_check.py --dry-run # 通知を送らず確認のみ
  ./venv/bin/python3 alert_check.py --ticker 8306.T

cron 設定例（毎朝8時）:
  0 8 * * * cd ~/projects/stock_analyze && ./venv/bin/python3 alert_check.py >> data/alert.log 2>&1
"""

import argparse
import json
import os
import pathlib
from datetime import datetime
from typing import Optional

import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

DATA_DIR     = pathlib.Path(__file__).parent / "data"
RESULTS_FILE = DATA_DIR / "results.json"
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"

# 損切りライン接近の閾値（stop_loss の何% 上までを「接近」とみなすか）
STOP_LOSS_BUFFER_PCT = 3.0
# スコア急落の閾値
SCORE_DROP_THRESHOLD = 1.5


# ---------------------------------------------------------------------------
# LINE Notify
# ---------------------------------------------------------------------------

def send_line_notify(message: str, dry_run: bool = False) -> bool:
    """LINE Notify でメッセージを送信。dry_run=True の場合は送信せず表示のみ。"""
    if dry_run:
        print(f"[DRY RUN] LINE通知:\n{message}")
        return True

    token = os.environ.get("LINE_NOTIFY_TOKEN", "")
    if not token or token == "your_line_notify_token_here":
        print("⚠️ LINE_NOTIFY_TOKEN が未設定です。.env に設定してください。")
        return False

    try:
        resp = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": message},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        print(f"⚠️ LINE Notify エラー: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"⚠️ LINE Notify 送信失敗: {e}")
        return False


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_results() -> dict:
    if not RESULTS_FILE.exists():
        return {}
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


def load_portfolio() -> dict:
    if not PORTFOLIO_FILE.exists():
        return {}
    raw = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def get_current_price(ticker: str) -> Optional[float]:
    try:
        info = yf.Ticker(ticker).fast_info
        return float(info.last_price) if info.last_price else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Trigger checks
# ---------------------------------------------------------------------------

def check_stop_loss(ticker: str, current_price: float, latest: dict) -> Optional[str]:
    """トリガー1: 損切りライン接近"""
    stop_loss = latest.get("stop_loss")
    if not stop_loss or not current_price:
        return None
    signal = latest.get("signal", "WATCH")
    if signal not in ("BUY", "WATCH"):
        return None
    # stop_loss から BUFFER % 以内に接近しているか
    buffer = stop_loss * (1 + STOP_LOSS_BUFFER_PCT / 100)
    if current_price <= buffer:
        pct = (current_price - stop_loss) / stop_loss * 100
        return (
            f"🚨 【損切りライン接近】{ticker}\n"
            f"現在価格: {current_price:,.0f}\n"
            f"損切りライン: {stop_loss:,.0f} ({pct:+.1f}%)\n"
            f"信号: {signal}"
        )
    return None


def check_signal_change(ticker: str, history: list) -> Optional[str]:
    """トリガー2: シグナル変化（直近2件を比較）"""
    if len(history) < 2:
        return None
    prev   = history[-2]
    latest = history[-1]
    prev_sig   = prev.get("signal", "WATCH")
    latest_sig = latest.get("signal", "WATCH")
    if prev_sig == latest_sig:
        return None
    prev_date   = prev.get("date", "—")[:10]
    latest_date = latest.get("date", "—")[:10]
    return (
        f"🔄 【シグナル変化】{ticker}\n"
        f"{prev_date}: {prev_sig} → {latest_date}: {latest_sig}\n"
        f"スコア: {prev.get('total_score', '—')} → {latest.get('total_score', '—')}"
    )


def check_score_drop(ticker: str, history: list) -> Optional[str]:
    """トリガー3: スコア急落（直近2件を比較）"""
    if len(history) < 2:
        return None
    prev_score   = history[-2].get("total_score")
    latest_score = history[-1].get("total_score")
    if prev_score is None or latest_score is None:
        return None
    drop = prev_score - latest_score
    if drop < SCORE_DROP_THRESHOLD:
        return None
    prev_date   = history[-2].get("date", "—")[:10]
    latest_date = history[-1].get("date", "—")[:10]
    return (
        f"📉 【スコア急落】{ticker}\n"
        f"{prev_date}: {prev_score:.1f} → {latest_date}: {latest_score:.1f} "
        f"(Δ{-drop:+.1f})"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="保有銘柄アラートチェック (LINE Notify)")
    parser.add_argument("--ticker",  help="特定銘柄のみチェック")
    parser.add_argument("--dry-run", action="store_true", help="通知を送らず確認のみ")
    parser.add_argument("--all",     action="store_true",
                        help="portfolio.json に関わらず results.json 全銘柄をチェック")
    args = parser.parse_args()

    results   = load_results()
    portfolio = load_portfolio()

    if not results:
        print("❌ data/results.json が見つかりません")
        return

    # 対象銘柄を決定
    if args.ticker:
        tickers = [args.ticker]
    elif args.all or not portfolio:
        tickers = list(results.keys())
        if not args.all and not portfolio:
            print("ℹ️ portfolio.json が空なので全銘柄をチェックします（--all フラグ等価）")
    else:
        # portfolio.json に登録されている銘柄のみ対象
        tickers = list(portfolio.keys())

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n🔔 アラートチェック開始 ({now_str})")
    print(f"   対象: {len(tickers)} 銘柄\n")

    alerts_sent = 0

    for ticker in tickers:
        if ticker not in results:
            print(f"  ⚠️ {ticker} は results.json にありません")
            continue

        history = results[ticker].get("history", [])
        if not history:
            continue

        latest = history[-1]
        print(f"  🔍 {ticker}: signal={latest.get('signal','—')} "
              f"score={latest.get('total_score','—')} "
              f"date={latest.get('date','—')[:10]}")

        # 現在価格取得（損切りチェックに必要）
        current_price = get_current_price(ticker)

        # 各トリガーチェック
        triggers = [
            check_stop_loss(ticker, current_price, latest),
            check_signal_change(ticker, history),
            check_score_drop(ticker, history),
        ]

        for msg in triggers:
            if msg:
                print(f"\n  ⚡ アラート発火:\n{msg}\n")
                if send_line_notify(msg, dry_run=args.dry_run):
                    alerts_sent += 1
                else:
                    print("  ❌ 通知送信失敗")

    suffix = " [DRY RUN]" if args.dry_run else ""
    print(f"\n✅ 完了{suffix}: {alerts_sent} 件のアラートを送信")


if __name__ == "__main__":
    main()
