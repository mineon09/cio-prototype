"""
news_fetcher.py - ニュース・センチメント取得モジュール
=====================================================
Finnhub API と yfinance からリアルニュースを取得し、
Gemini で分析・アノテーションを行う。

設計方針：
- ニュースの「取得」（Finnhub / yfinance）と「分析」（Gemini）を分離
- Gemini はニュースの検索・生成を行わない（ハルシネーション防止）
- すべてのニュースに data_source タグを付与してトレーサビリティを確保

キャッシュシステム：
- 日付別でニュースをキャッシュ（7 日間保持）
- キャッシュ書き込み時に日付バリデーションを実施
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


def _validate_news_date(news_item: Dict, max_age_days: int = 14) -> bool:
    """
    ニュースアイテムの日付が有効範囲内かを検証する

    Parameters
    ----------
    news_item     : ニュースアイテム（published_at フィールド必須）
    max_age_days  : 許容する最大経過日数（デフォルト 14 日）

    Returns
    -------
    True: 日付が有効（過去 max_age_days 以内、かつ未来日でない）
    False: 日付が無効・欠損・パース不可
    """
    published_at = news_item.get("published_at", "")
    if not published_at or not isinstance(published_at, str):
        return False

    try:
        date_str = published_at.strip()
        if len(date_str) >= 16:
            parsed = datetime.strptime(date_str[:16], "%Y-%m-%d %H:%M")
        elif len(date_str) >= 10:
            parsed = datetime.strptime(date_str[:10], "%Y-%m-%d")
        else:
            return False
    except (ValueError, TypeError):
        return False

    now = datetime.now()
    # 未来日を拒否（1日の猶予を許容：タイムゾーン差）
    if parsed > now + timedelta(days=1):
        return False
    # max_age_days より古いものを拒否
    if parsed < now - timedelta(days=max_age_days):
        return False

    return True


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
                        if "data_source" not in item:
                            item["data_source"] = "cache"
                        all_news.append(item)
            except Exception:
                pass
    
    return all_news


def _save_news_cache(ticker: str, news: List[Dict]) -> None:
    """
    ニュースを当日のキャッシュファイルに保存（日付バリデーション付き）

    Parameters
    ----------
    ticker : 銘柄コード
    news   : 保存するニュースリスト
    """
    today = datetime.now()
    cache_file = _get_news_cache_file(ticker, today)

    # 日付バリデーションでフィルタ
    valid_news = []
    rejected = 0
    for item in news:
        if _validate_news_date(item):
            valid_news.append(item)
        else:
            rejected += 1

    if rejected > 0:
        print(f"  ⚠️ 日付不正のニュースを{rejected}件除外")

    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(valid_news, f, ensure_ascii=False, indent=2)
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
            # yfinance の新レスポンス構造（content ネスト）と旧構造の両方に対応
            content = item.get("content", {})
            if content:
                title = content.get("title", "")
                publisher = content.get("provider", {}).get("displayName", "")
                link = (content.get("canonicalUrl") or content.get("clickThroughUrl") or {}).get("url", "")
                pub_date_raw = content.get("pubDate", "") or content.get("displayTime", "")
                # "2026-03-25T11:48:30Z" → "2026-03-25 11:48"
                published_at = pub_date_raw.replace("T", " ").replace("Z", "")[:16] if pub_date_raw else ""
                thumbnail_url = ""
                thumb = content.get("thumbnail", {})
                if thumb:
                    resolutions = thumb.get("resolutions", [])
                    thumbnail_url = resolutions[0].get("url", "") if resolutions else thumb.get("originalUrl", "")
                item_type = content.get("contentType", "STORY")
            else:
                # 旧構造フォールバック
                title = item.get("title", "")
                publisher = item.get("publisher", "")
                link = item.get("link", "")
                ts = item.get("providerPublishTime", 0)
                published_at = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
                thumbnail_url = item.get("thumbnail", {}).get("resolutions", [{}])[0].get("url", "") if item.get("thumbnail") else ""
                item_type = item.get("type", "STORY")

            news_list.append({
                "title": title,
                "publisher": publisher,
                "link": link,
                "published_at": published_at,
                "type": item_type,
                "thumbnail": thumbnail_url,
                "data_source": "yfinance",
            })

        return news_list
    except Exception as e:
        print(f"  ⚠️ yfinance ニュース取得エラー：{e}")
        return []


def fetch_finnhub_news(ticker: str, days: int = 14, limit: int = 10) -> List[Dict]:
    """
    Finnhub API から銘柄の最新ニュースを取得（プライマリソース）

    Parameters
    ----------
    ticker : 銘柄コード（例: AAPL, MSFT）
    days   : 過去何日分のニュースを取得するか
    limit  : 最大取得件数

    Returns
    -------
    ニュースリスト（data_source: "finnhub" 付き）
    FINNHUB_API_KEY 未設定時は空リストを返す（グレースフルデグレード）
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key:
        return []

    try:
        import finnhub
        client = finnhub.Client(api_key=api_key)

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        raw_news = client.company_news(
            ticker,
            _from=start_date.strftime("%Y-%m-%d"),
            to=end_date.strftime("%Y-%m-%d"),
        )

        if not raw_news:
            return []

        news_list = []
        cutoff = datetime.now() - timedelta(days=days)

        for item in raw_news:
            ts = item.get("datetime", 0)
            if ts:
                pub_dt = datetime.fromtimestamp(ts)
            else:
                continue

            if pub_dt < cutoff:
                continue

            news_list.append({
                "title": item.get("headline", ""),
                "publisher": item.get("source", ""),
                "link": item.get("url", ""),
                "published_at": pub_dt.strftime("%Y-%m-%d %H:%M"),
                "type": item.get("category", "STORY"),
                "thumbnail": item.get("image", ""),
                "data_source": "finnhub",
            })

        news_list.sort(key=lambda x: x.get("published_at", ""), reverse=True)
        return news_list[:limit]

    except Exception as e:
        print(f"  ⚠️ Finnhub ニュース取得エラー：{e}")
        return []


def fetch_gemini_news_analysis(
    ticker: str,
    real_news_list: List[Dict],
    company_name: str = None,
) -> List[Dict]:
    """
    Gemini を使って実ニュースにセンチメント・カテゴリ等をアノテーションする

    Gemini は新しいニュースを生成しない。提供されたニュースのみをアノテーションする。

    Parameters
    ----------
    ticker          : 銘柄コード
    real_news_list  : Finnhub / yfinance から取得した実ニュースのリスト
    company_name    : 会社名（オプション）

    Returns
    -------
    アノテーション付きニュースリスト（入力と同数、追加なし）
    """
    if not real_news_list:
        return []

    name = company_name or ticker
    n = len(real_news_list)

    # Gemini に渡す簡易ニュースリスト（インデックス付き）
    news_for_prompt = []
    for i, item in enumerate(real_news_list):
        news_for_prompt.append({
            "index": i,
            "title": item.get("title", ""),
            "publisher": item.get("publisher", ""),
            "published_at": item.get("published_at", ""),
        })

    prompt = f"""You are annotating news items for {name} ({ticker}).

You are annotating ONLY the following {n} news items.
Do NOT add, invent, or hallucinate additional news items.
Return EXACTLY {n} items, one for each input item, in the same order.

【Input news items】
{json.dumps(news_for_prompt, ensure_ascii=False)}

【Task】
For each item, add:
- "sentiment": "positive" / "neutral" / "negative"
- "relevance": "high" / "medium" / "low"
- "category": "earnings" / "M&A" / "product" / "analyst" / "risk" / "other"
- "summary_ja": 日本語の要約（50〜80文字）

【Output format】
Return a JSON array of {n} objects. Each object must include ALL original fields
(index, title, publisher, published_at) plus the 4 new annotation fields.
Output ONLY valid JSON array, no additional text.
"""

    try:
        result, _ = call_gemini(prompt, parse_json=True)

        if not isinstance(result, list):
            return real_news_list

        # アノテーション結果を元のリストにマージ
        annotated = []
        for i, original in enumerate(real_news_list):
            item = original.copy()
            # 対応するアノテーションを探す（インデックスまたは順序で）
            annotation = None
            if i < len(result):
                annotation = result[i]
            else:
                for r in result:
                    if r.get("index") == i:
                        annotation = r
                        break

            if annotation:
                item["sentiment"] = annotation.get("sentiment", "neutral")
                item["relevance"] = annotation.get("relevance", "medium")
                item["category"] = annotation.get("category", "other")
                item["summary"] = annotation.get("summary_ja", "")
            else:
                item.setdefault("sentiment", "neutral")
                item.setdefault("relevance", "medium")
                item.setdefault("category", "other")
                item.setdefault("summary", "")

            annotated.append(item)

        return annotated

    except Exception as e:
        print(f"  ⚠️ Gemini ニュース分析エラー：{e}")
        return real_news_list


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

    フロー：
    1. yfinance → 日付バリデーション
    2. Finnhub → 日付フィルタ済み
    3. マージ＋重複排除
    4. Gemini でアノテーション（センチメント・カテゴリ等）
    5. 総合センチメント分析
    6. キャッシュ保存（バリデーション付き）

    Parameters
    ----------
    ticker        : 銘柄コード
    company_name  : 会社名
    include_google: Gemini 分析を含むか（後方互換性のため維持）
    yf_limit      : yfinance 取得件数
    google_limit  : Finnhub 取得件数（後方互換パラメータ名）
    google_days   : ニュース検索期間（日）
    use_cache     : キャッシュを使用するか
    cache_days    : キャッシュ保持日数

    Returns
    -------
    統合ニュースデータ
    """
    print(f"  📰 {ticker} のニュース収集中...")

    # ── Step 1: yfinance ニュース取得＋日付フィルタ ──
    yf_news_raw = fetch_yf_news(ticker, limit=yf_limit)
    yf_news = [n for n in yf_news_raw if _validate_news_date(n, max_age_days=google_days)]
    if len(yf_news_raw) != len(yf_news):
        print(f"    ✓ yfinance: {len(yf_news)} 件（{len(yf_news_raw) - len(yf_news)}件を日付フィルタで除外）")
    else:
        print(f"    ✓ yfinance: {len(yf_news)} 件")

    # ── Step 2: Finnhub ニュース取得（既に日付フィルタ済み） ──
    finnhub_news = fetch_finnhub_news(ticker, days=google_days, limit=google_limit)
    if finnhub_news:
        print(f"    ✓ Finnhub: {len(finnhub_news)} 件")
    else:
        api_key = os.getenv("FINNHUB_API_KEY", "")
        if not api_key:
            print(f"    ⚠️ Finnhub: APIキー未設定（FINNHUB_API_KEY）→ yfinance のみで継続")
        else:
            print(f"    ⚠️ Finnhub: 0 件")

    # ── Step 3: マージ＋重複排除 ──
    merged_news = []
    seen_titles = set()

    for item in yf_news:
        title = item.get("title", "")
        if title and title not in seen_titles:
            seen_titles.add(title)
            merged_news.append(item)

    for item in finnhub_news:
        title = item.get("title", "")
        if title and title not in seen_titles:
            seen_titles.add(title)
            merged_news.append(item)

    # キャッシュからも補完
    cached_news = []
    if use_cache:
        cached_news = _load_cached_news(ticker, days=cache_days)
        for item in cached_news:
            title = item.get("title", "")
            if title and title not in seen_titles and _validate_news_date(item, max_age_days=google_days):
                seen_titles.add(title)
                merged_news.append(item)
        if cached_news:
            print(f"    ✓ キャッシュ補完：{len(cached_news)} 件から有効分を追加")

    print(f"    → マージ後：{len(merged_news)} 件")

    # ── Step 4: ニュースが少ない場合の警告 ──
    if len(merged_news) < 3:
        print(f"    ⚠️ ニュースが{len(merged_news)}件のみ（Finnhub APIキーの確認を推奨）")

    # ── Step 5: Gemini アノテーション（センチメント・カテゴリ付与） ──
    annotated_news = merged_news
    if include_google and merged_news:
        annotated_news = fetch_gemini_news_analysis(
            ticker, merged_news, company_name=company_name
        )
        print(f"    ✓ Gemini アノテーション完了")

    # 日付でソート（新しい順）
    def get_date_key(news):
        published_at = news.get('published_at', '')
        if isinstance(published_at, str) and len(published_at) >= 10:
            return published_at[:10]
        return '0000-00-00'

    annotated_news.sort(key=get_date_key, reverse=True)

    # ── Step 6: 総合センチメント分析 ──
    sentiment = analyze_news_sentiment(annotated_news)

    # ── Step 7: キャッシュ保存（バリデーション付き） ──
    if annotated_news:
        _save_news_cache(ticker, annotated_news)
        _cleanup_old_cache(ticker, keep_days=cache_days)

    return {
        "available": True,
        "yf_news": yf_news,
        "finnhub_news": finnhub_news,
        "all_news": annotated_news[:15],
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

            # data_source タグ
            ds = news.get("data_source", "")
            ds_tag = f" [{ds}]" if ds else ""

            lines.append(f"  {i}. {sentiment_mark} {source_info}{title} {date_info}{ds_tag}")

    return "\n".join(lines)


def fetch_web_search_news(query: str, max_results: int = 5) -> List[Dict]:
    """
    ウェブ検索 API でニュースを取得する（Exa → Perplexity → Tavily フォールバック）。

    Parameters
    ----------
    query       : 検索クエリ（例: "トヨタ 株価 最新ニュース"）
    max_results : 取得件数

    Returns
    -------
    [
      {
        "title":        str,
        "url":          str,
        "content":      str,
        "published_at": str | None,
        "data_source":  "exa" | "perplexity" | "tavily"
      },
      ...
    ]
    失敗時は []
    """
    import requests as _req

    # ── Exa ────────────────────────────────────────────────
    exa_key = os.getenv("EXA_API_KEY", "")
    if exa_key:
        try:
            resp = _req.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": exa_key, "Content-Type": "application/json"},
                json={
                    "query": query,
                    "numResults": max_results,
                    "useAutoprompt": True,
                    "contents": {"text": {"maxCharacters": 500}},
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                news = []
                for r in results[:max_results]:
                    news.append({
                        "title":        r.get("title", ""),
                        "url":          r.get("url", ""),
                        "content":      (r.get("text") or r.get("snippet") or "")[:500],
                        "published_at": r.get("publishedDate") or r.get("published_date"),
                        "data_source":  "exa",
                    })
                print(f"    ✓ Exa: {len(news)} 件")
                return news
        except Exception as e:
            print(f"    ⚠️ Exa 失敗: {e} → Perplexity にフォールバック")

    # ── Perplexity ─────────────────────────────────────────
    perp_key = os.getenv("PERPLEXITY_API_KEY", "")
    if perp_key:
        try:
            resp = _req.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {perp_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar",
                    "messages": [
                        {"role": "system", "content": "You are a financial news assistant. Return only JSON."},
                        {
                            "role": "user",
                            "content": (
                                f"Search for the latest news about: {query}\n"
                                f"Return a JSON array of up to {max_results} results. "
                                "Each object must have: title (string), url (string), "
                                "content (string, ≤500 chars), published_at (ISO date or null)."
                            ),
                        },
                    ],
                    "return_citations": True,
                },
                timeout=20,
            )
            resp.raise_for_status()
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            # JSON 部分を抽出
            import re as _re
            m = _re.search(r"\[.*\]", content, _re.DOTALL)
            if m:
                items = json.loads(m.group())
                news = []
                for item in items[:max_results]:
                    if isinstance(item, dict):
                        news.append({
                            "title":        item.get("title", ""),
                            "url":          item.get("url", ""),
                            "content":      str(item.get("content", ""))[:500],
                            "published_at": item.get("published_at"),
                            "data_source":  "perplexity",
                        })
                if news:
                    print(f"    ✓ Perplexity: {len(news)} 件")
                    return news
        except Exception as e:
            print(f"    ⚠️ Perplexity 失敗: {e} → Tavily にフォールバック")

    # ── Tavily ─────────────────────────────────────────────
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if tavily_key:
        try:
            resp = _req.post(
                "https://api.tavily.com/search",
                headers={"Content-Type": "application/json"},
                json={
                    "api_key": tavily_key,
                    "query": query,
                    "max_results": max_results,
                    "include_raw_content": False,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                news = []
                for r in results[:max_results]:
                    news.append({
                        "title":        r.get("title", ""),
                        "url":          r.get("url", ""),
                        "content":      (r.get("content") or "")[:500],
                        "published_at": r.get("published_date"),
                        "data_source":  "tavily",
                    })
                print(f"    ✓ Tavily: {len(news)} 件")
                return news
        except Exception as e:
            print(f"    ⚠️ Tavily 失敗: {e}")

    print(f"    ⚠️ ウェブ検索ニュース: 全 API 失敗（EXA_API_KEY, PERPLEXITY_API_KEY, TAVILY_API_KEY を確認してください）")
    return []


# テスト実行
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    ticker = sys.argv[1] if len(sys.argv) > 1 else "AMAT"

    print(f"🧪 News Fetcher テスト：{ticker}")
    print(f"  FINNHUB_API_KEY: {'設定済み' if os.getenv('FINNHUB_API_KEY') else '未設定'}")
    result = fetch_all_news(ticker, include_google=True)

    print("\n" + "=" * 60)
    print(format_news_for_prompt(result))
    print("=" * 60)

    # data_source 分布を表示
    sources = {}
    for item in result.get("all_news", []):
        src = item.get("data_source", "unknown")
        sources[src] = sources.get(src, 0) + 1
    print(f"\n📊 データソース分布: {sources}")
