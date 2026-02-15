"""Debug: Print all financial keys"""
import sys, os, io
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import yfinance as yf
from src.data_fetcher import fetch_stock_data
from datetime import datetime

ticker = '7203.T'
as_of_date = datetime(2024, 6, 1)

stock = yf.Ticker(ticker)
fin = stock.quarterly_financials
if fin is not None and not fin.empty:
    print(f"\n--- Financials Keys ({ticker}) ---")
    print(list(fin.index))

bs = stock.quarterly_balance_sheet
if bs is not None and not bs.empty:
    print(f"\n--- Balance Sheet Keys ({ticker}) ---")
    print(list(bs.index))

data = fetch_stock_data(ticker, as_of_date=as_of_date)
print(f"\nExtracted Metrics: {data['metrics']}")
