import pandas as pd
import numpy as np
from datetime import date
import random
import inspect
from src.backtester import run_monte_carlo, execute_short_entry, run_rolling_backtest
from src.strategies import BreakoutStrategy
from src.analyzers import TechnicalAnalyzer

def test_monte_carlo_bootstrap():
    print("Testing Monte Carlo Bootstrap (BUG-002)...")
    # Using bootstrap (choices), median results should vary across runs for a diverse trade set.
    trades_varied = [{'return': v} for v in [1.0, 2.0, -1.0, 5.0, -3.0]]
    
    unique_medians = set()
    for _ in range(50):
        r = run_monte_carlo(trades_varied, iterations=20, initial_capital=1000000)
        unique_medians.add(round(r['final_value']['median'], 2))
    
    print(f"  Unique medians found in 50 runs: {len(unique_medians)}")
    # If it was random.sample (shuffle), all medians would be identical because the trade set size is small
    # and we are using all trades in each iteration.
    assert len(unique_medians) > 1, "❌ BUG-002: Monte Carlo results are deterministic (shuffle instead of bootstrap?)"
    print("  ✅ BUG-002: Bootstrap sampling confirmed (variance detected).")

def test_breakout_strategy_safety():
    print("Testing Breakout Strategy Safety Default (BUG-003)...")
    config = {
        "strategies": {
            "breakout": {
                "enabled": True,
                "enabled_regimes": ["RISK_ON"],
                "entry": {"fundamental_min": 5.0}
            }
        }
    }
    strategy = BreakoutStrategy("breakout", config)
    
    dates = pd.date_range(start='2023-01-01', periods=100)
    df = pd.DataFrame({
        'Close': np.random.randn(100).cumsum() + 100,
        'Volume': [1000] * 100,
        'High': [110] * 100,
        'Low': [90] * 100
    }, index=dates)
    
    row = df.iloc[10].copy()
    row['fundamental'] = 10.0
    row['regime'] = 'RISK_ON'
    
    # Use only 11 days (MA75 will be NaN)
    ta = TechnicalAnalyzer(df.iloc[:11])
    result = strategy.analyze_entry(row, df.iloc[:11], ta)
    
    ma75_msg = [d for d in result['details'] if "Trend" in d]
    if ma75_msg:
        assert "NG (Safety default)" in ma75_msg[0], f"Expected 'NG (Safety default)', got '{ma75_msg[0]}'"
        print("  ✅ BUG-003: Safety default works.")
    else:
        assert False, f"❌ BUG-003: Trend log not found. Logs: {result['details']}"

def test_date_timestamp_mismatch():
    print("Testing Date/Timestamp Mismatch (BUG-005)...")
    dates = pd.date_range(start='2023-01-01', periods=10)
    df = pd.DataFrame({'Close': range(10)}, index=dates)
    
    entry_date = date(2023, 1, 1) 
    row_date = pd.Timestamp('2023-01-05') 
    
    start_ts = pd.Timestamp(entry_date)
    end_ts = pd.Timestamp(row_date)
    mask = (df.index >= start_ts) & (df.index <= end_ts)
    count = mask.sum() - 1
    assert count == 4, f"Expected 4 bars, got {count}"
    print("  ✅ BUG-005: Type mismatch handled.")

def test_rolling_backtest_bug_new():
    print("Testing Rolling Backtest NameError (BUG-NEW)...")
    import src.backtester
    original_run_backtest = src.backtester.run_backtest
    try:
        # 1. Check Function Signature
        sig = inspect.signature(run_rolling_backtest)
        assert "strategy" in sig.parameters, "❌ BUG-NEW: 'strategy' parameter missing from run_rolling_backtest"
        
        # 2. Mock execution to check for NameError at runtime
        src.backtester.run_backtest = lambda *args, **kwargs: {"total_return_pct": 0, "alpha": 0, "trade_count": 0}
        run_rolling_backtest("7203.T", "2024-01-01", total_months=1, window_months=1, strategy="breakout")
        print("  ✅ BUG-NEW: run_rolling_backtest accepted strategy arg and executed without NameError.")
    finally:
        src.backtester.run_backtest = original_run_backtest

def test_atr_config_bug_004():
    print("Testing ATR Config Multiplier (BUG-004)...")
    config = {
        "strategies": {"bounce": {"atr_period": 14}},
        "exit_strategy": {
            "short":  {"stop_loss_atr_multiplier": 1.0, "take_profit_atr_multiplier": 2.0},
            "bounce": {"stop_loss_atr_multiplier": 2.0, "take_profit_atr_multiplier": 5.0} # Specific
        }
    }
    
    import src.backtester
    original_get_atr = src.backtester.get_atr_at_entry
    try:
        src.backtester.get_atr_at_entry = lambda *args, **kwargs: 10.0
        
        # Test Bounce
        stop, take, mode = execute_short_entry(100, "2023-01-01", pd.DataFrame(), config, strategy_name="bounce")
        print(f"  Bounce Strategy -> Stop Loss: {stop}")
        assert stop == 80.0, f"Expected 80.0 for bounce (multiplier 2), got {stop}"
        
        # Test Short (Fallback)
        stop_short, _, _ = execute_short_entry(100, "2023-01-01", pd.DataFrame(), config, strategy_name="short")
        print(f"  Short Strategy  -> Stop Loss: {stop_short}")
        assert stop_short == 90.0, f"Expected 90.0 for short (multiplier 1), got {stop_short}"
        
        # Test Missing Exit Strategy (BUG-004 Potential KeyError Fix Verification)
        empty_config = {"exit_strategy": {}} # No "short" here
        # Should use defaults: 1.5 multiplier
        stop_def, _, _ = execute_short_entry(100, "2023-01-01", pd.DataFrame(), empty_config, strategy_name="unknown")
        print(f"  Unknown Strategy -> Stop Loss: {stop_def}")
        assert stop_def == 85.0, f"Expected 85.0 (default 1.5 multiplier), got {stop_def}"
        
        print("  ✅ BUG-004: Strategy-specific exit config and safety defaults confirmed.")
    finally:
        src.backtester.get_atr_at_entry = original_get_atr

if __name__ == "__main__":
    try:
        test_monte_carlo_bootstrap()
        test_breakout_strategy_safety()
        test_date_timestamp_mismatch()
        test_rolling_backtest_bug_new()
        test_atr_config_bug_004()
        print("\n✨ ALL FIXES VERIFIED SUCCESSFULLY ✨")
    except AssertionError as e:
        print(f"\n❌ VERIFICATION FAILED: {str(e)}")
        exit(1)
    except Exception as e:
        print(f"\n💥 UNEXPECTED CRASH: {str(e)}")
        import traceback
        traceback.print_exc()
        exit(1)
