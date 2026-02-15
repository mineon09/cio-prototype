import sys
import io

from src.backtester import run_backtest

with open("verification_v12_atr.txt", "w", encoding="utf-8") as f:
    f.write("Verifying v1.2 ATR-based Dynamic Exit with XOM...\n")
    try:
        # XOM should trigger ATR-based TP/SL more frequently
        res = run_backtest("XOM", "2024-01-01", 6, strategy="short")
        
        f.write("\n--- RESULTS ---\n")
        f.write(f"Total Return: {res.get('total_return_pct', 'N/A')}%\n")
        f.write("Trades:\n")
        if 'trades' in res:
            for t in res['trades']:
                ret_str = f"(Return: {t.get('return', 0):.1f}%)" if 'return' in t else ""
                atr_str = f"[Entry ATR: {t.get('atr', 'N/A')}]" if t['type'].startswith('BUY') else ""
                f.write(f"  {t['date'].strftime('%Y-%m-%d')} {t['type']} @ {t['price']:.2f} {ret_str} {atr_str}\n")
        else:
            f.write("No trades found.\n")
        
        # Add raw history for a few days around the trade
        f.write("\n--- RAW HISTORY SIPPET ---\n")
        import pandas as pd
        # Inspecting the period around the first sell
        f.write(str(res.get('history', [])[:10]))
            
    except Exception as e:
        f.write(f"Error: {e}\n")
        import traceback
        f.write(traceback.format_exc())
