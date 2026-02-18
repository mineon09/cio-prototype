import sys
import os
import pandas as pd
from datetime import datetime, timedelta

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

try:
    from backtester import run_rolling_backtest
except ImportError:
    # Try local import if running from src
    sys.path.append(os.path.dirname(__file__))
    from src.backtester import run_rolling_backtest

# Key tickers for WFA
WFA_TICKERS = ["7203.T", "9984.T"]
STRATEGIES = ["bounce", "breakout"]

def run_wfa():
    print("=== Walk-Forward Analysis (Rolling Window) ===")
    
    for strategy in STRATEGIES:
        print(f"\n--- Strategy: {strategy.upper()} ---")
        for ticker in WFA_TICKERS:
            print(f"  Testing {ticker} (Rolling Window: 12 months, Step: 3 months)...")
            try:
                # 2020-01-01 start, 24 months total (just a sample run for the report)
                # To be comprehensive, we run longer: 48 months (4 years)
                df = run_rolling_backtest(ticker, "2020-01-01", total_months=48, window_months=12, step_months=3)
                
                if not df.empty:
                    print(df)
                    filename = f"wfa_{ticker}_{strategy}.csv"
                    df.to_csv(filename, index=False)
                    print(f"  Saved to {filename}")
                    
                    # Summary stats
                    avg_ret = df['total_return'].mean()
                    win_windows = len(df[df['total_return'] > 0])
                    total_windows = len(df)
                    print(f"  Avg Window Return: {avg_ret:.2f}% | Win Rate (Windows): {win_windows}/{total_windows} ({win_windows/total_windows*100:.1f}%)")
                else:
                    print("  No results.")
                    
            except Exception as e:
                print(f"  Error: {e}")

if __name__ == "__main__":
    run_wfa()
