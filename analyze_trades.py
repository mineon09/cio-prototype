import pandas as pd
import logging
logging.disable(logging.CRITICAL)
from src.backtester import run_backtest
import warnings
warnings.filterwarnings('ignore')
import json

with open('trades_analysis.txt', 'w') as f:
    for ticker in ['7203.T', '1605.T']:
        res = run_backtest(ticker, '2023-01-01', 12, strategy='breakout')
        f.write(f"\n=== {ticker} Trades ===\n")
        if res and res.get('trades'):
            df = pd.DataFrame(res['trades'])
            f.write(df[['date', 'type', 'price', 'reason', 'return']].to_string())
        else:
            f.write(f"No trades found or error: {res}")
