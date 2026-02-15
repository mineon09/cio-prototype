"""Fast Debug: Check Financial Data Extraction Logic"""
import sys, os, io
# Fix encoding for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))

import yfinance as yf
import pandas as pd
from datetime import datetime
from src.data_fetcher import fetch_stock_data

TICKER = '7203.T'
AS_OF = datetime(2024, 6, 1)

print(f"🔎 DEBUG: Fetching {TICKER} as of {AS_OF.date()}...")

# 1. Inspect Raw Data Keys via yfinance directly
stock = yf.Ticker(TICKER)
fin = stock.quarterly_financials
bs = stock.quarterly_balance_sheet

print("\n--- [Raw Keys Check] ---")
if fin is not None and not fin.empty:
    print(f"Financials Index (Rows): {list(fin.index)}")
else:
    print("❌ Financials is Empty/None")

if bs is not None and not bs.empty:
    print(f"Balance Sheet Index (Rows): {list(bs.index)}")
else:
    print("❌ Balance Sheet is Empty/None")

# 2. Run fetch_stock_data and check extracted metrics
data = fetch_stock_data(TICKER, as_of_date=AS_OF)
metrics = data.get('metrics', {})

print("\n--- [Extracted Metrics] ---")
for k, v in metrics.items():
    print(f"  {k}: {v}")

print("\n--- [Missing Key Metrics?] ---")
if not metrics.get('roe'): print("❌ ROE is missing")
if not metrics.get('op_margin'): print("❌ Op Margin is missing")
if not metrics.get('equity_ratio'): print("❌ Equity Ratio is missing")
