"""
portfolio_manager.py - 保有銘柄台帳 CLI

使い方:
  ./venv/bin/python3 portfolio_manager.py add 8306.T --qty 100 --price 2450
  ./venv/bin/python3 portfolio_manager.py add AAPL --qty 50 --price 185.5 --currency USD
  ./venv/bin/python3 portfolio_manager.py remove 8306.T
  ./venv/bin/python3 portfolio_manager.py list
  ./venv/bin/python3 portfolio_manager.py show 8306.T
"""

import argparse
import json
import os
import pathlib
import tempfile
from datetime import datetime

import yfinance as yf

PORTFOLIO_FILE = pathlib.Path(__file__).parent / "data" / "portfolio.json"
SCHEMA_KEYS = {"_comment", "_schema"}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_portfolio() -> dict:
    if not PORTFOLIO_FILE.exists():
        return {}
    raw = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if k not in SCHEMA_KEYS}


def save_portfolio(holdings: dict):
    meta = {}
    if PORTFOLIO_FILE.exists():
        raw = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
        meta = {k: v for k, v in raw.items() if k in SCHEMA_KEYS}
    data = {**meta, **holdings}
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False,
        dir=str(PORTFOLIO_FILE.parent), suffix=".tmp",
    )
    json.dump(data, tmp, indent=2, ensure_ascii=False)
    tmp.close()
    if PORTFOLIO_FILE.exists():
        os.remove(str(PORTFOLIO_FILE))
    os.rename(tmp.name, str(PORTFOLIO_FILE))


def get_current_price(ticker: str) -> float | None:
    """yfinance で現在価格を取得。取得失敗時は None を返す。"""
    try:
        info = yf.Ticker(ticker).fast_info
        return float(info.last_price) if info.last_price else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Portfolio calculations
# ---------------------------------------------------------------------------

def calc_pnl(holding: dict, current_price: float | None) -> dict:
    """含損益を計算して返す。"""
    avg = holding.get("avg_price", 0)
    qty = holding.get("qty", 0)
    if not avg or not qty or current_price is None:
        return {}
    cost = avg * qty
    market_value = current_price * qty
    pnl = market_value - cost
    pnl_pct = (current_price - avg) / avg * 100
    return {
        "current_price": current_price,
        "market_value":  round(market_value, 2),
        "cost":          round(cost, 2),
        "pnl":           round(pnl, 2),
        "pnl_pct":       round(pnl_pct, 2),
    }


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_add(args):
    holdings = load_portfolio()
    entry = {
        "qty":           args.qty,
        "avg_price":     args.price,
        "currency":      args.currency,
        "acquired_date": args.date or datetime.now().strftime("%Y-%m-%d"),
        "notes":         args.notes or "",
    }
    action = "更新" if args.ticker in holdings else "追加"
    holdings[args.ticker] = entry
    save_portfolio(holdings)
    print(f"✅ {args.ticker} を{action}しました: {args.qty}株 @ {args.price} {args.currency}")


def cmd_remove(args):
    holdings = load_portfolio()
    if args.ticker not in holdings:
        print(f"⚠️ {args.ticker} は portfolio.json にありません")
        return
    del holdings[args.ticker]
    save_portfolio(holdings)
    print(f"🗑️  {args.ticker} を削除しました")


def cmd_list(args):
    holdings = load_portfolio()
    if not holdings:
        print("ポートフォリオは空です。add コマンドで銘柄を追加してください。")
        return

    print(f"\n{'銘柄':<12} {'株数':>6} {'取得単価':>10} {'現在価格':>10} {'含損益':>12} {'損益率':>8}")
    print("-" * 65)
    total_cost = 0.0
    total_value = 0.0
    for ticker, h in holdings.items():
        cp = get_current_price(ticker)
        pnl = calc_pnl(h, cp)
        cp_str   = f"{cp:,.0f}"    if cp else "—"
        pnl_str  = f"{pnl.get('pnl', 0):+,.0f}" if pnl else "—"
        pct_str  = f"{pnl.get('pnl_pct', 0):+.1f}%" if pnl else "—"
        print(f"{ticker:<12} {h.get('qty', 0):>6,} {h.get('avg_price', 0):>10,.0f} "
              f"{cp_str:>10} {pnl_str:>12} {pct_str:>8}")
        if pnl:
            total_cost  += pnl.get("cost", 0)
            total_value += pnl.get("market_value", 0)

    if total_cost > 0:
        total_pnl     = total_value - total_cost
        total_pnl_pct = total_pnl / total_cost * 100
        print("-" * 65)
        print(f"{'合計':<12} {'':>6} {'':>10} {'':>10} {total_pnl:>+12,.0f} {total_pnl_pct:>+7.1f}%")


def cmd_show(args):
    holdings = load_portfolio()
    if args.ticker not in holdings:
        print(f"⚠️ {args.ticker} は portfolio.json にありません")
        return
    h  = holdings[args.ticker]
    cp = get_current_price(args.ticker)
    pnl = calc_pnl(h, cp)
    print(f"\n{args.ticker}")
    print(f"  保有株数   : {h.get('qty', 0):,}")
    print(f"  取得単価   : {h.get('avg_price', 0):,} {h.get('currency', '')}")
    print(f"  取得日     : {h.get('acquired_date', '—')}")
    if cp:
        print(f"  現在価格   : {cp:,.0f}")
        print(f"  含損益     : {pnl.get('pnl', 0):+,.0f} ({pnl.get('pnl_pct', 0):+.1f}%)")
        print(f"  時価評価額 : {pnl.get('market_value', 0):,.0f}")
    if h.get("notes"):
        print(f"  メモ       : {h['notes']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="保有銘柄台帳 CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="銘柄を追加または更新")
    p_add.add_argument("ticker",   help="銘柄コード (例: 8306.T)")
    p_add.add_argument("--qty",    type=float, required=True, help="保有株数")
    p_add.add_argument("--price",  type=float, required=True, help="平均取得単価")
    p_add.add_argument("--currency", default="JPY", help="通貨 (JPY/USD)")
    p_add.add_argument("--date",   help="取得日 YYYY-MM-DD（省略時: 今日）")
    p_add.add_argument("--notes",  help="メモ")

    p_rm = sub.add_parser("remove", help="銘柄を削除")
    p_rm.add_argument("ticker", help="銘柄コード")

    sub.add_parser("list", help="保有銘柄一覧を表示（含損益付き）")

    p_show = sub.add_parser("show", help="特定銘柄の詳細を表示")
    p_show.add_argument("ticker", help="銘柄コード")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    dispatch = {"add": cmd_add, "remove": cmd_remove, "list": cmd_list, "show": cmd_show}
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
