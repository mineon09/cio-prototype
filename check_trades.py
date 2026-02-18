
import re

try:
    with open("final_report_v2.md", "r", encoding="utf-8") as f:
        lines = f.readlines()
except:
    with open("final_report_v2.md", "r", encoding="utf-16le") as f:
        lines = f.readlines()

print("Trade Count Check:")
for line in lines:
    if "|" in line and "Strategy" not in line and ":---" not in line:
        parts = [p.strip() for p in line.split("|")]
        # parts[0] is empty, parts[1] is Strategy, parts[2] is Ticker, ... parts[5] is Trades
        if len(parts) >= 6:
            strategy = parts[1]
            ticker = parts[2]
            trades_str = parts[5]
            try:
                trades = int(trades_str)
                status = "OK" if trades >= 10 else "LOW"
                print(f"{strategy} {ticker}: {trades} ({status})")
            except:
                print(f"{strategy} {ticker}: Parse Error ({trades_str})")
