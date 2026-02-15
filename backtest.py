"""
backtest.py - バックテスト実行用CLI
=================================
指定した銘柄と期間でバックテストを実行し、レポートを表示します。

Usage:
  python backtest.py --ticker 7203.T --start 2024-01-01 --months 12
"""

import sys
import io
import argparse

# Prevent UnicodeEncodeError on Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from src.backtester import run_backtest, run_monte_carlo, run_rolling_backtest

def main():
    parser = argparse.ArgumentParser(description="CIO Prototype Backtester")
    parser.add_argument("--ticker", required=True, help="銘柄コード (例: 7203.T)")
    parser.add_argument("--start", required=True, help="開始日 (YYYY-MM-DD)")
    parser.add_argument("--months", type=int, default=12, help="テスト期間(月)")
    parser.add_argument("--strategy", default="long", choices=["long", "short"], help="戦略 (long: 長期, short: 短期)")
    
    # New Arguments
    parser.add_argument("--montecarlo", type=int, default=0, help="モンテカルロ・シミュレーション試行回数 (例: 1000)")
    parser.add_argument("--rolling", action="store_true", help="ローリングバックテスト(Walk-Forward)を実行")
    parser.add_argument("--window", type=int, default=12, help="ローリングバックテストのウィンドウサイズ(月)")
    parser.add_argument("--step", type=int, default=3, help="ローリングバックテストのステップサイズ(月)")

    args = parser.parse_args()
    
    try:
        if args.rolling:
            print(f"\n🚀 ローリングバックテスト開始: {args.ticker}")
            print(f"   期間: {args.months}ヶ月, ウィンドウ: {args.window}ヶ月, ステップ: {args.step}ヶ月")
            df = run_rolling_backtest(args.ticker, args.start, total_months=args.months, window_months=args.window, step_months=args.step)
            
            if not df.empty:
                print("\n" + "="*60)
                print(f"📊 ローリングバックテスト結果集計 (N={len(df)})")
                print("="*60)
                print(df[['start_date', 'total_return', 'market_return', 'alpha', 'trades_count']].to_string(index=False))
                print("-" * 60)
                print(f"平均リターン: {df['total_return'].mean():.2f}% (Min: {df['total_return'].min():.2f}%, Max: {df['total_return'].max():.2f}%)")
                print(f"平均市場リターン: {df['market_return'].mean():.2f}%")
                print(f"平均Alpha: {df['alpha'].mean():.2f}%")
                print("="*60)
            else:
                print("❌ 結果が生成されませんでした。")
                
        else:
            # 通常バックテスト
            result = run_backtest(args.ticker, args.start, args.months, strategy=args.strategy)
            
            print("\n" + "="*50)
            print(f"📊 バックテスト結果: {args.ticker}")
            print("="*50)
            print(f"期間: {result['period']}")
            print(f"最終資産: {result['final_value']:,.0f}円 (初期資産: {result['initial_capital']:,.0f}円)")
            print(f"トータル収益率: {result['total_return_pct']}%")
            print(f"  vs 市場ベンチマーク: {result['benchmark_return_pct']}% (Alpha: {result['alpha']}%)")
            print(f"  vs 個別株Buy&Hold:   {result.get('stock_return_pct', 'N/A')}%")
            print("-" * 50)
            print("売買履歴:")
            for t in result['trades']:
                r_str = f"({t['return']:+.1f}%)" if 'return' in t else ""
                print(f"  {t['date'].strftime('%Y-%m-%d')} {t['type']:<12} @ {t['price']:,.0f} (スコア: {t['score']}) {r_str}")
            print("="*50)
            
            # モンテカルロ・シミュレーション
            if args.montecarlo > 0:
                print(f"\n🎲 モンテカルロ・シミュレーション実行中 (Iter: {args.montecarlo})...")
                mc_res = run_monte_carlo(result['trades'], iterations=args.montecarlo, initial_capital=result['initial_capital'])
                if "error" in mc_res:
                    print(f"  ❌ エラー: {mc_res['error']}")
                else:
                    fv = mc_res['final_value']
                    dd = mc_res['max_drawdown']
                    print("-" * 50)
                    print(f"  結果予測 (中央値): {fv['median']:,.0f}円")
                    print(f"  95%信頼区間:       {fv['percentile_5']:,.0f}円 ~ {fv['percentile_95']:,.0f}円")
                    print(f"  最大DD予測 (95%Tile): {dd['percentile_95']:.2f}% (Worst: {dd['worst']:.2f}%)")
                    print("="*50)

    except Exception as e:
        print(f"❌ バックテスト実行エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
