import json
import glob
import os

def load_result(filename):
    if not os.path.exists(filename): return None
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

files = {
    "7203_base": "result_7203_baseline.json",
    "7203_opt": "result_7203_optimized.json",
    "8035_base": "result_8035_baseline.json",
    "8035_opt": "result_8035_optimized.json",
    "7203_train": "result_7203_train.json",
    "7203_test": "result_7203_test.json",
    "8035_train": "result_8035_train.json",
    "8035_test": "result_8035_test.json",
    "7203_rsi27": "result_7203_rsi27.json",
    "7203_rsi33": "result_7203_rsi33.json",
    "8035_vol0.9": "result_8035_vol0.9.json",
    "8035_vol1.1": "result_8035_vol1.1.json"
}

results = {k: load_result(v) for k, v in files.items()}

md = "# S-Grade Strategy Verification Report (v1.5.0)\n\n"

# 1. A/B Testing
md += "## 1. A/B Testing: Code Fix vs Parameter Optimization\n"
md += "Comparing v1.4.2 parameters (Baseline) vs v1.5.0 parameters (Optimized) using the FIXED v1.5.0 code.\n\n"
md += "| Ticker | Strategy | Case | Return | Alpha | Sharpe | MaxDD | Trades | Win Rate |\n"
md += "|---|---|---|---|---|---|---|---|---|\n"

def row(key, label):
    r = results.get(key)
    if not r: return f"| {label} | N/A | | | | | | |\n"
    return f"| {r['ticker']} | {r.get('strategy', 'N/A')} | {label} | **{r['total_return_pct']}%** | {r['alpha']}% | {r.get('sharpe_ratio', 'N/A')} | {r['max_drawdown_pct']}% | {r['trade_count']} | {r['win_rate_pct']}% |\n"

md += row("7203_base", "v1.4.2 Params (RSI<35)")
md += row("7203_opt", "v1.5.0 Params (RSI<30)")
md += row("8035_base", "v1.4.2 Params (Vol>1.2)")
md += row("8035_opt", "v1.5.0 Params (Vol>1.0)")
md += "\n"

# 2. Walk-Forward
md += "## 2. Walk-Forward Analysis (Optimized Params)\n"
md += "Checking for overfitting by splitting data into Training (2020-2021) and Testing (2022-2024).\n\n"
md += "| Ticker | Period | Return | Alpha | Sharpe | Profit Factor |\n"
md += "|---|---|---|---|---|---|\n"

def wfa_row(key, period):
    r = results.get(key)
    if not r: return f"| {period} | N/A | | | |\n"
    return f"| {r['ticker']} | {period} | **{r['total_return_pct']}%** | {r['alpha']}% | {r.get('sharpe_ratio', 'N/A')} | {r.get('profit_factor', 'N/A')} |\n"

md += wfa_row("7203_train", "Train (2020-2021)")
md += wfa_row("7203_test", "Test (2022-2024)")
md += wfa_row("8035_train", "Train (2020-2021)")
md += wfa_row("8035_test", "Test (2022-2024)")
md += "\n"

# 3. Robustness
md += "## 3. Robustness (Parameter Sensitivity)\n"
md += "Verifying stability by varying key parameters by +/- 10%.\n\n"
md += "| Ticker | Parameter | Variation | Return | Trades |\n"
md += "|---|---|---|---|---|\n"

def sens_row(key, param):
    r = results.get(key)
    if not r: return f"| {param} | N/A | | |\n"
    return f"| {r['ticker']} | {param} | {r.get('cli_overrides', 'N/A')} | **{r['total_return_pct']}%** | {r['trade_count']} |\n"


# Just use standard format
def sens_simple(key, label):
    r = results.get(key)
    if not r: return f"| {label} | N/A | N/A | N/A | N/A |\n"
    return f"| {r['ticker']} | {label} | N/A | **{r['total_return_pct']}%** | {r['trade_count']} |\n"

md += sens_simple("7203_rsi27", "RSI 27")
md += sens_simple("7203_opt", "RSI 30 (Base)")
md += sens_simple("7203_rsi33", "RSI 33")
md += sens_simple("8035_vol0.9", "Vol 0.9")
md += sens_simple("8035_opt", "Vol 1.0 (Base)")
md += sens_simple("8035_vol1.1", "Vol 1.1")

print(md)
with open("S_GRADE_REPORT.md", "w", encoding="utf-8") as f:
    f.write(md)
