import sys
import os
import pandas as pd
from datetime import datetime, timedelta

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

try:
    from backtester import run_backtest
except ImportError:
    # Try local import if running from src
    sys.path.append(os.path.dirname(__file__))
    from src.backtester import run_backtest

# 検証用ティッカーリスト (代表的な5銘柄に絞る)
TICKERS = [
    "7203.T", # Toyota (Auto/Value)
    "9984.T", # SoftBank (Tech/Volatile)
    "8306.T", # MUFG (Bank/Rate Sensitive)
    "6758.T", # Sony (Consumer/Tech)
    "6920.T"  # Lasertec (Semi/Growth)
]

STRATEGIES = ["bounce", "breakout"]
START_DATE = "2020-01-01"
DAYS = 2200 # 約6年分

def run_mega_sim():
    print(f"Starting Mega Backtest: {len(TICKERS)} tickers x {len(STRATEGIES)} strategies")
    print(f"Period: {START_DATE} ~ (approx {DAYS} days)\n")
    
    csv_filename = "mega_backtest_report_v1.4.3.csv"
    # Write header if new
    if not os.path.exists(csv_filename):
        pd.DataFrame(columns=["ticker", "strategy", "return", "alpha", "trades", "win_rate", "max_drawdown", "profit_factor"]).to_csv(csv_filename, index=False)

    for strategy in STRATEGIES:
        print(f"=== Strategy: {strategy.upper()} ===")
        for ticker in TICKERS:
            print(f"  Testing {ticker}...", end="", flush=True)
            try:
                # Direct function call
                duration_months = int(DAYS / 30)
                result = run_backtest(ticker, START_DATE, duration_months=duration_months, strategy=strategy)
                
                if "error" in result:
                    print(f" [ERROR] {result['error']}")
                    continue
                
                ret = result.get("total_return_pct", 0.0)
                alpha = result.get("alpha", 0.0)
                trades = result.get("trade_count", 0)
                win = result.get("win_rate_pct", 0.0)
                dd = result.get("max_drawdown_pct", 0.0)
                
                print(f" Done. Trades: {trades}, Return: {ret}%")
                
                res_dict = {
                    "ticker": ticker,
                    "strategy": strategy,
                    "return": ret,
                    "alpha": alpha,
                    "trades": trades,
                    "win_rate": win,
                    "max_drawdown": dd,
                    "profit_factor": 0.0 # Placeholder
                }
                
                # Append to CSV immediately
                pd.DataFrame([res_dict]).to_csv(csv_filename, mode='a', header=False, index=False)
                
            except Exception as e:
                print(f" [EXCEPTION] {e}")

    print(f"\nSaved detailed report to {csv_filename}")
    
    # Statistical Summary
    summary = df.groupby("strategy").agg({
        "return": ["mean", "min", "max", "sum"],
        "alpha": ["mean"],
        "trades": ["sum", "mean"],
        "win_rate": "mean",
        "max_drawdown": ["mean", "min"] 
    })
    
    print("\n=== MEGA SIMULATION SUMMARY (v1.4.3) ===")
    print(summary)
    
    with open("mega_sim_summary_v1.4.3.txt", "w", encoding="utf-8") as f:
        f.write(summary.to_string())

if __name__ == "__main__":
    run_mega_sim()
