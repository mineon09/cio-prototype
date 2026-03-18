"""
data_cache.py - API レスポンスキャッシュ管理ユーティリティ
=======================================================
外部 API 呼び出しを最小限に抑えるためのキャッシュ機能

使い方:
    from src.data_cache import DataCache
    
    cache = DataCache()
    
    # キャッシュから取得
    data = cache.get("7203.T", "news")
    
    # キャッシュに保存（24 時間有効）
    cache.set("7203.T", "news", news_data, ttl_hours=24)
    
    # 自動キャッシュデコレータ
    @cache.cached(ttl_hours=24)
    def fetch_data(ticker):
        # API 呼び出し
        return data
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Dict, Callable, TypeVar, ParamSpec

# キャッシュディレクトリ
CACHE_DIR = Path(".edinet_cache")
CACHE_DIR.mkdir(exist_ok=True)

T = TypeVar('T')
P = ParamSpec('P')


class DataCache:
    """API レスポンスキャッシュマネージャー"""
    
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)
    
    def _get_cache_path(self, ticker: str, data_type: str) -> Path:
        """キャッシュファイルのパスを生成"""
        # ファイル名：7203.T_news.json
        safe_ticker = ticker.replace(".", "_").replace(":", "_")
        filename = f"{safe_ticker}_{data_type}.json"
        return self.cache_dir / filename
    
    def _is_expired(self, cache_path: Path, ttl_hours: int) -> bool:
        """キャッシュの有効期限をチェック"""
        if not cache_path.exists():
            return True
        
        try:
            mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
            expiry = mtime + timedelta(hours=ttl_hours)
            return datetime.now() > expiry
        except Exception:
            return True
    
    def get(self, ticker: str, data_type: str, ttl_hours: int = 24) -> Optional[Dict]:
        """
        キャッシュからデータを取得
        
        Args:
            ticker: 銘柄コード
            data_type: データタイプ ("news", "analyst", "industry", "stock_data")
            ttl_hours: 有効時間（時間）
        
        Returns:
            キャッシュデータ（期限切れまたは存在しない場合は None）
        """
        cache_path = self._get_cache_path(ticker, data_type)
        
        if self._is_expired(cache_path, ttl_hours):
            return None
        
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"  💾 [CACHE HIT] {ticker}/{data_type}")
                return data
        except Exception as e:
            print(f"  ⚠️ キャッシュ読み込みエラー：{e}")
            return None
    
    def set(self, ticker: str, data_type: str, data: Dict, ttl_hours: int = 24) -> bool:
        """
        キャッシュにデータを保存
        
        Args:
            ticker: 銘柄コード
            data_type: データタイプ
            data: 保存するデータ
            ttl_hours: 有効時間（時間）
        
        Returns:
            成功した場合 True
        """
        cache_path = self._get_cache_path(ticker, data_type)
        
        try:
            # データにメタデータを追加
            cache_data = {
                "data": data,
                "cached_at": datetime.now().isoformat(),
                "ttl_hours": ttl_hours,
                "ticker": ticker,
                "data_type": data_type,
            }
            
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False, default=str)
            
            print(f"  💾 [CACHE SAVE] {ticker}/{data_type}")
            return True
        except Exception as e:
            print(f"  ⚠️ キャッシュ保存エラー：{e}")
            return False
    
    def invalidate(self, ticker: str, data_type: Optional[str] = None) -> int:
        """
        キャッシュを削除
        
        Args:
            ticker: 銘柄コード
            data_type: 指定すればそのタイプのみ、None ですべて削除
        
        Returns:
            削除したファイル数
        """
        count = 0
        
        if data_type:
            cache_path = self._get_cache_path(ticker, data_type)
            if cache_path.exists():
                cache_path.unlink()
                count = 1
                print(f"  🗑️ [CACHE CLEAR] {ticker}/{data_type}")
        else:
            # 該当ティッカーの全キャッシュを削除
            safe_ticker = ticker.replace(".", "_").replace(":", "_")
            for cache_file in self.cache_dir.glob(f"{safe_ticker}_*.json"):
                cache_file.unlink()
                count += 1
                print(f"  🗑️ [CACHE CLEAR] {cache_file.name}")
        
        return count
    
    def clear_all(self) -> int:
        """全キャッシュを削除"""
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            count += 1
        print(f"  🗑️ [CACHE CLEAR ALL] {count} files")
        return count
    
    def cached(self, data_type: str, ttl_hours: int = 24) -> Callable:
        """
        自動キャッシュデコレータ
        
        使用例:
            @cache.cached("news", ttl_hours=24)
            def fetch_news(ticker):
                # API 呼び出し
                return news_data
        """
        def decorator(func: Callable[P, T]) -> Callable[P, T]:
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                # ticker を引数から取得（位置引数またはキーワード引数）
                ticker = kwargs.get('ticker')
                if ticker is None and args:
                    ticker = args[0]
                
                if ticker:
                    # キャッシュチェック
                    cached_data = self.get(ticker, data_type, ttl_hours)
                    if cached_data is not None:
                        return cached_data
                
                # 関数実行
                result = func(*args, **kwargs)
                
                # キャッシュ保存
                if ticker and result is not None:
                    self.set(ticker, data_type, result, ttl_hours)
                
                return result
            return wrapper
        return decorator


# グローバルキャッシュインスタンス
_cache_instance: Optional[DataCache] = None


def get_cache() -> DataCache:
    """グローバルキャッシュインスタンスを取得"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = DataCache()
    return _cache_instance


def clear_cache(ticker: Optional[str] = None, data_type: Optional[str] = None) -> int:
    """
    キャッシュをクリアするユーティリティ関数
    
    Args:
        ticker: 銘柄コード（None で全キャッシュ）
        data_type: データタイプ（None で全タイプ）
    
    Returns:
        削除したファイル数
    """
    cache = get_cache()
    
    if ticker:
        return cache.invalidate(ticker, data_type)
    else:
        return cache.clear_all()


def get_cache_stats() -> Dict[str, Any]:
    """キャッシュ統計情報を取得"""
    cache = get_cache()
    
    stats = {
        "total_files": 0,
        "total_size_bytes": 0,
        "data_types": {},
        "tickers": set(),
    }
    
    for cache_file in cache.cache_dir.glob("*.json"):
        try:
            size = cache_file.stat().st_size
            stats["total_files"] += 1
            stats["total_size_bytes"] += size
            
            # ファイル名から情報を抽出
            filename = cache_file.stem  # 拡張子なし
            parts = filename.split("_", 1)
            if len(parts) == 2:
                ticker, data_type = parts
                stats["tickers"].add(ticker)
                stats["data_types"][data_type] = stats["data_types"].get(data_type, 0) + 1
        except Exception:
            pass
    
    stats["tickers"] = list(stats["tickers"])
    stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)
    
    return stats


if __name__ == "__main__":
    # テスト
    print("Cache stats:", get_cache_stats())
