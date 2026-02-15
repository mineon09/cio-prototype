"""
backtester.py - 投資戦略バックテストモジュール
==============================================
過去の時点に遡ってデータを取得・分析し、Layer 1-3 のスコアリング基準が
実際の市場で有効であったかを検証する。
"""

import sys
import os
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import yfinance as yf

# src パッケージ内のモジュールを利用
try:
    from .data_fetcher import fetch_stock_data
    from .analyzers import generate_scorecard
except ImportError:
    from data_fetcher import fetch_stock_data
    from analyzers import generate_scorecard

def run_backtest(ticker: str, start_date_str: str, duration_months: int = 12, strategy: str = "long"):
    """
    指定した銘柄のバックテストを実行する。
    
    Args:
        ticker: 銘柄コード (例: 7203.T)
        start_date_str: 開始日 'YYYY-MM-DD'
        duration_months: テスト期間（月数）
        strategy: 'long' (長期/デフォルト) or 'short' (短期トレード)
    """
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD"}
    
    print(f"🚀 バックテスト開始: {ticker} (開始日: {start_date_str}, 期間: {duration_months}ヶ月, 戦略: {strategy})")
    
    # 期間計算
    end_date = start_date + relativedelta(months=duration_months)
    if end_date > datetime.now():
        end_date = datetime.now()

    results = []
    
    # --- 日次ループ (Short戦略) ---
    if strategy == "short":
        # yfinanceで期間中の日次データを一括取得
        print(f"  📊 {ticker} 日次データ一括取得中...")
        try:
            # 前後少し余裕を持たせて取得
            hist_start = (start_date - timedelta(days=10)).strftime('%Y-%m-%d')
            hist_end = (end_date + timedelta(days=1)).strftime('%Y-%m-%d')
            stock = yf.Ticker(ticker)
            hist = stock.history(start=hist_start, end=hist_end)
            
            # indexのタイムゾーン削除
            if hist.index.tz is not None:
                hist.index = hist.index.tz_localize(None)
            
            hist = hist[(hist.index >= pd.Timestamp(start_date)) & (hist.index <= pd.Timestamp(end_date))]
            with open("debug_backtester.log", "a", encoding="utf-8") as f:
                f.write(f"DEBUG: Daily data count: {len(hist)}\n")
                f.write(f"DEBUG: Start: {start_date}, End: {end_date}\n")
                if not hist.empty:
                    f.write(f"DEBUG: First date: {hist.index[0]}, Last date: {hist.index[-1]}\n")
        except Exception as e:
            print(f"  ❌ 日次データ取得エラー: {e}")
            return {"error": str(e)}

        # 月次スコアリング用のキャッシュ
        current_month_score = None
        last_scored_month = -1

        for date, row in hist.iterrows():
            current_date = date.to_pydatetime()
            price = row['Close']
            
            # 月が変わったらスコアリングを実行 (月初の営業日)
            if current_date.month != last_scored_month:
                with open("debug_backtester.log", "a", encoding="utf-8") as f:
                    f.write(f"DEBUG: Scoring for month {current_date.month} at {current_date}\n")
                
                print(f"  🔍 {current_date.strftime('%Y-%m-%d')} | 月次定期分析実行...", end="\r")
                data = fetch_stock_data(ticker, as_of_date=current_date)
                
                if data and data.get("technical") and data["technical"].get("current_price"):
                    scorecard = generate_scorecard(
                        data.get("metrics", {}),
                        data.get("technical", {}),
                        sector=data.get("sector", ""),
                        macro_data=data.get("macro")
                    )
                    current_month_score = scorecard
                    last_scored_month = current_date.month
                    
                    # ログ出力
                    total_score = scorecard.get("total_score")
                    signal = scorecard.get("signal")
                    with open("debug_backtester.log", "a", encoding="utf-8") as f:
                        f.write(f"DEBUG: Score: {total_score}, Signal: {signal}\n")
                    print(f"  📅 {current_date.strftime('%Y-%m-%d')} | 株価: {price:,.0f} | 月次スコア: {total_score} ({signal}){' '*20}")
                else:
                    with open("debug_backtester.log", "a", encoding="utf-8") as f:
                        f.write(f"DEBUG: Data missing for {current_date}\n")
                    print(f"  ⚠️ {current_date.strftime('%Y-%m-%d')}: データ不足のためスキップ{' '*20}")
                    current_month_score = None

            # 日次の記録 (スコアは最新の月次スコアを流用)
            if current_month_score:
                results.append({
                    "date": current_date,
                    "price": price,
                    "high": row.get('High', price),
                    "low": row.get('Low', price),
                    "signal": current_month_score.get("signal"), 
                    "score": current_month_score.get("total_score"),
                    "atr": current_month_score.get("technical", {}).get("atr"),
                    "fundamental": current_month_score.get("fundamental", {}).get("score"),
                    "valuation": current_month_score.get("valuation", {}).get("score"),
                    "technical": current_month_score.get("technical", {}).get("score"),
                })

    # --- 月次ループ (Long戦略 - 従来通り) ---
    else:
        for i in range(duration_months + 1):
            current_date = start_date + relativedelta(months=i)
            
            # 未来の日付になったら終了
            if current_date > datetime.now():
                break

            # 土日の場合は直前の金曜日に調整
            if current_date.weekday() >= 5:
                current_date -= timedelta(days=current_date.weekday() - 4)
                
            data = fetch_stock_data(ticker, as_of_date=current_date)
            
            if not data or not data.get("technical") or not data["technical"].get("current_price"):
                print(f"  ⚠️ {current_date.strftime('%Y-%m-%d')}: スキップ (データ不足)")
                continue
                
            price = data["technical"]["current_price"]
            
            # 2. Score
            scorecard = generate_scorecard(
                data.get("metrics", {}),
                data.get("technical", {}),
                yuho_data=None, 
                sector=data.get("sector", ""),
                dcf_data=None, 
                macro_data=data.get("macro") 
            )
            
            signal = scorecard.get("signal")
            total_score = scorecard.get("total_score")
            
            # 3. Record
            results.append({
                "date": current_date,
                "price": price,
                "high": price,
                "low": price,
                "signal": signal,
                "score": total_score,
                "atr": scorecard.get("technical", {}).get("atr"),
                "fundamental": scorecard.get("fundamental", {}).get("score"),
                "valuation": scorecard.get("valuation", {}).get("score"),
                "technical": scorecard.get("technical", {}).get("score"),
            })
            
            print(f"  📅 {current_date.strftime('%Y-%m-%d')} | 株価: {price:,.0f} | 総合スコア: {total_score} ({signal})")
            print(f"    [地力: {scorecard.get('fundamental', {}).get('score')}/10, 割安: {scorecard.get('valuation', {}).get('score')}/10, 技術: {scorecard.get('technical', {}).get('score')}/10]")

            print(f"    [地力: {scorecard.get('fundamental', {}).get('score')}/10, 割安: {scorecard.get('valuation', {}).get('score')}/10, 技術: {scorecard.get('technical', {}).get('score')}/10]")

    # --- Benchmark Data Fetching ---
    try:
        # Ticker suffix check for region
        bm_ticker = "^GSPC" # Default: S&P 500
        if ticker.endswith(".T"):
            bm_ticker = "^TOPIX" # Japan

        # Config override
        try:
            import json
            with open("config.json", encoding="utf-8") as f:
                cfg = json.load(f)
                if ticker.endswith(".T"):
                    bm_ticker = cfg.get("benchmark_ticker", bm_ticker)
                else:
                    bm_ticker = cfg.get("benchmark_ticker_us", bm_ticker)
        except:
            pass

        print(f"  📊 ベンチマーク取得中: {bm_ticker} ...")
        bm_data = yf.Ticker(bm_ticker).history(start=start_date, end=end_date)
    except Exception as e:
        print(f"  ⚠️ ベンチマーク取得失敗: {e}")
        bm_data = pd.DataFrame()

    # パフォーマンス計算
    perf = calculate_performance(results, strategy=strategy, benchmark_data=bm_data)
    perf['strategy'] = strategy
    perf['ticker'] = ticker
    perf['benchmark_ticker'] = bm_ticker
    return perf



def calculate_performance(results: list, strategy: str = "long", benchmark_data: pd.DataFrame = None) -> dict:
    """
    バックテスト結果からパフォーマンス指標を計算する。
    戦略: BUYシグナルが出たら購入し、SELLシグナルまたは期間終了で売却。
    単純化のため、全資産を投入・売却するモデルとする。
    """
    if not results:
        return {"error": "No results"}

    df = pd.DataFrame(results)
    
    initial_capital = 1000000 # 100万円スタート
    
    # ... (Assets calculation logic remains the same until return calc) ... 
    
    # NOTE: I need to be careful not to delete the internal logic.
    # Limitation of replace_file_content: checking the target content.
    # The function signature needs to change.
    
    if not results:
        return {"error": "No results"}

    df = pd.DataFrame(results)
    
    initial_capital = 1000000 # 100万円スタート
    cash = initial_capital
    holdings = 0
    trades = []
    
    # ポートフォリオ価値の推移
    portfolio_values = []
    
    buy_price = 0
    trailing_high_price = 0
    last_sell_date = None
    last_sell_reason = None
    
    # コスト設定・エグジット設定の読み込み
    try:
        import json
        with open("config.json", encoding="utf-8") as f:
            cfg = json.load(f)
            cost_bps = cfg.get("execution_cost_bps", 0)
            cost_rate = cost_bps / 10000.0
            exit_cfg = cfg.get("exit_strategy", {})
    except:
        cost_rate = 0.0
        exit_cfg = {}

    for i, row in df.iterrows():
        price = row['price']
        signal = row['signal']
        date = row['date']
        atr = row.get('atr', 0)
        
        # 売買ロジック
        if holdings == 0:
            # 買い条件: BUYシグナル
            if signal == "BUY":
                # --- Cooldown Check ---
                is_cooldown = False
                if last_sell_date and last_sell_reason:
                    delta_days = (date - last_sell_date).days
                    
                    # 損切り後のクールダウン
                    if "損切り" in last_sell_reason:
                        cd_days = exit_cfg.get(strategy, {}).get("cooldown_days_after_loss", 5)
                        if delta_days < cd_days:
                            is_cooldown = True
                    
                    # 利確後のクールダウン
                    elif "利確" in last_sell_reason:
                        cd_days = exit_cfg.get(strategy, {}).get("cooldown_days_after_profit", 3)
                        if delta_days < cd_days:
                            is_cooldown = True
                
                if not is_cooldown:
                    holdings = cash / (price * (1 + cost_rate))
                    cash = 0
                    buy_price = price
                    trailing_high_price = price
                    # エントリー時のATRを保持（損切り/利確ライン固定用）
                    entry_atr = atr
                    trades.append({"date": date, "type": "BUY", "price": price, "score": row['score'], "atr": atr})
            
        elif holdings > 0:
            # 戦略分岐
            sell_signal = False
            reason = ""
            current_return = (price - buy_price) / buy_price * 100
            
            # 日中の高値・安値があればそれを使用、なければ終値で判定
            current_low = row.get('low', price)
            current_high = row.get('high', price)
            
            if current_high > trailing_high_price:
                trailing_high_price = current_high
            
            # 戦略別のエグジット判定
            s_cfg = exit_cfg.get(strategy, {})
            mode = s_cfg.get("mode", "signal")
            
            if mode == "atr" and entry_atr and entry_atr > 0:
                # ATRベースの動的判定
                sl_multi = s_cfg.get("stop_loss_atr_multiplier", 1.5)
                tp_multi = s_cfg.get("take_profit_atr_multiplier", 2.5)
                ts_multi = s_cfg.get("trailing_stop_atr_multiplier", 0.0)
                
                stop_loss_price = buy_price - (entry_atr * sl_multi)
                take_profit_price = buy_price + (entry_atr * tp_multi)
                trailing_stop_price = trailing_high_price - (entry_atr * ts_multi) if ts_multi > 0 else 0
                
                if current_low <= stop_loss_price:
                    sell_signal = True
                    reason = "ATR 損切り"
                    price = stop_loss_price # 損切り価格で約定とみなす
                elif take_profit_price > 0 and current_high >= take_profit_price:
                    sell_signal = True
                    reason = "ATR 利確"
                    price = take_profit_price # 利確価格で約定とみなす
                elif ts_multi > 0 and current_low <= trailing_stop_price:
                    sell_signal = True
                    reason = f"Trailing Stop ({ts_multi}ATR)"
                    price = trailing_stop_price
                elif signal == "SELL":
                    sell_signal = True
                    reason = "シグナル"
            else:
                # 従来のシグナルまたは固定%判定 (フォールバック)
                if strategy == "short":
                    # 短期戦略（固定%）
                    fixed_sl = s_cfg.get("fixed_stop_loss_pct", -3.0)
                    fixed_tp = s_cfg.get("fixed_take_profit_pct", 5.0)
                    
                    if current_return >= fixed_tp:
                        sell_signal = True
                        reason = "固定利確"
                    elif current_return <= fixed_sl:
                        sell_signal = True
                        reason = "固定損切り"
                    elif signal == "SELL":
                        sell_signal = True
                        reason = "シグナル"
                else:
                    # 長期戦略: ATRトレーリングストップ or SELLシグナル
                    ts_multi = s_cfg.get("trailing_stop_atr_multiplier", 0.0)
                    
                    if current_high > trailing_high_price:
                        trailing_high_price = current_high
                        
                    trailing_stop_price = trailing_high_price - (entry_atr * ts_multi) if ts_multi > 0 and (entry_atr is not None and entry_atr > 0) else 0

                    if ts_multi > 0 and trailing_stop_price > 0 and current_low <= trailing_stop_price:
                         sell_signal = True
                         reason = f"Trailing Stop ({ts_multi}ATR)"
                         price = trailing_stop_price
                    elif signal == "SELL":
                        sell_signal = True
                        reason = "シグナル"

            if sell_signal:
                cash = holdings * price * (1 - cost_rate)
                holdings = 0
                last_sell_date = date
                last_sell_reason = reason
                trades.append({
                    "date": date, 
                    "type": f"SELL ({reason})", 
                    "price": price, 
                    "score": row['score'], 
                    "return": (price - buy_price) / buy_price * 100
                })
        
        # 資産評価額
        current_value = cash + (holdings * price)
        portfolio_values.append({"date": date, "value": current_value})
    
    # 最終日に強制売却 (評価用)
    if holdings > 0:
        last_row = df.iloc[-1]
        cash = holdings * last_row['price'] * (1 - cost_rate)
        holdings = 0
        trade_return = (last_row['price'] - buy_price) / buy_price * 100
        trades.append({"date": last_row['date'], "type": "SELL (EXIT)", "price": last_row['price'], "score": last_row['score'], "return": trade_return})
        final_value = cash
    else:
        final_value = cash

    total_return = (final_value - initial_capital) / initial_capital * 100
    
    # 1. Market Benchmark (市場指数)
    market_return = 0.0
    if benchmark_data is not None and not benchmark_data.empty:
        try:
            # 期間の調整 (データが存在する範囲で)
            start_val = benchmark_data.iloc[0]['Close']
            end_val = benchmark_data.iloc[-1]['Close']
            if start_val > 0:
                market_return = (end_val - start_val) / start_val * 100
        except Exception as e:
            print(f"⚠️ ベンチマーク計算エラー: {e}")
            market_return = 0.0

    # 2. Stock Benchmark (個別株Buy&Hold)
    stock_return = 0.0
    if not df.empty:
        start_price = df.iloc[0]['price']
        end_price = df.iloc[-1]['price']
        stock_return = (end_price - start_price) / start_price * 100

    # ... (End of calculate_performance)
    return {
        "ticker": "", 
        "period": f"{df.iloc[0]['date'].strftime('%Y-%m')} ~ {df.iloc[-1]['date'].strftime('%Y-%m')}",
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return_pct": round(total_return, 2),
        "benchmark_return_pct": round(market_return, 2), # 互換性のため市場リターンを入れる
        "market_return_pct": round(market_return, 2),    # 新設: 市場ベンチマーク
        "stock_return_pct": round(stock_return, 2),      # 新設: 個別株Buy&Hold
        "alpha": round(total_return - market_return, 2),
        "trades": trades,
        "history": portfolio_values
    }

def run_monte_carlo(trades: list, iterations: int = 1000, initial_capital: float = 1000000) -> dict:
    """
    モンテカルロ・シミュレーションを実行し、トレード順序のランダム性がパフォーマンスに与える影響を検証する。
    
    Args:
        trades: バックテストのトレード履歴リスト
        iterations: 試行回数
        initial_capital: 初期資産
        
    Returns:
        dict: シミュレーション結果の統計情報 (中央値、95%信頼区間など)
    """
    import random
    import numpy as np
    
    if not trades:
        return {"error": "No trades to simulate"}
        
    # リターン率の抽出 (％)
    returns = [t['return'] for t in trades if 'return' in t]
    
    if not returns:
        return {"error": "No returns found in trades"}
        
    final_values = []
    max_drawdowns = []
    
    for _ in range(iterations):
        # リターンのシャッフル (復元抽出)
        # sampled_returns = random.choices(returns, k=len(returns)) # 復元抽出の場合
        sampled_returns = random.sample(returns, k=len(returns)) # 非復元抽出 (順序のみシャッフル)
        
        capital = initial_capital
        peak = capital
        max_dd = 0.0
        
        for r in sampled_returns:
            capital *= (1 + r / 100.0)
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
                
        final_values.append(capital)
        max_drawdowns.append(max_dd)
        
    # 統計量の計算
    result = {
        "iterations": iterations,
        "final_value": {
            "median": np.median(final_values),
            "mean": np.mean(final_values),
            "min": np.min(final_values),
            "max": np.max(final_values),
            "percentile_5": np.percentile(final_values, 5), # ワースト5%
            "percentile_95": np.percentile(final_values, 95) # ベスト5%
        },
        "max_drawdown": {
            "median": np.median(max_drawdowns),
            "mean": np.mean(max_drawdowns),
            "worst": np.max(max_drawdowns), # 最大ドローダウンの最大値 (最悪ケース)
            "percentile_95": np.percentile(max_drawdowns, 95) # 95%信頼区間での最大DD
        }
    }
    return result

def run_rolling_backtest(ticker: str, start_date_str: str, total_months: int = 24, window_months: int = 12, step_months: int = 1) -> pd.DataFrame:
    """
    ローリングバックテスト（スライディングウィンドウ検証）を実行する。
    指定した期間をウィンドウサイズで区切り、少しずつずらしながらバックテストを行うことで、
    特定の期間への過学習を防ぎ、戦略の安定性を検証する。
    
    Args:
        ticker: 銘柄コード
        start_date_str: 全体の開始日
        total_months: 全体の期間
        window_months: 1回のテスト期間（ウィンドウサイズ）
        step_months: ずらす期間（ステップサイズ）
        
    Returns:
        DataFrame: 各ウィンドウのテスト結果
    """
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    results = []
    
    current_start = start_dt
    
    # ウィンドウが全期間に収まる間繰り返す
    # 終了判定: current_start + window_months <= start_dt + total_months
    end_limit = start_dt + relativedelta(months=total_months)
    
    while current_start + relativedelta(months=window_months) <= end_limit:
        try:
            # バックテスト実行
            w_start_str = current_start.strftime("%Y-%m-%d")
            
            # ログを抑制しつつ実行したいが、run_backtestはprintしてしまう。
            # ここではそのまま表示させるか、run_backtestを改修してquietモードをつけるのが良い。
            # 簡易的に、標準出力を一時的にミュートする手もあるが、進行状況が見えないのも困る。
            # そのまま実行し、結果を集約する。
            print(f"\n🌊 Rolling Window: {w_start_str} (Duration: {window_months}m)")
            
            bt_result = run_backtest(ticker, w_start_str, duration_months=window_months, strategy="short") # verifyは通常short戦略で行う
            
            if "error" not in bt_result:
                results.append({
                    "start_date": w_start_str,
                    "end_date": (current_start + relativedelta(months=window_months)).strftime("%Y-%m-%d"),
                    "total_return": bt_result["total_return_pct"],
                    "market_return": bt_result["market_return_pct"],
                    "alpha": bt_result["alpha"],
                    "trades_count": len(bt_result["trades"]),
                    "final_value": bt_result["final_value"]
                })
        except Exception as e:
            print(f"  ❌ Window Error ({current_start}): {e}")
            
        current_start += relativedelta(months=step_months)
        
    return pd.DataFrame(results)

if __name__ == "__main__":
    pass
