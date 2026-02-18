import subprocess
import os
import shutil
import time

def run_test(ticker, strategy, params, output_name):
    cmd = [
        "python", "backtest.py",
        "--ticker", ticker,
        "--strategy", strategy,
        "--start", "2020-01-01",
        "--months", "60"
    ]
    for k, v in params.items():
        cmd.extend([k, str(v)])
    
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    time.sleep(1)
    if os.path.exists("backtest_result.json"):
        shutil.move("backtest_result.json", output_name)
        print(f"Saved to {output_name}")
    else:
        print(f"Error: backtest_result.json not found for {output_name}")

tests = [
    {
        "ticker": "7203.T", "strategy": "bounce",
        "params": {"--rsi-threshold": "35", "--volume-multiplier": "1.1"},
        "output": "result_7203_baseline.json"
    },
    {
        "ticker": "7203.T", "strategy": "bounce",
        "params": {"--rsi-threshold": "30", "--volume-multiplier": "1.3"},
        "output": "result_7203_optimized.json"
    },
    {
        "ticker": "8035.T", "strategy": "breakout",
        "params": {"--volume-multiplier": "1.2"},
        "output": "result_8035_baseline.json"
    },
    {
        "ticker": "8035.T", "strategy": "breakout",
        "params": {"--volume-multiplier": "1.0"},
        "output": "result_8035_optimized.json"
    }
]

for t in tests:
    try:
        run_test(t["ticker"], t["strategy"], t["params"], t["output"])
    except Exception as e:
        print(f"Failed {t['output']}: {e}")
