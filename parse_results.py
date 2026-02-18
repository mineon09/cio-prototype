
try:
    with open("backtest_results.log", "r", encoding="utf-16le") as f:
        print(f.read())
except:
    with open("backtest_results.log", "r", encoding="utf-8", errors="ignore") as f:
        print(f.read())
