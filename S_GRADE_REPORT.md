# S-Grade Strategy Verification Report (v1.5.0)

## 1. A/B Testing: Code Fix vs Parameter Optimization
Comparing v1.4.2 parameters (Baseline) vs v1.5.0 parameters (Optimized) using the FIXED v1.5.0 code.

| Ticker | Strategy | Case | Return | Alpha | Sharpe | MaxDD | Trades | Win Rate |
|---|---|---|---|---|---|---|---|---|
| 7203.T | bounce | v1.4.2 Params (RSI<35) | **-4.78%** | -89.19% | -0.14 | -8.42% | 12 | 33.3% |
| 7203.T | bounce | v1.5.0 Params (RSI<30) | **3.64%** | -80.77% | 0.2 | -7.31% | 7 | 57.1% |
| 8035.T | breakout | v1.4.2 Params (Vol>1.2) | **8.43%** | -75.99% | 0.36 | -7.87% | 7 | 42.9% |
| 8035.T | breakout | v1.5.0 Params (Vol>1.0) | **-3.77%** | -88.18% | -0.12 | -13.56% | 9 | 22.2% |

## 2. Walk-Forward Analysis (Optimized Params)
Checking for overfitting by splitting data into Training (2020-2021) and Testing (2022-2024).

| Ticker | Period | Return | Alpha | Sharpe | Profit Factor |
|---|---|---|---|---|---|
| 7203.T | Train (2020-2021) | **0.0%** | -22.61% | 0 | inf |
| 7203.T | Test (2022-2024) | **3.64%** | -43.32% | 0.25 | 2.24 |
| 8035.T | Train (2020-2021) | **0.0%** | -22.61% | 0 | inf |
| 8035.T | Test (2022-2024) | **-3.77%** | -50.74% | -0.16 | 1.01 |

## 3. Robustness (Parameter Sensitivity)
Verifying stability by varying key parameters by +/- 10%.

| Ticker | Parameter | Variation | Return | Trades |
|---|---|---|---|---|
| 7203.T | RSI 27 | N/A | **-0.34%** | 4 |
| 7203.T | RSI 30 (Base) | N/A | **3.64%** | 7 |
| 7203.T | RSI 33 | N/A | **0.85%** | 9 |
| 8035.T | Vol 0.9 | N/A | **-10.0%** | 11 |
| 8035.T | Vol 1.0 (Base) | N/A | **-3.77%** | 9 |
| 8035.T | Vol 1.1 | N/A | **-3.77%** | 9 |
