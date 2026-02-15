import yfinance as yf
import sys
# force utf-8
sys.stdout.reconfigure(encoding='utf-8')

ticker = '7203.T'
stock = yf.Ticker(ticker)
fin = stock.financials

print("--- DATES START ---")
if fin is not None:
    for col in fin.columns:
        print(col)
else:
    print("NONE")
print("--- DATES END ---")
