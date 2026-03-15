"""
parallel_utils.py - 並列処理ユーティリティ
==========================================
データ取得の並列処理を実装する。

使用例:
    from src.parallel_utils import fetch_multiple_tickers
    results = fetch_multiple_tickers(['AAPL', 'GOOGL', 'MSFT'])
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Callable, Any, Optional
import logging

from src.logging_utils import get_logger

logger = get_logger(__name__)


def fetch_multiple_tickers(
    tickers: List[str],
    fetch_func: Callable[[str], Any],
    max_workers: int = 4,
    fallback_value: Optional[Any] = None
) -> Dict[str, Any]:
    """
    複数銘柄のデータを並列取得する。

    Args:
        tickers: ティッカーリスト
        fetch_func: データ取得関数（ticker を受け取りデータを返す）
        max_workers: 最大ワーカースレッド数
        fallback_value: エラー時のフォールバック値

    Returns:
        {ticker: data} の辞書
    """
    if fallback_value is None:
        fallback_value = {"ticker": "", "name": "", "metrics": {}, "technical": {}}
    
    results = {}
    
    def fetch_with_fallback(ticker: str) -> tuple:
        try:
            data = fetch_func(ticker)
            return ticker, data
        except Exception as e:
            logger.warning(f"{ticker} 取得失敗：{e}")
            fallback = fallback_value.copy() if isinstance(fallback_value, dict) else fallback_value
            if isinstance(fallback, dict):
                fallback['ticker'] = ticker
            return ticker, fallback
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_with_fallback, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, data = future.result()
            results[ticker] = data
    
    return results


def parallel_map(
    func: Callable[[Any], Any],
    items: List[Any],
    max_workers: int = 4,
    handle_errors: bool = True
) -> List[Any]:
    """
    関数を複数アイテムに並列適用する。

    Args:
        func: 適用する関数
        items: アイテムリスト
        max_workers: 最大ワーカースレッド数
        handle_errors: エラーを捕捉して None を返すか

    Returns:
        結果リスト
    """
    results = [None] * len(items)
    
    def apply_with_index(args):
        i, item = args
        try:
            return i, func(item)
        except Exception as e:
            if handle_errors:
                logger.warning(f"アイテム {i} 処理失敗：{e}")
                return i, None
            raise
    
    indexed_items = list(enumerate(items))
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(apply_with_index, args): args for args in indexed_items}
        for future in as_completed(futures):
            i, result = future.result()
            results[i] = result
    
    return results
