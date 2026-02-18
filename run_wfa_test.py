import subprocess
import os
import shutil
import time

def run_test(ticker, strategy, params, start_date, months, output_name):
    cmd = [
        "python", "backtest.py",
        "--ticker", ticker,
        "--strategy", strategy,
        "--start", start_date,
        "--months", str(months)
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
    # 7203.T Walk-Forward
    {
        "ticker": "7203.T", "strategy": "bounce",
        "params": {"--rsi-threshold": "30", "--volume-multiplier": "1.3"},
        "start": "2020-01-01", "months": 24, "output": "result_7203_train.json"
    },
    {
        "ticker": "7203.T", "strategy": "bounce",
        "params": {"--rsi-threshold": "30", "--volume-multiplier": "1.3"},
        "start": "2022-01-01", "months": 36, "output": "result_7203_test.json"
    },
    # 8035.T Walk-Forward
    {
        "ticker": "8035.T", "strategy": "breakout",
        "params": {"--volume-multiplier": "1.0"},
        "start": "2020-01-01", "months": 24, "output": "result_8035_train.json"
    },
    {
        "ticker": "8035.T", "strategy": "breakout",
        "params": {"--volume-multiplier": "1.0"},
        "start": "2022-01-01", "months": 36, "output": "result_8035_test.json"
    }
]

for t in tests:
    try:
        run_test(t["ticker"], t["strategy"], t["params"], t["start"], t["months"], t["output"])
    except Exception as e:
        print(f"Failed {t['output']}: {e}")
