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
from .data_fetcher import fetch_stock_data
from .analyzers import generate_scorecard

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
                        sector=data.get("sector", "")
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
                    # Short戦略では、日々の判定はcalculate_performance側で行うため、
                    # ここでは「月次で決まったシグナル」と「当日の価格」を渡す。
                    # 利確/損切り判定はcalculate_performance内で日次価格を見て行われる。
                    "signal": current_month_score.get("signal"), 
                    "score": current_month_score.get("total_score"),
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
                macro_data=None 
            )
            
            signal = scorecard.get("signal")
            total_score = scorecard.get("total_score")
            
            # 3. Record
            results.append({
                "date": current_date,
                "price": price,
                "signal": signal,
                "score": total_score,
                "fundamental": scorecard.get("fundamental", {}).get("score"),
                "valuation": scorecard.get("valuation", {}).get("score"),
                "technical": scorecard.get("technical", {}).get("score"),
            })
            
            print(f"  📅 {current_date.strftime('%Y-%m-%d')} | 株価: {price:,.0f} | 総合スコア: {total_score} ({signal})")
            print(f"    [地力: {scorecard.get('fundamental', {}).get('score')}/10, 割安: {scorecard.get('valuation', {}).get('score')}/10, 技術: {scorecard.get('technical', {}).get('score')}/10]")

    # パフォーマンス計算
    perf = calculate_performance(results, strategy=strategy)
    perf['strategy'] = strategy
    perf['ticker'] = ticker
    return perf


def calculate_performance(results: list, strategy: str = "long") -> dict:
    """
    バックテスト結果からパフォーマンス指標を計算する。
    戦略: BUYシグナルが出たら購入し、SELLシグナルまたは期間終了で売却。
    単純化のため、全資産を投入・売却するモデルとする。
    """
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
    
    # コスト設定の読み込み
    try:
        import json
        with open("config.json", encoding="utf-8") as f:
            cfg = json.load(f)
            cost_bps = cfg.get("execution_cost_bps", 0)
            cost_rate = cost_bps / 10000.0
    except:
        cost_rate = 0.0

    for i, row in df.iterrows():
        price = row['price']
        signal = row['signal']
        date = row['date']
        
        # 売買ロジック
        if holdings == 0:
            # 買い条件: BUYシグナル
            if signal == "BUY":
                # 購入コストを引いた上でポジションを持つ
                # cash = price * units * (1 + cost) -> units = cash / (price * (1 + cost))
                holdings = cash / (price * (1 + cost_rate))
                cash = 0
                buy_price = price
                trades.append({"date": date, "type": "BUY", "price": price, "score": row['score']})
            
        elif holdings > 0:
            # 戦略分岐
            sell_signal = False
            reason = ""
            # 現在のリターン（含み益ベース）
            current_return = (price - buy_price) / buy_price * 100
            
            if strategy == "short":
                # 短期戦略: 利確+5%, 損切り-3%
                if current_return >= 5.0:
                    sell_signal = True
                    reason = "Take Profit"
                elif current_return <= -3.0:
                    sell_signal = True
                    reason = "Stop Loss"
                elif signal == "SELL":
                    sell_signal = True
                    reason = "Signal"
            else:
                # 長期戦略: SELLシグナルのみで売却
                if signal == "SELL":
                    sell_signal = True
                    reason = "Signal"

            if sell_signal:
                # 売却代金 = units * price * (1 - cost)
                cash = holdings * price * (1 - cost_rate)
                holdings = 0
                
                # 実際のトレード損益（手数料控除後）を計算するのは難しいが、
                # ここでは単純に (売値 - 買値)/買値 を記録し、最終資産でコスト影響を見る
                trades.append({"date": date, "type": f"SELL ({reason})", "price": price, "score": row['score'], "return": current_return})
        
        # 資産評価額 (手数料は考慮せず時価評価)
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
    
    # BHベンチマーク
    if not df.empty:
        start_price = df.iloc[0]['price']
        end_price = df.iloc[-1]['price']
        bh_return = (end_price - start_price) / start_price * 100
    else:
        bh_return = 0

    return {
        "ticker": "", 
        "period": f"{df.iloc[0]['date'].strftime('%Y-%m')} ~ {df.iloc[-1]['date'].strftime('%Y-%m')}",
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return_pct": round(total_return, 2),
        "benchmark_return_pct": round(bh_return, 2),
        "alpha": round(total_return - bh_return, 2),
        "trades": trades,
        "history": portfolio_values
    }

if __name__ == "__main__":
    pass
