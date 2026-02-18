import sys
import os
import io
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import yfinance as yf

# ロガー設定
logger = logging.getLogger("CIO_Backtester")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    


    logger.setLevel(logging.INFO)

# 文字化け対策 (Windows環境用)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        pass

# モジュールインポートの正規化
try:
    from .data_fetcher import fetch_stock_data
    from .analyzers import generate_scorecard, TechnicalAnalyzer
    from .macro_regime import get_macro_regime
except (ImportError, ValueError):
    try:
        from data_fetcher import fetch_stock_data
        from analyzers import generate_scorecard, TechnicalAnalyzer
        from macro_regime import get_macro_regime
    except ImportError:
        # 最終手段としてsys.path調整
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from data_fetcher import fetch_stock_data
        from analyzers import generate_scorecard, TechnicalAnalyzer
        from macro_regime import get_macro_regime

def calculate_atr(daily_df: pd.DataFrame, period: int = 14) -> pd.Series:
    high  = daily_df["High"]
    low   = daily_df["Low"]
    close = daily_df["Close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False, min_periods=period).mean()

def get_atr_at_entry(daily_df: pd.DataFrame, entry_date, config: dict, strategy: str = "short") -> float | None:
    """エントリー日時点でのATR値を計算して返す。"""
    swing_cfg = config.get("strategies", {}).get(strategy, {})
    period = swing_cfg.get("atr_period", 
             config.get("exit_strategy", {}).get("short", {}).get("atr_period", 14))
    
    MIN_ROWS = period + 5
    past_df  = daily_df[daily_df.index <= pd.Timestamp(entry_date)]

    if len(past_df) < MIN_ROWS:
        return None

    atr_series = calculate_atr(past_df, period)
    valid      = atr_series.dropna()
    atr_val    = float(valid.iloc[-1]) if len(valid) > 0 else None

    return atr_val if atr_val and atr_val > 0 else None

def execute_short_entry(entry_price, entry_date, daily_df, config):
    atr = get_atr_at_entry(daily_df, entry_date, config)
    cfg = config["exit_strategy"]["short"]

    if atr is not None:
        stop_loss   = entry_price - atr * cfg["stop_loss_atr_multiplier"]
        take_profit = entry_price + atr * cfg["take_profit_atr_multiplier"]
        mode = "ATR"
    else:
        stop_loss   = entry_price * (1 + cfg["fixed_stop_loss_pct"]   / 100)
        take_profit = entry_price * (1 + cfg["fixed_take_profit_pct"] / 100)
        mode = "固定"
    return stop_loss, take_profit, mode

try:
    from .strategies import BaseStrategy, LongStrategy, BounceStrategy, BreakoutStrategy
except (ImportError, ValueError):
    from strategies import BaseStrategy, LongStrategy, BounceStrategy, BreakoutStrategy


def get_buy_threshold(regime: str, config: dict) -> float:
    overrides = config.get("signals", {}).get("BUY", {}).get("regime_overrides", {})
    default = config.get("signals", {}).get("BUY", {}).get("min_score", 6.5)
    return overrides.get(regime, {}).get("min_score", default)

def run_backtest(ticker: str, start_date_str: str, duration_months: int = 12, strategy: str = "long", cli_overrides: dict = None):
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid date format"}
    
    logger.info(f"Backtest Start: {ticker} ({strategy}) from {start_date_str}")
    
    try:
        from src.utils import load_config_with_overrides
        config = load_config_with_overrides(ticker)
    except Exception as e:
        logger.error(f"Failed to load config with overrides: {e}")
        config = {}

    # Apply CLI Overrides (Highest Priority)
    if cli_overrides:
        print(f"DEBUG: Applying CLI Overrides: {cli_overrides}")
        if strategy in config["strategies"]:
            # Deep merge into entry/exit if keys match specific known params
            s_cfg = config["strategies"][strategy]
            if "entry" not in s_cfg: s_cfg["entry"] = {}
            
            # Map common CLI args to config structure
            if "rsi_threshold" in cli_overrides: s_cfg["entry"]["rsi_threshold"] = cli_overrides["rsi_threshold"]
            if "volume_multiplier" in cli_overrides: s_cfg["entry"]["volume_multiplier"] = cli_overrides["volume_multiplier"]
            if "price_above_ma" in cli_overrides: s_cfg["entry"]["price_above_ma"] = cli_overrides["price_above_ma"]

    hist = None
    end_date = start_date + relativedelta(months=duration_months)
    if end_date > datetime.now():
        end_date = datetime.now()

    results = []
    
    if strategy in ["short", "bounce", "breakout"]:
        try:
            hist_start = (start_date - timedelta(days=120)).strftime('%Y-%m-%d')
            hist_end = (end_date + timedelta(days=1)).strftime('%Y-%m-%d')
            stock = yf.Ticker(ticker)
            
            # Retry Logic for Initial History Fetch
            import time
            for attempt in range(5):
                try:
                    hist = stock.history(start=hist_start, end=hist_end)
                    if not hist.empty: break
                except Exception as e:
                    if attempt == 4: raise e
                    time.sleep(10 * (attempt + 1))
            
            if hist.index.tz is not None:
                hist.index = hist.index.tz_localize(None)
            
            # Keep full history for TA
            full_hist = hist
            
            # Filter for iteration
            hist = hist[(hist.index >= pd.Timestamp(start_date)) & (hist.index <= pd.Timestamp(end_date))]
        except Exception as e:
            return {"error": str(e)}

        current_month_score = None
        last_scored_month = -1
        regime = "NEUTRAL"

        for date, row in hist.iterrows():
            current_date = date.to_pydatetime()
            price = row['Close']
            
            # Use full_hist for past data
            past_data = full_hist.loc[:date].tail(100)
            ta = TechnicalAnalyzer(past_data)
            perfect_order = ta.check_ma_alignment()

            if current_date.month != last_scored_month:
                # 高速化: 過去400日分のデータを切り出して渡す (yf.download回避)
                past_slice_start = current_date - timedelta(days=400)
                past_slice = full_hist[(full_hist.index >= pd.Timestamp(past_slice_start)) & (full_hist.index <= pd.Timestamp(current_date))]
                
                data = fetch_stock_data(ticker, as_of_date=current_date, price_history=past_slice)
                if data and data.get("technical"):
                    regime = get_macro_regime(current_date, config)
                    tech_data = data.get("technical", {})
                    tech_data["perfect_order"] = perfect_order
                    
                    buy_threshold = get_buy_threshold(regime, config)
                    
                    scorecard = generate_scorecard(
                        data.get("metrics", {}),
                        tech_data,
                        sector=data.get("sector", ""),
                        macro_data={"regime": regime},
                        buy_threshold=buy_threshold
                    )
                    current_month_score = scorecard
                    current_month_score["raw_technical"] = tech_data
                    last_scored_month = current_date.month
                    logger.info(f"{current_date.strftime('%Y-%m-%d')} | Score: {scorecard.get('total_score')} (Regime: {regime})")
                else:
                    current_month_score = None

            if current_month_score:
                results.append({
                    "date": current_date,
                    "price": price,
                    "high": row.get('High', price),
                    "low": row.get('Low', price),
                    "signal": current_month_score.get("signal"), 
                    "score": current_month_score.get("total_score"),
                    "tech_data": current_month_score.get("raw_technical", {}), 
                    "fundamental": current_month_score.get("fundamental", {}).get("score"),
                    "regime": regime
                })

    else: # Long strategy
        try:
            hist_start = (start_date - timedelta(days=400)).strftime('%Y-%m-%d')
            hist_end = end_date.strftime('%Y-%m-%d')
            stock = yf.Ticker(ticker)
            full_hist = stock.history(start=hist_start, end=hist_end)
            if full_hist.index.tz is not None:
                full_hist.index = full_hist.index.tz_localize(None)
        except:
             full_hist = pd.DataFrame()

        for i in range(duration_months + 1):
            current_date = start_date + relativedelta(months=i)
            if current_date > datetime.now(): break
            if current_date.weekday() >= 5:
                current_date -= timedelta(days=current_date.weekday() - 4)
            
            # Slice history for optimization
            past_slice = pd.DataFrame()
            if not full_hist.empty:
                 slice_start = current_date - timedelta(days=400)
                 past_slice = full_hist[(full_hist.index >= pd.Timestamp(slice_start)) & (full_hist.index <= pd.Timestamp(current_date))]

            data = fetch_stock_data(ticker, as_of_date=current_date, price_history=past_slice if not past_slice.empty else None)
            if not data or not data.get("technical"): continue
                
            price = data["technical"]["current_price"]
            regime = get_macro_regime(current_date, config)
            
            # Calculate Perfect Order for Momentum Bonus (Long Strategy)
            ta = TechnicalAnalyzer(past_slice if not past_slice.empty else pd.DataFrame())
            perfect_order = ta.check_ma_alignment()
            
            tech_data = data.get("technical", {})
            tech_data["perfect_order"] = perfect_order
            
            buy_threshold = get_buy_threshold(regime, config)
            
            scorecard = generate_scorecard(
                data.get("metrics", {}),
                tech_data,
                sector=data.get("sector", ""),
                macro_data={"regime": regime},
                buy_threshold=buy_threshold
            )
            
            results.append({
                "date": current_date,
                "price": price,
                "high": price,
                "low": price,
                "signal": scorecard.get("signal"),
                "score": scorecard.get("total_score"),
                "tech_data": scorecard.get("technical", {}), 
                "fundamental": scorecard.get("fundamental", {}).get("score"),
                "regime": regime
            })
            logger.info(f"{current_date.strftime('%Y-%m-%d')} | Score: {scorecard.get('total_score')} (Regime: {regime}, Threshold: {buy_threshold})")

    # Benchmark fetch fix
    default_bm = "^GSPC" 
    if ticker.endswith(".T"):
         default_bm = config.get("benchmark_ticker", "1306.T")
    elif config.get("benchmark_ticker_us"):
         default_bm = config.get("benchmark_ticker_us", "^GSPC")

    try:
        bm_data = yf.Ticker(default_bm).history(start=start_date, end=end_date)
    except:
        bm_data = pd.DataFrame()

    perf = calculate_performance(results, strategy_name=strategy, benchmark_data=bm_data, daily_data=hist, config=config)
    perf.update({'strategy': strategy, 'ticker': ticker, 'benchmark_ticker': default_bm})
    return perf

def calculate_performance(results: list, strategy_name: str = "long", benchmark_data: pd.DataFrame = None, daily_data: pd.DataFrame = None, config: dict = None) -> dict:
    if not results: return {"error": "No results"}
    df = pd.DataFrame(results)
    config = config or {}
    
    strategy_map = {"long": LongStrategy, "bounce": BounceStrategy, "breakout": BreakoutStrategy}
    strategy = strategy_map.get(strategy_name, BaseStrategy)(strategy_name, config)

    initial_capital, cash, holdings = 1000000, 1000000, 0
    trades, portfolio_values = [], []
    cost_rate = config.get("execution_cost_bps", 15) / 10000.0

    buy_price, last_sell_date, last_sell_reason = 0, None, None
    ctx = {}

    for i, row in df.iterrows():
        price, date = row['price'], row['date']
        ta = TechnicalAnalyzer(daily_data.loc[:date].tail(100)) if daily_data is not None else None

        if holdings == 0:
            if strategy.should_buy(row, daily_data, ta):
                cd_days = 0
                if last_sell_date:
                    delta = (date - last_sell_date).days
                    if strategy_name == "long":
                        cd_days = 15 if "損切り" in (last_sell_reason or "") or "SELL" in (last_sell_reason or "") else 7
                    else:
                        risk = strategy.s_cfg.get("risk", {})
                        cd_days = risk.get("cooldown_days_after_loss", 10) if "Stop" in (last_sell_reason or "") else risk.get("cooldown_days_after_profit", 3)
                
                if not last_sell_date or (date - last_sell_date).days >= cd_days:
                    holdings = cash / (price * (1 + cost_rate))
                    cash = 0
                    buy_price = price
                    entry_atr = get_atr_at_entry(daily_data, date, config, strategy_name) if strategy_name != "long" else row.get('atr', 0)
                    ctx = {'buy_price': buy_price, 'entry_date': date, 'entry_atr': entry_atr, 'trailing_high': price, 'low_score_months': 0}
                    trades.append({
                        "date": date, 
                        "type": "BUY", 
                        "price": price, 
                        "score": row['score'], 
                        "regime": row.get('regime', 'NEUTRAL')
                    })
                    logger.info(f"  🚀 BUY: {price:,.0f} at {date.strftime('%Y-%m-%d')}")
        
        else:
            ctx['trailing_high'] = max(ctx['trailing_high'], row.get('high', price))
            should_sell, reason, exit_price = strategy.should_sell(row, daily_data, ta, ctx)
            if not should_sell and i == len(df) - 1: should_sell, reason, exit_price = True, "End of Period", price

            if should_sell:
                cash = holdings * exit_price * (1 - cost_rate)
                holdings, last_sell_date, last_sell_reason = 0, date, reason
                trades[-1].update({"sell_date": date, "sell_price": exit_price, "reason": reason, "return": (exit_price - buy_price) / buy_price * 100})
                logger.info(f"  ⚖️ SELL: {exit_price:,.0f} ({reason}) Return: {trades[-1]['return']:.2f}%")

        portfolio_values.append({"date": date, "value": cash + (holdings * price)})

    p_df = pd.DataFrame(portfolio_values)
    if p_df.empty: return {"error": "No data"}
    
    total_return = (p_df['value'].iloc[-1] - initial_capital) / initial_capital * 100
    valid_trades = [t for t in trades if "sell_price" in t]
    win_rate = (len([t for t in valid_trades if t['return'] > 0]) / len(valid_trades) * 100) if valid_trades else 0
    p_df['dd'] = (p_df['value'] - p_df['value'].cummax()) / p_df['value'].cummax() * 100
    
    market_return = (benchmark_data['Close'].iloc[-1] - benchmark_data['Close'].iloc[0]) / benchmark_data['Close'].iloc[0] * 100 if benchmark_data is not None and not benchmark_data.empty else 0
    stock_return = (df['price'].iloc[-1] - df['price'].iloc[0]) / df['price'].iloc[0] * 100

    # Advanced Metrics
    daily_returns = p_df['value'].pct_change().dropna()
    sharpe_ratio = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() != 0 else 0
    
    gross_profit = sum([t['return'] for t in valid_trades if t['return'] > 0])
    gross_loss = abs(sum([t['return'] for t in valid_trades if t['return'] < 0]))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf')

    return {
        "ticker": "", "period": f"{df.iloc[0]['date'].strftime('%Y-%m')} ~ {df.iloc[-1]['date'].strftime('%Y-%m')}",
        "initial_capital": initial_capital, "final_value": p_df['value'].iloc[-1],
        "total_return_pct": round(total_return, 2), "benchmark_return_pct": round(market_return, 2),
        "market_return_pct": round(market_return, 2), "alpha": round(total_return - market_return, 2),
        "win_rate_pct": round(win_rate, 1), "max_drawdown_pct": round(p_df['dd'].min(), 2),
        "sharpe_ratio": round(sharpe_ratio, 2), "profit_factor": profit_factor,
        "trade_count": len(valid_trades), "trades": trades, "history": portfolio_values, "stock_return_pct": round(stock_return, 2)
    }

def run_monte_carlo(trades: list, iterations: int = 1000, initial_capital: float = 1000000) -> dict:
    import random
    if not trades: return {"error": "No trades"}
    returns = [t['return'] for t in trades if 'return' in t]
    if not returns: return {"error": "No returns"}
    
    final_values, max_drawdowns = [], []
    for _ in range(iterations):
        sampled = random.sample(returns, k=len(returns))
        cap, peak, max_dd = initial_capital, initial_capital, 0.0
        for r in sampled:
            cap *= (1 + r / 100.0)
            peak = max(peak, cap)
            max_dd = max(max_dd, (peak - cap) / peak * 100.0)
        final_values.append(cap)
        max_drawdowns.append(max_dd)
        
    return {
        "iterations": iterations,
        "final_value": {"median": np.median(final_values), "mean": np.mean(final_values), "min": np.min(final_values), "max": np.max(final_values)},
        "max_drawdown": {"median": np.median(max_drawdowns), "mean": np.mean(max_drawdowns), "worst": np.max(max_drawdowns)}
    }

def run_rolling_backtest(ticker: str, start_date_str: str, total_months: int = 24, window_months: int = 12, step_months: int = 1):
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    results = []
    current_start = start_dt
    end_limit = start_dt + relativedelta(months=total_months)
    
    while current_start + relativedelta(months=window_months) <= end_limit:
        try:
            w_start_str = current_start.strftime("%Y-%m-%d")
            logger.info(f"Rolling Window: {w_start_str}")
            bt_result = run_backtest(ticker, w_start_str, duration_months=window_months, strategy="bounce")
            if "error" not in bt_result:
                results.append({
                    "start": w_start_str, "total_return": bt_result["total_return_pct"],
                    "alpha": bt_result["alpha"], "trades": bt_result["trade_count"]
                })
        except Exception as e:
            logger.error(f"Window Error: {e}")
        current_start += relativedelta(months=step_months)
    return pd.DataFrame(results)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, required=True)
    parser.add_argument("--strategy", type=str, default="long")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--start", type=str, default=None, dest="start_date")
    parser.add_argument("--months", type=int, default=None)
    
    # Strategy Param Overrides
    parser.add_argument("--rsi-threshold", type=float, default=None)
    parser.add_argument("--volume-multiplier", type=float, default=None)
    parser.add_argument("--entry-price-ma", type=int, default=None)

    args = parser.parse_args()
    start_date = args.start_date if args.start_date else (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    
    duration_months = args.months if args.months else int(args.days / 30)

    # config override creation
    cli_overrides = {}
    if args.rsi_threshold: cli_overrides["rsi_threshold"] = args.rsi_threshold
    if args.volume_multiplier: cli_overrides["volume_multiplier"] = args.volume_multiplier
    if args.entry_price_ma: cli_overrides["price_above_ma"] = args.entry_price_ma
    
    result = run_backtest(args.ticker, start_date, duration_months=duration_months, strategy=args.strategy, cli_overrides=cli_overrides)
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print(f"\nSummary: {result['ticker']} ({result['strategy']})")
        print(f"  Return: {result['total_return_pct']}% (Alpha: {result['alpha']}%)")
        print(f"  Trades: {result['trade_count']} (Win: {result['win_rate_pct']}%)")
        print(f"  Max DD: {result['max_drawdown_pct']}%")
        print(f"  Sharpe: {result['sharpe_ratio']} | PF: {result['profit_factor']}")
