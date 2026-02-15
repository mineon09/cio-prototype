"""Debug Backtest Summary"""
import sys, os, io
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from src.backtester import run_backtest
import pandas as pd

ticker = '7203.T'
print(f"Detailed Debug Backtest for {ticker}")
# Running for 3 months to see the breakdown
results = run_backtest(ticker, '2024-01-01', 3)

if 'history' in results:
    # Normally history only has Portfolio Value, but let's assume we can get more if we modify or just look at logs
    pass

print("\nConclusion: Check logs above for detailed scores.")
