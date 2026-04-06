XOM（Exxon Mobil）
json{
    "signal": "WATCH",
    "score": 4.5,
    "confidence": 0.65,
    "reasoning": "PER24.0倍はエネルギーセクター平均12〜15倍を約60%上回り割高感が強い。アナリストコンセンサス目標株価$160.17は現在株価$160.69をわずかに下回り実質的アップサイドゼロ。ROE11.1%は業界平均15%を下回るが、営業CF/純利益1.95は強固なキャッシュ創出力を示す。Perfect Order成立でモメンタムは維持も、マクロ環境（関税・原油価格変動）リスクを考慮しエントリーは見送り。配当利回り2.49%はダウンサイド緩衝として機能。",
    "industry_outlook": "再エネ転換・EV普及が長期的収益圧迫リスク。短中期は地政学的緊張と供給制約で原油価格は下値サポートされる見込み。",
    "competitive_position": "統合型メジャーとして上流〜下流の垂直統合強み。Pioneer買収でPermianポジション強化済み。バリュエーションは業界内で割高水準。",
    "entry_price": 152.0,
    "stop_loss": 142.0,
    "take_profit": 175.0,
    "position_size": 0.05,
    "holding_period": "long",
    "time_horizon": "12-18 months",
    "key_catalysts": [
        {
            "event": "2026年Q2決算発表（Pioneer統合効果の確認）",
            "expected_timing": "2026Q3",
            "impact": "high",
            "probability": 0.75
        },
        {
            "event": "原油価格$85/bbl超への回復",
            "expected_timing": "2026H2",
            "impact": "high",
            "probability": 0.40
        },
        {
            "event": "増配・自社株買い拡大発表",
            "expected_timing": "2026Q3",
            "impact": "medium",
            "probability": 0.60
        },
        {
            "event": "低炭素事業（CCS・水素）進捗開示",
            "expected_timing": "2026Q4",
            "impact": "medium",
            "probability": 0.50
        }
    ],
    "key_risks": [
        {
            "risk": "原油価格急落（関税戦争による世界需要減速）",
            "probability": 0.40,
            "impact": "high",
            "mitigation": "エネルギーセクターウェイト削減・原油先物ヘッジ"
        },
        {
            "risk": "環境規制強化によるCapex上昇・資産減損",
            "probability": 0.30,
            "impact": "medium",
            "mitigation": "低炭素投資進捗のモニタリング"
        },
        {
            "risk": "PER割高修正（バリュエーション収縮）",
            "probability": 0.45,
            "impact": "medium",
            "mitigation": "エントリー価格をPER20倍相当$152近辺まで引き下げ待ち"
        },
        {
            "risk": "地政学リスクによる供給過剰・価格崩壊",
            "probability": 0.25,
            "impact": "high",
            "mitigation": "ポートフォリオ内エネルギー比率を5%以下に抑制"
        }
    ],
    "scenario_analysis": {
        "bull_case": {
            "target": 185.0,
            "probability": 0.20,
            "scenario": "原油$90/bbl回復＋Pioneer統合シナジー前倒し実現でEPS$10超、PER18倍適用"
        },
        "base_case": {
            "target": 162.0,
            "probability": 0.55,
            "scenario": "原油$70〜80/bbl推移、コンセンサスEPS$8前後でPER20倍維持。現水準から横ばい圏"
        },
        "bear_case": {
            "target": 130.0,
            "probability": 0.25,
            "scenario": "関税戦争による世界景気後退で原油$60割れ、EPS$5台へ縮小。PER15倍への収縮"
        }
    },
    "esg_factors": {
        "environmental": "CCS・低炭素技術への投資を拡大中だが、化石燃料依存の根本構造は変わらず。Scope3排出削減目標の具体性が課題",
        "social": "Pioneer買収後の雇用・地域コミュニティへの影響が継続的モニタリング項目。安全記録は業界平均を上回る",
        "governance": "取締役会の独立性は高く、株主還元規律は強固。ただし気候関連株主提案への対応姿勢に批判的な機関投資家あり"
    }
}"""
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
