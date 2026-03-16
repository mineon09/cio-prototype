"""
news_fetcher.py - ニュース・センチメント取得モジュール
=====================================================
yfinance ニュースと Google 検索を組み合わせ、
銘柄に関する最新ニュースと市場センチメントを取得する。
"""

import os
import re
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import yfinance as yf

try:
    from .data_fetcher import call_gemini
except ImportError:
    from data_fetcher import call_gemini


def fetch_yf_news(ticker: str, limit: int = 10) -> List[Dict]:
    """
    yfinance から銘柄の最新ニュースを取得
    
    Parameters
    ----------
    ticker : 銘柄コード
    limit  : 取得件数（最大 10 件）
    
    Returns
    -------
    ニュースリスト（日付順、新しい順）
    """
    try:
        stock = yf.Ticker(ticker)
        news_data = stock.news
        
        if not news_data:
            return []
        
        news_list = []
        for item in news_data[:limit]:
            news_list.append({
                "title": item.get("title", ""),
                "publisher": item.get("publisher", ""),
                "link": item.get("link", ""),
                "published_at": datetime.fromtimestamp(item.get("providerPublishTime", 0)).strftime("%Y-%m-%d %H:%M") if item.get("providerPublishTime") else "",
                "type": item.get("type", "STORY"),
                "thumbnail": item.get("thumbnail", {}).get("resolutions", [{}])[0].get("url", "") if item.get("thumbnail") else "",
            })
        
        return news_list
    except Exception as e:
        print(f"  ⚠️ yfinance ニュース取得エラー: {e}")
        return []


def fetch_google_news(ticker: str, company_name: str = None, limit: int = 5) -> List[Dict]:
    """
    Gemini 検索機能で Google ニュースから関連記事を取得
    
    Parameters
    ----------
    ticker        : 銘柄コード
    company_name  : 会社名（オプション）
    limit         : 取得件数
    
    Returns
    -------
    ニュースリスト
    """
    name = company_name or ticker
    
    prompt = f"""
You are a financial research assistant.
Search for the latest news about {name} ({ticker}) from the past 2 weeks.

Return a JSON array of up to {limit} news items with the following structure:
[
  {{
    "title": "ニュースタイトル（日本語）",
    "source": "情報源（例：Reuters, Bloomberg, 日経など）",
    "published_date": "YYYY-MM-DD",
    "summary": "要約（日本語 50 文字以内）",
    "sentiment": "positive/neutral/negative",
    "relevance": "high/medium/low"
  }}
]

IMPORTANT:
- Only include news from the past 14 days
- Focus on material news (earnings, M&A, product launches, regulatory changes, etc.)
- Exclude generic market commentary
- Output ONLY valid JSON array, no additional text
"""
    
    try:
        result, model = call_gemini(prompt, parse_json=True, use_search=True)
        
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "news" in result:
            return result["news"]
        else:
            return []
    except Exception as e:
        print(f"  ⚠️ Google ニュース検索エラー: {e}")
        return []


def analyze_news_sentiment(news_list: List[Dict]) -> Dict:
    """
    ニュースリストからセンチメント分析を実行
    
    Parameters
    ----------
    news_list : ニュースリスト
    
    Returns
    -------
    センチメント分析結果
    """
    if not news_list:
        return {
            "overall": "neutral",
            "score": 0,
            "positive_count": 0,
            "neutral_count": 0,
            "negative_count": 0,
            "key_themes": [],
            "summary": "分析対象となるニュースがありません"
        }
    
    # yfinance ニュースの場合は Gemini で分析
    prompt = f"""
You are a sentiment analysis AI.
Analyze the following news headlines and determine the overall market sentiment.

【News Headlines】
{json.dumps(news_list[:10], ensure_ascii=False)}

【Output Format】
Return a JSON object with the following structure:
{{
  "overall": "positive/neutral/negative",
  "score": -1.0 to 1.0 (positive is >0, negative is <0),
  "positive_count": number,
  "neutral_count": number,
  "negative_count": number,
  "key_themes": ["テーマ 1", "テーマ 2", ...],
  "summary": "センチメント分析の要約（日本語 100 文字以内）"
}}

Consider:
- Earnings results and guidance
- M&A activity
- Product launches/recalls
- Regulatory changes
- Management changes
- Legal issues
- Market share changes
"""
    
    try:
        result, _ = call_gemini(prompt, parse_json=True)
        
        if isinstance(result, dict):
            return result
        else:
            return {
                "overall": "neutral",
                "score": 0,
                "positive_count": 0,
                "neutral_count": len(news_list),
                "negative_count": 0,
                "key_themes": [],
                "summary": "センチメント分析エラー"
            }
    except Exception as e:
        print(f"  ⚠️ センチメント分析エラー: {e}")
        return {
            "overall": "neutral",
            "score": 0,
            "positive_count": 0,
            "neutral_count": len(news_list),
            "negative_count": 0,
            "key_themes": [],
            "summary": f"分析エラー：{str(e)}"
        }


def fetch_all_news(
    ticker: str,
    company_name: str = None,
    include_google: bool = True,
    yf_limit: int = 10,
    google_limit: int = 5
) -> Dict:
    """
    全てのニュースソースから情報を収集
    
    Parameters
    ----------
    ticker        : 銘柄コード
    company_name  : 会社名
    include_google: Google 検索を含むか
    yf_limit      : yfinance 取得件数
    google_limit  : Google ニュース取得件数
    
    Returns
    -------
    統合ニュースデータ
    """
    print(f"  📰 {ticker} のニュース収集中...")
    
    # yfinance ニュース
    yf_news = fetch_yf_news(ticker, limit=yf_limit)
    print(f"    ✓ yfinance: {len(yf_news)} 件")
    
    # Google ニュース
    google_news = []
    if include_google:
        google_news = fetch_google_news(ticker, company_name, limit=google_limit)
        print(f"    ✓ Google News: {len(google_news)} 件")
    
    # 統合
    all_news = yf_news.copy()
    
    # Google ニュースを追加（重複チェック付き）
    existing_titles = {n["title"] for n in yf_news}
    for gn in google_news:
        if gn.get("title") not in existing_titles:
            all_news.append({
                "title": gn.get("title", ""),
                "publisher": gn.get("source", ""),
                "link": gn.get("link", ""),
                "published_at": gn.get("published_date", ""),
                "type": "GOOGLE_NEWS",
                "thumbnail": "",
                "summary": gn.get("summary", ""),
                "sentiment": gn.get("sentiment", "neutral"),
                "relevance": gn.get("relevance", "medium"),
            })
            existing_titles.add(gn.get("title", ""))
    
    # センチメント分析
    sentiment = analyze_news_sentiment(all_news)
    
    return {
        "available": True,
        "yf_news": yf_news,
        "google_news": google_news,
        "all_news": all_news[:15],  # 最大 15 件に制限
        "sentiment": sentiment,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def format_news_for_prompt(news_data: Dict, max_items: int = 5) -> str:
    """
    ニュースデータをプロンプト用テキストに整形
    
    Parameters
    ----------
    news_data : fetch_all_news の戻り値
    max_items : 表示件数
    
    Returns
    -------
    整形済みテキスト
    """
    if not news_data or not news_data.get("available"):
        return "（ニュースデータ未取得）"
    
    lines = []
    
    # センチメントサマリー
    sentiment = news_data.get("sentiment", {})
    sentiment_emoji = {
        "positive": "📈",
        "neutral": "➡️",
        "negative": "📉"
    }.get(sentiment.get("overall", "neutral"), "➡️")
    
    lines.append(f"【市場センチメント】 {sentiment_emoji} {sentiment.get('overall', 'neutral').upper()}")
    lines.append(f"  スコア：{sentiment.get('score', 0):.2f} (-1〜+1)")
    lines.append(f"  要約：{sentiment.get('summary', '')}")
    
    if sentiment.get("key_themes"):
        lines.append(f"  主要テーマ：{', '.join(sentiment['key_themes'][:3])}")
    
    # 最新ニュース
    all_news = news_data.get("all_news", [])[:max_items]
    if all_news:
        lines.append("\n【最新ニュース】")
        for i, news in enumerate(all_news, 1):
            sentiment_mark = ""
            if news.get("sentiment"):
                sentiment_mark = {
                    "positive": "🟢",
                    "neutral": "⚪",
                    "negative": "🔴"
                }.get(news.get("sentiment", "neutral"), "⚪")

            publisher = news.get("publisher", "") or news.get("source", "")
            # 日付フォーマット統一 (YYYY-MM-DD または YYYY-MM-DD HH:MM)
            published_at = news.get("published_at", "")
            if published_at:
                if isinstance(published_at, str):
                    date = published_at[:10] if len(published_at) >= 10 else published_at
                else:
                    date = str(published_at)[:10]
            else:
                date = ""
            
            title = news.get("title", "タイトルなし")
            source_info = f"[{publisher}] " if publisher else ""
            date_info = f"({date})" if date else ""
            
            lines.append(f"  {i}. {sentiment_mark} {source_info}{title} {date_info}")
    
    return "\n".join(lines)


# テスト実行
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AMAT"
    
    print(f"🧪 News Fetcher テスト：{ticker}")
    result = fetch_all_news(ticker, include_google=True)
    print("\n" + "="*60)
    print(format_news_for_prompt(result))
    print("="*60)
