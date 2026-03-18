"""
news_fetcher.py - ニュース・センチメント取得モジュール
=====================================================
yfinance ニュースと Google 検索を組み合わせ、
銘柄に関する最新ニュースと市場センチメントを取得する。

キャッシュシステム：
- 日付別でニュースをキャッシュ（7 日間保持）
- 複数日のニュースを統合して最新情報を提供
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


# キャッシュ設定
NEWS_CACHE_DIR = os.path.join("data", "cache", "news")
NEWS_CACHE_DAYS = 7  # 7 日間保持


def _get_news_cache_dir() -> str:
    """ニュースキャッシュディレクトリの取得と作成"""
    os.makedirs(NEWS_CACHE_DIR, exist_ok=True)
    return NEWS_CACHE_DIR


def _get_news_cache_file(ticker: str, date: datetime) -> str:
    """特定の日付のキャッシュファイルパスを返す"""
    return os.path.join(_get_news_cache_dir(), f"{ticker}_{date.strftime('%Y%m%d')}.json")


def _load_cached_news(ticker: str, days: int = 7) -> List[Dict]:
    """
    過去 N 日分のキャッシュからニュースを読み込む
    
    Parameters
    ----------
    ticker : 銘柄コード
    days   : 過去何日分を読み込むか
    
    Returns
    -------
    統合されたニュースリスト
    """
    all_news = []
    seen_titles = set()
    
    for i in range(days):
        date = datetime.now() - timedelta(days=i)
        cache_file = _get_news_cache_file(ticker, date)
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_news = json.load(f)
                
                for item in cached_news:
                    title = item.get('title', '')
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_news.append(item)
            except Exception:
                pass
    
    return all_news


def _save_news_cache(ticker: str, news: List[Dict]) -> None:
    """
    ニュースを当日のキャッシュファイルに保存
    
    Parameters
    ----------
    ticker : 銘柄コード
    news   : 保存するニュースリスト
    """
    today = datetime.now()
    cache_file = _get_news_cache_file(ticker, today)
    
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(news, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️ キャッシュ保存エラー：{e}")


def _cleanup_old_cache(ticker: str, keep_days: int = 7) -> None:
    """
    古いキャッシュファイルを削除
    
    Parameters
    ----------
    ticker    : 銘柄コード
    keep_days : 保持する日数
    """
    cache_dir = _get_news_cache_dir()
    cutoff_date = datetime.now() - timedelta(days=keep_days)
    
    try:
        for filename in os.listdir(cache_dir):
            if filename.startswith(f"{ticker}_") and filename.endswith(".json"):
                # ファイル名から日付を抽出
                date_str = filename.replace(f"{ticker}_", "").replace(".json", "")
                try:
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                    if file_date < cutoff_date:
                        os.remove(os.path.join(cache_dir, filename))
                except ValueError:
                    pass
    except Exception:
        pass


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
        print(f"  ⚠️ yfinance ニュース取得エラー：{e}")
        return []


def fetch_google_news(ticker: str, company_name: str = None, limit: int = 10, days: int = 14) -> List[Dict]:
    """
    Gemini 検索機能で Google ニュースから関連記事を取得（強化版）
    複数クエリで網羅性向上

    Parameters
    ----------
    ticker        : 銘柄コード
    company_name  : 会社名（オプション）
    limit         : 取得件数
    days          : 過去何日分のニュースを取得するか

    Returns
    -------
    ニュースリスト
    """
    name = company_name or ticker
    
    # 複数クエリで網羅性向上
    queries = [
        f"{name} ({ticker}) 決算 業績 予想",
        f"{name} ({ticker}) M&A 提携 買収",
        f"{name} ({ticker}) 新製品 技術 発表",
        f"{name} ({ticker}) アナリスト 格付け 目標株価",
        f"{name} ({ticker}) リスク 規制 訴訟",
    ]

    all_news = []
    seen_titles = set()

    for i, query in enumerate(queries):
        prompt = f"""
You are a financial research assistant specializing in Japanese stock market news.
Search for news about: {query}

Find news articles from the past {days} days and return up to {max(3, limit // len(queries))} relevant items.

Return a JSON array with the following structure:
[
  {{
    "title": "ニュースタイトル（日本語）",
    "source": "情報源（例：ロイター、ブルームバーグ、日経、Reuters など）",
    "published_date": "YYYY-MM-DD",
    "summary": "要約（日本語 50-100 文字）",
    "sentiment": "positive/neutral/negative",
    "relevance": "high/medium/low",
    "category": "earnings/M&A/product/analyst/risk/other"
  }}
]

IMPORTANT:
- Focus on material news: earnings, M&A, product launches, regulatory changes, analyst ratings
- Exclude generic market commentary or unrelated articles
- Only include news from the past {days} days
- Output ONLY valid JSON array, no additional text
- If no relevant news found, return empty array []
"""

        try:
            result, model = call_gemini(prompt, parse_json=True, use_search=True)

            if isinstance(result, list):
                for item in result:
                    title = item.get("title", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_news.append(item)
            elif isinstance(result, dict) and "news" in result:
                for item in result["news"]:
                    title = item.get("title", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_news.append(item)
        except Exception as e:
            print(f"  ⚠️ Google ニュース検索エラー（クエリ {i+1}/{len(queries)}）: {e}")
            continue

    # 関連度でソート（high > medium > low）
    relevance_order = {"high": 0, "medium": 1, "low": 2, "other": 3}
    all_news.sort(key=lambda x: relevance_order.get(x.get("relevance", "other"), 3))

    return all_news[:limit]


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

    # Gemini で分析
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
        print(f"  ⚠️ センチメント分析エラー：{e}")
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
    google_limit: int = 10,
    google_days: int = 14,
    use_cache: bool = True,
    cache_days: int = 7
) -> Dict:
    """
    全てのニュースソースから情報を収集（キャッシュ対応）

    Parameters
    ----------
    ticker        : 銘柄コード
    company_name  : 会社名
    include_google: Google 検索を含むか
    yf_limit      : yfinance 取得件数
    google_limit  : Google ニュース取得件数
    google_days   : Google ニュース検索期間（日）
    use_cache     : キャッシュを使用するか
    cache_days    : キャッシュ保持日数

    Returns
    -------
    統合ニュースデータ
    """
    print(f"  📰 {ticker} のニュース収集中...")

    # キャッシュから読み込み（use_cache=True の場合）
    cached_news = []
    if use_cache:
        cached_news = _load_cached_news(ticker, days=cache_days)
        if cached_news:
            print(f"    ✓ キャッシュ：{len(cached_news)} 件（過去{cache_days}日分）")

    # yfinance ニュース
    yf_news = fetch_yf_news(ticker, limit=yf_limit)
    print(f"    ✓ yfinance: {len(yf_news)} 件")

    # Google ニュース（キャッシュが十分にある場合はスキップ）
    google_news = []
    if include_google:
        # キャッシュが 5 件未満の場合は新規取得
        if len(cached_news) < 5:
            google_news = fetch_google_news(ticker, company_name, limit=google_limit, days=google_days)
            print(f"    ✓ Google News: {len(google_news)} 件")
            
            # キャッシュに保存
            if google_news:
                _save_news_cache(ticker, google_news)
                _cleanup_old_cache(ticker, keep_days=cache_days)
        else:
            print(f"    ✓ Google News: キャッシュ使用（{len(cached_news)}件）")
            google_news = cached_news

    # 統合（キャッシュ＋新規）
    all_news = yf_news.copy()

    # キャッシュニュースを追加（重複チェック付き）
    existing_titles = {n["title"] for n in yf_news}
    for cn in cached_news:
        if cn.get("title") not in existing_titles:
            all_news.append(cn)
            existing_titles.add(cn.get("title", ""))

    # Google ニュースを追加（重複チェック付き）
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

    # 日付でソート（新しい順）
    def get_date_key(news):
        published_at = news.get('published_at', '')
        if isinstance(published_at, str) and len(published_at) >= 10:
            return published_at[:10]
        return '0000-00-00'
    
    all_news.sort(key=get_date_key, reverse=True)

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
