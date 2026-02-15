import yfinance as yf
import sys

ticker = '7203.T'
stock = yf.Ticker(ticker)

with open('keys.txt', 'w', encoding='utf-8') as f:
    f.write(f"--- Financials Keys ({ticker}) ---\n")
    if stock.quarterly_financials is not None:
        f.write("\n".join(str(k) for k in stock.quarterly_financials.index))
    else:
        f.write("None\n")

    f.write("\n\n--- Balance Sheet Keys ({ticker}) ---\n")
    if stock.quarterly_balance_sheet is not None:
        f.write("\n".join(str(k) for k in stock.quarterly_balance_sheet.index))
    else:
        f.write("None\n")

print("Keys dumped to keys.txt")
