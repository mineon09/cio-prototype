import yfinance as yf
import pandas as pd
import sys

ticker = '7203.T'
stock = yf.Ticker(ticker)
fin = stock.quarterly_financials

print(f"--- Columns Check ({ticker}) ---")
if fin is not None:
    print(f"Columns: {fin.columns}")
    print(f"Dtype: {fin.columns.dtype}")
    try:
        dates = pd.to_datetime(fin.columns)
        print("pd.to_datetime(columns) SUCCESS")
        print(dates)
    except Exception as e:
        print(f"pd.to_datetime(columns) FAILED: {e}")
else:
    print("Financials is None")
