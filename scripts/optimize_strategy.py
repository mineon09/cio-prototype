#!/usr/bin/env python3
"""
scripts/optimize_strategy.py - LLMによる戦略パラメータ最適化 CLI
================================================================
バックテスト結果を LLM に渡し、パラメータ改善案を反復的に生成・適用する。

論文「大規模言語モデルを用いた株式投資戦略の自動生成におけるフィードバック設計」
(docs/ex_pdf/2026_193.pdf) に基づく実装。

使い方:
    # 基本（デフォルト: Claude, P1, 5回反復, dry-run で確認）
    ./venv/bin/python3 scripts/optimize_strategy.py --ticker 8035.T --strategy bounce --dry-run

    # 実際に最適化を実行（設定が変更される）
    ./venv/bin/python3 scripts/optimize_strategy.py \\
        --ticker 8035.T --strategy breakout --start 2023-01-01 --months 12 \\
        --model claude --level P2 --max-iter 30

    # Gemini を使用（Claude API キーなしの場合）
    ./venv/bin/python3 scripts/optimize_strategy.py \\
        --ticker AAPL --strategy bounce --model gemini --level P1

    # モデル比較（論文の A/B テストに相当）
    ./venv/bin/python3 scripts/optimize_strategy.py \\
        --ticker 8035.T --strategy bounce --compare-models --dry-run

    # グループ全銘柄を順番に最適化（30iter × 各銘柄）
    ./venv/bin/python3 scripts/optimize_strategy.py \\
        --group JP_semiconductor --max-iter 30 --level P2

モデル優先順位（論文の実験結果より）:
    Claude Sonnet 4.5: 平均 +14.1% の P&L 改善（最良）
    Gemini:            平均 +7.3%  の P&L 改善（良）
    GPT-4o:            平均 -0.3%  の P&L 改善（保守的）
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_strategy_optimizer import optimize_strategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("optimize_strategy")


# ---------------------------------------------------------------------------
# 銘柄グループ定義（30iter設計）
# ---------------------------------------------------------------------------

TICKER_GROUPS: dict[str, dict] = {
    "JP_semiconductor": {
        "tickers": ["8035.T", "6857.T"],        # 東京エレクトロン, アドバンテスト
        "strategy": "bounce",
        "benchmark": "6344",
        "known_issue": "YEN_STRONG 逆風（輸出企業）",
        "iter_budget": 30,
        "start": "2022-01-01",
        "months": 36,
    },
    "JP_trading": {
        "tickers": ["8053.T", "8058.T"],        # 住友商事, 三菱商事
        "strategy": "breakout",
        "benchmark": "1699",
        "known_issue": "ベースラインが強い — 変更最小限で検証",
        "iter_budget": 15,
        "start": "2022-01-01",
        "months": 36,
    },
    "JP_financial": {
        "tickers": ["8306.T", "8316.T"],        # 三菱UFJ, 三井住友
        "strategy": "bounce",
        "benchmark": "1615",
        "known_issue": "BOJ_HIKE を除外済み",
        "iter_budget": 30,
        "start": "2022-01-01",
        "months": 36,
    },
    "US_semiconductor": {
        "tickers": ["AMAT", "LRCX"],
        "strategy": "bounce",
        "benchmark": "SOXX",
        "known_issue": "USレジーム未対応 → v2.1 で FED/DXY/VIX システムに切り替え済み",
        "iter_budget": 30,
        "start": "2021-01-01",
        "months": 36,
    },
    "US_energy": {
        "tickers": ["XOM", "CVX"],
        "strategy": "breakout",
        "benchmark": "XLE",
        "known_issue": "勝率 0% → USレジーム再設計が前提（v2.1 で対応済み）",
        "iter_budget": 20,
        "start": "2021-01-01",
        "months": 36,
    },
}


def run_single(args) -> dict:
    """単一モデルで最適化を実行する"""
    return optimize_strategy(
        ticker=args.ticker,
        strategy=args.strategy,
        start_date=args.start,
        months=args.months,
        model=args.model,
        level=args.level,
        max_iter=args.max_iter,
        dry_run=args.dry_run,
        save_history=not args.dry_run,
    )


def run_model_comparison(args) -> dict:
    """複数モデルで同じ条件を実行し比較する（論文の A/B テストに相当）"""
    models = ["claude", "gemini", "gpt-4o"]
    comparison_results = {}

    print("\n" + "=" * 60)
    print(f"🔬 モデル比較実験: {args.ticker} ({args.strategy})")
    print(f"   論文の実験設定に準拠: 同一初期設定で複数モデルを比較")
    print("=" * 60)

    for model in models:
        print(f"\n📊 モデル: {model}")
        try:
            result = optimize_strategy(
                ticker=args.ticker,
                strategy=args.strategy,
                start_date=args.start,
                months=args.months,
                model=model,
                level=args.level,
                max_iter=args.max_iter,
                dry_run=True,  # 比較時は常に dry_run
                save_history=False,
            )
            comparison_results[model] = result
            print(f"   P&L改善: {result.get('improvement_pct', 0):+.2f}% | 承認: {result.get('approved', False)}")
        except Exception as e:
            logger.error(f"   {model} 実行失敗: {e}")
            comparison_results[model] = {"error": str(e)}

    # サマリー表示
    print("\n" + "=" * 60)
    print("📈 モデル比較サマリー")
    print("-" * 60)
    print(f"{'モデル':<15} {'P&L改善':>10} {'年率換算':>10} {'承認':>8}")
    print("-" * 60)
    for model, result in comparison_results.items():
        if "error" in result:
            print(f"{model:<15} {'エラー':>10}")
        else:
            imp = result.get("improvement_pct", 0)
            ann_imp = result.get("annualized_improvement_pct", 0)
            appr = "✅" if result.get("approved") else "❌"
            print(f"{model:<15} {imp:>+9.2f}% {ann_imp:>+9.2f}% {appr:>8}")
    print("=" * 60)

    return comparison_results


def print_result_summary(result: dict):
    """最適化結果のサマリーを表示する"""
    print("\n" + "=" * 60)
    print(f"📊 最適化結果サマリー: {result.get('ticker')} ({result.get('strategy')})")
    print(f"   モデル: {result.get('model')} | レベル: {result.get('level')}")
    print(f"   反復数: {result.get('iterations')} | 承認: {'✅ APPROVED' if result.get('approved') else '❌ 未承認'}")
    if result.get("dry_run"):
        print("   [DRY RUN モード — 設定は変更されていません]")
    print("-" * 60)

    init_p = result.get("initial_performance", {})
    final_p = result.get("final_performance", {})
    print(f"{'指標':<20} {'初期':>10} {'最終':>10} {'変化':>10}")
    print("-" * 60)
    metrics = [
        ("Total Return (%)", "total_return_pct"),
        ("Sharpe Ratio",     "sharpe_ratio"),
        ("Win Rate (%)",     "win_rate_pct"),
        ("Max Drawdown (%)", "max_drawdown_pct"),
        ("Trade Count",      "trade_count"),
    ]
    for label, key in metrics:
        iv = init_p.get(key, "N/A")
        fv = final_p.get(key, "N/A")
        if isinstance(iv, (int, float)) and isinstance(fv, (int, float)):
            delta = fv - iv
            sign = "+" if delta >= 0 else ""
            print(f"{label:<20} {iv:>10.2f} {fv:>10.2f} {sign}{delta:>9.2f}")
        else:
            print(f"{label:<20} {str(iv):>10} {str(fv):>10}")
    print("-" * 60)

    if result.get("config_changes"):
        print(f"\n⚙️ 適用されたパラメータ変更 ({len(result['config_changes'])} 回):")
        for change in result["config_changes"]:
            print(f"  反復 {change['iteration']}: {change['updates']}")
            if change.get("analysis"):
                print(f"    分析: {change['analysis'][:100]}...")

    print("=" * 60)


def run_group(args) -> dict:
    """グループ内の全銘柄を順番に最適化する（30iter設計）"""
    group_cfg = TICKER_GROUPS.get(args.group)
    if not group_cfg:
        raise ValueError(f"不明なグループ: {args.group}。有効: {list(TICKER_GROUPS.keys())}")

    tickers = group_cfg["tickers"]
    strategy = args.strategy or group_cfg["strategy"]
    start = args.start or group_cfg["start"]
    months = args.months or group_cfg["months"]
    iter_budget = args.max_iter if args.max_iter != 5 else group_cfg["iter_budget"]

    print("\n" + "=" * 60)
    print(f"🔬 グループ最適化: {args.group}")
    print(f"   銘柄: {tickers}")
    print(f"   戦略: {strategy} | 期間: {start} + {months}M | 最大 {iter_budget} iter")
    print(f"   補足: {group_cfg['known_issue']}")
    print("=" * 60)

    group_results: dict[str, dict] = {}
    for ticker in tickers:
        print(f"\n{'─' * 40}")
        print(f"📈 {ticker} の最適化開始")
        print(f"{'─' * 40}")

        # args を一時的に上書き（ticker/strategy/start/months/max_iter）
        class _FakeArgs:
            pass

        fargs = _FakeArgs()
        fargs.__dict__.update(vars(args))
        fargs.ticker = ticker
        fargs.strategy = strategy
        fargs.start = start
        fargs.months = months
        fargs.max_iter = iter_budget

        try:
            result = run_single(fargs)
            group_results[ticker] = result
        except Exception as e:
            logger.error(f"  {ticker} 最適化失敗: {e}")
            group_results[ticker] = {"error": str(e), "ticker": ticker}

    # グループサマリー表示
    print("\n" + "=" * 60)
    print(f"📊 グループ最適化完了: {args.group}")
    print("-" * 60)
    print(f"{'銘柄':<12} {'Sharpe':>8} {'Return':>10} {'Trades':>8} {'承認':>6}")
    print("-" * 60)
    for ticker, res in group_results.items():
        if "error" in res:
            print(f"{ticker:<12} {'エラー':>8}")
            continue
        fp = res.get("final_performance", {})
        sharpe = fp.get("sharpe_ratio", 0)
        ret = fp.get("total_return_pct", 0)
        trades = fp.get("trade_count", 0)
        appr = "✅" if res.get("approved") else "❌"
        print(f"{ticker:<12} {sharpe:>8.3f} {ret:>+9.2f}% {trades:>8} {appr:>6}")
    print("=" * 60)

    # グループ結果を JSON に保存
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent.parent / "data" / "optimization"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"group_{args.group}_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(group_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 グループ結果を保存: {out_path}")

    return group_results


def main():
    parser = argparse.ArgumentParser(
        description="LLMによる戦略パラメータ最適化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # 必須引数（--group 使用時は --ticker / --strategy は省略可）
    parser.add_argument("--ticker", help="銘柄コード (例: 8035.T, AAPL)")
    parser.add_argument("--strategy", choices=["bounce", "breakout", "long"],
                        help="戦略名")

    # グループ最適化
    parser.add_argument(
        "--group",
        choices=list(TICKER_GROUPS.keys()),
        help="銘柄グループ名（グループ内全銘柄を順番に最適化）",
    )

    # バックテスト設定
    parser.add_argument("--start", default=None, help="バックテスト開始日 (YYYY-MM-DD; --group 使用時はグループ設定を優先)")
    parser.add_argument("--months", type=int, default=None, help="バックテスト期間（月数; --group 使用時はグループ設定を優先）")

    # LLM設定
    parser.add_argument(
        "--model", default="claude",
        choices=["claude", "gemini", "gpt-4o"],
        help="使用するLLMモデル (デフォルト: claude; 論文結果: claude > gemini > gpt-4o)"
    )
    parser.add_argument(
        "--level", default="P1",
        choices=["P1", "P2", "P3"],
        help="フィードバックレベル (P1: 基本指標, P2: +エグジット内訳, P3: +プロット; デフォルト: P1)"
    )

    # 最適化設定
    parser.add_argument("--max-iter", type=int, default=5,
                        help="最大反復回数 (デフォルト: 5; 30iter設計は --group で自動設定)")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLMの提案を表示するが設定は変更しない")

    # 比較実験
    parser.add_argument("--compare-models", action="store_true",
                        help="Claude/Gemini/GPT-4o を一括比較（論文のABテストに相当）")

    # 出力設定
    parser.add_argument("--output", help="結果をJSONファイルに保存 (省略時は自動保存)")
    parser.add_argument("--verbose", "-v", action="store_true", help="デバッグログを表示")

    args = parser.parse_args()

    # --group と --ticker の排他チェック
    if args.group and args.ticker:
        parser.error("--group と --ticker は同時に指定できません")
    if not args.group and not args.ticker:
        parser.error("--ticker または --group のいずれかを指定してください")
    if not args.group and not args.strategy:
        parser.error("--ticker 使用時は --strategy が必要です")

    # --ticker 使用時のデフォルト値設定
    if not args.group:
        if args.start is None:
            args.start = "2023-01-01"
        if args.months is None:
            args.months = 12

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.group:
        print(f"\n🚀 グループ最適化 | {args.group} | モデル: {args.model} | レベル: {args.level}")
        if args.dry_run:
            print("   ⚠️  DRY RUN モード — 設定は変更されません")
        try:
            run_group(args)
        except KeyboardInterrupt:
            print("\n\n⚠️ 中断されました")
            sys.exit(1)
        except Exception as e:
            logger.error(f"エラー: {e}", exc_info=args.verbose)
            sys.exit(1)
        return

    print(f"\n🚀 LLM戦略最適化 | {args.ticker} ({args.strategy})")
    print(f"   モデル: {args.model} | レベル: {args.level} | 最大反復: {args.max_iter}")
    if args.dry_run:
        print("   ⚠️  DRY RUN モード — 設定は変更されません")

    try:
        if args.compare_models:
            result = run_model_comparison(args)
        else:
            result = run_single(args)
            print_result_summary(result)

        # 結果をJSONファイルに保存（--output 指定時）
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n💾 結果を保存: {output_path}")

    except KeyboardInterrupt:
        print("\n\n⚠️ 中断されました")
        sys.exit(1)
    except Exception as e:
        logger.error(f"エラー: {e}", exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
