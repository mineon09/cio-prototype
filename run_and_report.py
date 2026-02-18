
import sys
import os
import io

# Modify sys.path to ensure we can import src
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# Redirect stdout to capture output
from contextlib import redirect_stdout

from backtester import run_backtest

TICKERS = ["7203.T", "9984.T"]
STRATEGIES = ["bounce", "breakout"]
START_DATE = "2020-01-01"
DURATION_MONTHS = 60 # 5 years

print("| Strategy | Ticker | Return | Alpha | Trades | Win Rate | Max DD |")
print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

for ticker in TICKERS:
    for strategy in STRATEGIES:
        try:
            # Capture logs to avoid clutter, we only want the result dict
            f = io.StringIO()
            with redirect_stdout(f):
                result = run_backtest(ticker, START_DATE, duration_months=DURATION_MONTHS, strategy=strategy)
            
            if "error" in result:
                print(f"| {strategy} | {ticker} | ERROR: {result['error']} | - | - | - | - |")
            else:
                print(f"| {strategy} | {ticker} | {result['total_return_pct']}% | {result['alpha']}% | {result['trade_count']} | {result['win_rate_pct']}% | {result['max_drawdown_pct']}% |")
                
                # Check for >10 trades requirement
                if result['trade_count'] < 10:
                   print(f"<!-- WARNING: {ticker} {strategy} has only {result['trade_count']} trades -->")

        except Exception as e:
            print(f"| {strategy} | {ticker} | EXCEPTION: {e} | - | - | - | - |")
