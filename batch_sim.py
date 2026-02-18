import subprocess
import json
import os

bounce_tickers = [
    "7203.T", "9984.T", "6758.T", "8306.T", "8031.T", 
    "7267.T", "6501.T", "4502.T", "2914.T", "8411.T"
]

breakout_tickers = [
    "7011.T", "8035.T", "6857.T", "6920.T", "6098.T",
    "4063.T", "9101.T", "7974.T", "4543.T", "6367.T"
]

def run_sim(ticker, strategy):
    print(f"Running {strategy} for {ticker}...")
    cmd = [
        "python", "src/backtester.py", 
        "--ticker", ticker, 
        "--strategy", strategy, 
        "--days", "365"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
        # Extract Result Summary from stdout
        lines = result.stdout.split('\n')
        summary = {}
        target_found = False
        for line in lines:
            if "Result Summary:" in line:
                target_found = True
                continue
            if target_found and line.strip():
                if ":" in line:
                    key, val = line.strip().split(":", 1)
                    summary[key.strip()] = val.strip()
        return summary
    except Exception as e:
        print(f"Error for {ticker}: {e}")
        return None

def main():
    results = []
    
    print("--- BOUNCE STRATEGY BATCH ---")
    for t in bounce_tickers:
        res = run_sim(t, "bounce")
        if res:
            res['ticker'] = t
            res['strategy'] = 'bounce'
            results.append(res)
            
    print("\n--- BREAKOUT STRATEGY BATCH ---")
    for t in breakout_tickers:
        res = run_sim(t, "breakout")
        if res:
            res['ticker'] = t
            res['strategy'] = 'breakout'
            results.append(res)
            
    # Write to markdown table
    with open("batch_sim_report.md", "w", encoding="utf-8") as f:
        f.write("# Batch Simulation Report (v1.4 Swing Strategies)\n\n")
        
        f.write("## Bounce Strategy\n")
        f.write("| Ticker | Return | Market | Alpha | Trades | Win Rate | Max DD |\n")
        f.write("|--------|--------|--------|-------|--------|----------|--------|\n")
        for r in [r for r in results if r['strategy'] == 'bounce']:
            f.write(f"| {r['ticker']} | {r.get('Total Return', '-')} | {r.get('Market Return', '-')} | {r.get('Alpha', '-')} | {r.get('Trades', '-')} | {r.get('Win Rate', '-')} | {r.get('Max Drawdown', '-')} |\n")
            
        f.write("\n## Breakout Strategy\n")
        f.write("| Ticker | Return | Market | Alpha | Trades | Win Rate | Max DD |\n")
        f.write("|--------|--------|--------|-------|--------|----------|--------|\n")
        for r in [r for r in results if r['strategy'] == 'breakout']:
            f.write(f"| {r['ticker']} | {r.get('Total Return', '-')} | {r.get('Market Return', '-')} | {r.get('Alpha', '-')} | {r.get('Trades', '-')} | {r.get('Win Rate', '-')} | {r.get('Max Drawdown', '-')} |\n")

    print("\nREPORT GENERATED: batch_sim_report.md")

if __name__ == "__main__":
    main()
