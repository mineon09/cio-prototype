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

from src.backtester import run_backtest

def main():
    parser = argparse.ArgumentParser(description="CIO Prototype Backtester")
    parser.add_argument("--ticker", required=True, help="銘柄コード (例: 7203.T)")
    parser.add_argument("--start", required=True, help="開始日 (YYYY-MM-DD)")
    parser.add_argument("--months", type=int, default=12, help="テスト期間(月)")
    parser.add_argument("--strategy", default="long", choices=["long", "short"], help="戦略 (long: 長期, short: 短期)")
    
    args = parser.parse_args()
    
    try:
        result = run_backtest(args.ticker, args.start, args.months, strategy=args.strategy)
        
        print("\n" + "="*50)
        print(f"📊 バックテスト結果: {args.ticker}")
        print("="*50)
        print(f"期間: {result['period']}")
        print(f"最終資産: {result['final_value']:,.0f}円 (初期資産: {result['initial_capital']:,.0f}円)")
        print(f"トータル収益率: {result['total_return_pct']}%  vs  ベンチマーク: {result['benchmark_return_pct']}%")
        print(f"アルファ (市場超過利回り): {result['alpha']}%")
        print("-" * 50)
        print("売買履歴:")
        for t in result['trades']:
            r_str = f"({t['return']:+.1f}%)" if 'return' in t else ""
            print(f"  {t['date'].strftime('%Y-%m-%d')} {t['type']:<12} @ {t['price']:,.0f} (スコア: {t['score']}) {r_str}")
        print("="*50)
        
    except Exception as e:
        print(f"❌ バックテスト実行エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
