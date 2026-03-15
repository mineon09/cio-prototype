"""
analyst_ratings.py - アナリスト評価・目標株価取得モジュール
==========================================================
yfinance からアナリストのレーティング、目標株価、収益予測などを取得する。
"""

import os
import json
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict
import yfinance as yf


def fetch_analyst_ratings(ticker: str) -> Dict:
    """
    アナリストのレーティング履歴を取得
    
    Parameters
    ----------
    ticker : 銘柄コード
    
    Returns
    -------
    レーティングデータ
    """
    try:
        stock = yf.Ticker(ticker)
        recommendations = stock.recommendations
        
        if recommendations is None or recommendations.empty:
            # 新規推奨（recommendations_maybe）
            recommendations = stock.recommendations_maybe
        
        if recommendations is None or recommendations.empty:
            return {"available": False}
        
        # 直近 10 件を取得
        recent = recommendations.head(10).reset_index()
        
        ratings_list = []
        for _, row in recent.iterrows():
            ratings_list.append({
                "date": str(row.get("Date", row.get("period", "")))[:10],
                "firm": row.get("Firm", row.get("firm", "")),
                "to_grade": row.get("To Grade", row.get("toGrade", "")),
                "from_grade": row.get("From Grade", row.get("fromGrade", "")),
                "action": row.get("Action", row.get("action", "")),
            })
        
        return {
            "available": True,
            "ratings": ratings_list,
            "count": len(ratings_list),
        }
    except Exception as e:
        print(f"  ⚠️ アナリストレーティング取得エラー：{e}")
        return {"available": False, "error": str(e)}


def fetch_price_target(ticker: str) -> Dict:
    """
    アナリストの目標株価（コンセンサス）を取得
    
    Parameters
    ----------
    ticker : 銘柄コード
    
    Returns
    -------
    目標株価データ
    """
    try:
        stock = yf.Ticker(ticker)
        
        # 目標株価統計
        target_mean = stock.info.get("targetMeanPrice")
        target_high = stock.info.get("targetHighPrice")
        target_low = stock.info.get("targetLowPrice")
        target_median = stock.info.get("targetMedianPrice")
        current_price = stock.info.get("currentPrice") or stock.info.get("previousClose")
        
        if not any([target_mean, target_high, target_low, target_median]):
            return {"available": False}
        
        # アップサイド/ダウンサイド計算
        upside = None
        if target_mean and current_price:
            upside = ((target_mean - current_price) / current_price) * 100
        
        return {
            "available": True,
            "current_price": current_price,
            "target_mean": round(target_mean, 2) if target_mean else None,
            "target_high": round(target_high, 2) if target_high else None,
            "target_low": round(target_low, 2) if target_low else None,
            "target_median": round(target_median, 2) if target_median else None,
            "upside_pct": round(upside, 2) if upside else None,
            "currency": stock.info.get("currency", "USD"),
        }
    except Exception as e:
        print(f"  ⚠️ 目標株価取得エラー：{e}")
        return {"available": False, "error": str(e)}


def fetch_earnings_estimates(ticker: str) -> Dict:
    """
    収益予測（コンセンサス）を取得
    
    Parameters
    ----------
    ticker : 銘柄コード
    
    Returns
    -------
    収益予測データ
    """
    try:
        stock = yf.Ticker(ticker)
        earnings = stock.earnings_estimates
        
        if earnings is None or earnings.empty:
            return {"available": False}
        
        # 四半期予測
        quarterly = {}
        annual = {}
        
        # カラム名の正規化
        earnings_df = earnings.reset_index()
        
        for _, row in earnings_df.iterrows():
            period = row.get("period", "")
            if period:
                estimate_data = {
                    "period": period,
                    "avg_estimate": row.get("avgEstimate", row.get("Average Estimate")),
                    "low_estimate": row.get("lowEstimate", row.get("Low Estimate")),
                    "high_estimate": row.get("highEstimate", row.get("High Estimate")),
                    "year_ago_eps": row.get("yearAgoEps", row.get("Year Ago EPS")),
                    "num_analysts": row.get("numAnalysts", row.get("# Analysts")),
                    "growth": row.get("growth", row.get("Growth")),
                }
                
                # 四半期か年次かを判定
                if isinstance(period, str) and len(period) == 7:  # "2026Q1" など
                    quarterly[period] = estimate_data
                else:
                    annual[period] = estimate_data
        
        return {
            "available": True,
            "quarterly": list(quarterly.values())[:4],  # 最大 4 四半期
            "annual": list(annual.values())[:3],  # 最大 3 年
        }
    except Exception as e:
        print(f"  ⚠️ 収益予測取得エラー：{e}")
        return {"available": False, "error": str(e)}


def fetch_revenue_estimates(ticker: str) -> Dict:
    """
    売上予測（コンセンサス）を取得
    
    Parameters
    ----------
    ticker : 銘柄コード
    
    Returns
    -------
    売上予測データ
    """
    try:
        stock = yf.Ticker(ticker)
        revenue = stock.revenue_estimates
        
        if revenue is None or revenue.empty:
            return {"available": False}
        
        revenue_df = revenue.reset_index()
        
        estimates = []
        for _, row in revenue_df.iterrows():
            estimates.append({
                "period": row.get("period", row.get("Period", "")),
                "avg_estimate": row.get("avgEstimate", row.get("Average Estimate")),
                "low_estimate": row.get("lowEstimate", row.get("Low Estimate")),
                "high_estimate": row.get("highEstimate", row.get("High Estimate")),
                "year_ago_sales": row.get("yearAgoSales", row.get("Year Ago Sales")),
                "num_analysts": row.get("numAnalysts", row.get("# Analysts")),
                "growth": row.get("growth", row.get("Growth")),
            })
        
        return {
            "available": True,
            "estimates": estimates[:4],  # 最大 4 期間
        }
    except Exception as e:
        print(f"  ⚠️ 売上予測取得エラー：{e}")
        return {"available": False, "error": str(e)}


def calculate_consensus_signal(ratings_data: Dict, target_data: Dict) -> Dict:
    """
    アナリスト評価からコンセンサスシグナルを計算
    
    Parameters
    ----------
    ratings_data  : レーティングデータ
    target_data   : 目標株価データ
    
    Returns
    -------
    コンセンサスシグナル
    """
    if not ratings_data.get("available") and not target_data.get("available"):
        return {
            "signal": "NEUTRAL",
            "score": 5,
            "summary": "アナリストデータが利用できません"
        }
    
    # レーティング分析
    rating_score = 5
    if ratings_data.get("available"):
        ratings = ratings_data.get("ratings", [])
        buy_count = 0
        hold_count = 0
        sell_count = 0
        
        for r in ratings:
            grade = (r.get("to_grade", "") or "").upper()
            if "BUY" in grade or "OVERWEIGHT" in grade or "OUTPERFORM" in grade or "STRONG BUY" in grade:
                buy_count += 1
            elif "SELL" in grade or "UNDERWEIGHT" in grade or "UNDERPERFORM" in grade:
                sell_count += 1
            else:
                hold_count += 1
        
        total = buy_count + hold_count + sell_count
        if total > 0:
            rating_score = 5 + (buy_count - sell_count) / total * 5
            rating_score = max(1, min(10, rating_score))
    
    # 目標株価分析
    target_score = 5
    if target_data.get("available"):
        upside = target_data.get("upside_pct", 0)
        if upside:
            if upside > 20:
                target_score = 9
            elif upside > 10:
                target_score = 7
            elif upside > 5:
                target_score = 6
            elif upside < -20:
                target_score = 1
            elif upside < -10:
                target_score = 3
            elif upside < -5:
                target_score = 4
    
    # 総合スコア
    final_score = (rating_score + target_score) / 2
    
    if final_score >= 7:
        signal = "BUY"
    elif final_score >= 5:
        signal = "HOLD"
    else:
        signal = "SELL"
    
    return {
        "signal": signal,
        "score": round(final_score, 1),
        "rating_score": round(rating_score, 1),
        "target_score": round(target_score, 1),
        "summary": f"アナリストコンセンサス：{signal}（スコア：{final_score:.1f}/10）"
    }


def fetch_all_analyst_data(ticker: str) -> Dict:
    """
    全てのアナリストデータを収集
    
    Parameters
    ----------
    ticker : 銘柄コード
    
    Returns
    -------
    統合アナリストデータ
    """
    print(f"  📊 {ticker} のアナリストデータ収集中...")
    
    ratings = fetch_analyst_ratings(ticker)
    target = fetch_price_target(ticker)
    earnings = fetch_earnings_estimates(ticker)
    revenue = fetch_revenue_estimates(ticker)
    
    consensus = calculate_consensus_signal(ratings, target)
    
    print(f"    ✓ レーティング：{ratings.get('count', 0)} 件")
    print(f"    ✓ 目標株価：{'あり' if target.get('available') else 'なし'}")
    print(f"    ✓ 収益予測：{'あり' if earnings.get('available') else 'なし'}")
    print(f"    ✓ コンセンサス：{consensus['signal']}")
    
    return {
        "available": True,
        "ratings": ratings,
        "price_target": target,
        "earnings_estimates": earnings,
        "revenue_estimates": revenue,
        "consensus": consensus,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def format_analyst_for_prompt(analyst_data: Dict) -> str:
    """
    アナリストデータをプロンプト用テキストに整形
    
    Parameters
    ----------
    analyst_data : fetch_all_analyst_data の戻り値
    
    Returns
    -------
    整形済みテキスト
    """
    if not analyst_data or not analyst_data.get("available"):
        return "（アナリストデータ未取得）"
    
    lines = []
    
    # コンセンサス
    consensus = analyst_data.get("consensus", {})
    signal_emoji = {
        "BUY": "🟢",
        "HOLD": "🟡",
        "SELL": "🔴"
    }.get(consensus.get("signal", "HOLD"), "🟡")
    
    lines.append(f"【アナリストコンセンサス】 {signal_emoji} {consensus.get('signal', 'HOLD')}")
    lines.append(f"  総合スコア：{consensus.get('score', 5):.1f}/10")
    
    # 目標株価
    target = analyst_data.get("price_target", {})
    if target.get("available"):
        current = target.get("current_price", 0)
        mean_target = target.get("target_mean")
        upside = target.get("upside_pct")
        
        lines.append(f"\n【目標株価（コンセンサス）】")
        lines.append(f"  現在株価：${current:.2f}")
        if mean_target:
            lines.append(f"  平均目標：${mean_target:.2f} ({'+' if upside > 0 else ''}{upside:.1f}%)")
        if target.get("target_high"):
            lines.append(f"  最高目標：${target['target_high']:.2f}")
        if target.get("target_low"):
            lines.append(f"  最低目標：${target['target_low']:.2f}")
    
    # レーティング履歴
    ratings = analyst_data.get("ratings", {})
    if ratings.get("available"):
        recent_ratings = ratings.get("ratings", [])[:5]
        if recent_ratings:
            lines.append(f"\n【直近レーティング変更】")
            for r in recent_ratings:
                firm = r.get("firm", "")
                to_grade = r.get("to_grade", "")
                date = r.get("date", "")[:10]
                if firm and to_grade:
                    lines.append(f"  {date} [{firm}] {to_grade}")
    
    # 収益予測
    earnings = analyst_data.get("earnings_estimates", {})
    if earnings.get("available"):
        quarterly = earnings.get("quarterly", [])[:2]
        if quarterly:
            lines.append(f"\n【収益予測（コンセンサス）】")
            for est in quarterly:
                period = est.get("period", "")
                avg = est.get("avg_estimate")
                growth = est.get("growth")
                if period and avg is not None:
                    growth_str = f" ({'+' if growth > 0 else ''}{growth*100:.1f}% YoY)" if growth else ""
                    lines.append(f"  {period}: ${avg:.2f}{growth_str}")
    
    return "\n".join(lines)


# テスト実行
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AMAT"
    
    print(f"🧪 Analyst Ratings テスト：{ticker}")
    result = fetch_all_analyst_data(ticker)
    print("\n" + "="*60)
    print(format_analyst_for_prompt(result))
    print("="*60)
