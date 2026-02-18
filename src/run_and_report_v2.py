
import sys
import os
import io
import json
from contextlib import redirect_stdout

# We are running as part of src package
from .backtester import run_backtest

# Extended Tickers to ensure >10 trades
TICKERS = ["7203.T", "9984.T", "6758.T", "8035.T"]
STRATEGIES = ["bounce", "breakout"]
START_DATE = "2020-01-01"
DURATION_MONTHS = 60 # 5 years

OUTPUT_FILE = "final_report_v2.md"

def run():
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write("| Strategy | Ticker | Return | Alpha | Trades | Win Rate | Max DD |\n")
        out.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        
        print(f"Running backtests for {TICKERS}...")

        for ticker in TICKERS:
            for strategy in STRATEGIES:
                try:
                    # Capture logs
                    f = io.StringIO()
                    with redirect_stdout(f):
                        result = run_backtest(ticker, START_DATE, duration_months=DURATION_MONTHS, strategy=strategy)
                    
                    if "error" in result:
                        line = f"| {strategy} | {ticker} | ERROR: {result['error']} | - | - | - | - |"
                    else:
                        trade_count = result.get('trade_count', 0)
                        line = f"| {strategy} | {ticker} | {result.get('total_return_pct', 0)}% | {result.get('alpha', 0)}% | {trade_count} | {result.get('win_rate_pct', 0)}% | {result.get('max_drawdown_pct', 0)}% |"
                        
                    print(line)
                    out.write(line + "\n")

                except Exception as e:
                    line = f"| {strategy} | {ticker} | EXCEPTION: {e} | - | - | - | - |"
                    print(line)
                    out.write(line + "\n")

if __name__ == "__main__":
    run()
