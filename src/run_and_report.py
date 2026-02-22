
import sys
import os
import io
import json
from contextlib import redirect_stdout

# We are running as part of src package
try:
    from .backtester import run_backtest
except ImportError:
    from src.backtester import run_backtest

TICKERS = ["7203.T", "9984.T"]
STRATEGIES = ["bounce", "breakout"]
START_DATE = "2020-01-01"
DURATION_MONTHS = 60 # 5 years

def main():
    print("| Strategy | Ticker | Return | Alpha | Trades | Win Rate | Max DD |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for ticker in TICKERS:
        for strategy in STRATEGIES:
            try:
                # Capture logs
                f = io.StringIO()
                with redirect_stdout(f):
                    result = run_backtest(ticker, START_DATE, duration_months=DURATION_MONTHS, strategy=strategy)
                
                if "error" in result:
                    print(f"| {strategy} | {ticker} | ERROR: {result['error']} | - | - | - | - |")
                else:
                    trade_count = result.get('trade_count', 0)
                    print(f"| {strategy} | {ticker} | {result.get('total_return_pct', 0)}% | {result.get('alpha', 0)}% | {trade_count} | {result.get('win_rate_pct', 0)}% | {result.get('max_drawdown_pct', 0)}% |")
                    
                    # Check for >10 trades requirement
                    if trade_count < 10:
                        print(f"<!-- WARNING: {ticker} {strategy} has only {trade_count} trades -->")

            except Exception as e:
                print(f"| {strategy} | {ticker} | EXCEPTION: {e} | - | - | - | - |")

if __name__ == "__main__":
    main()
