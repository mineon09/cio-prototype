"""
sec_cache.py - SEC 10-K テキスト・LLM 解析結果のファイルキャッシュ管理
=======================================================================
10-K 生テキストと LLM 解析結果をローカルファイルにキャッシュする。

キャッシュ構成:
  cache/
  ├── sec_text/      ← {ticker}_{filing_date}.txt  (TTL: 90日)
  └── sec_analysis/  ← {ticker}_{filing_date}.json (TTL: 90日)

キャッシュキー: {ticker.lower()}_{filing_date}  (例: amat_2025-12-12)
"""

import json
from datetime import datetime, timedelta
from pathlib import Path


class SecCache:
    """SEC 10-K の生テキストと LLM 解析結果を管理するファイルキャッシュ。"""

    TTL_DAYS = 90

    def __init__(self, cache_root: str | Path = None):
        if cache_root is None:
            cache_root = Path(__file__).parent / "cache"
        self.root = Path(cache_root)
        self.text_dir = self.root / "sec_text"
        self.analysis_dir = self.root / "sec_analysis"
        self.text_dir.mkdir(parents=True, exist_ok=True)
        self.analysis_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, ticker: str, filing_date: str) -> str:
        return f"{ticker.lower()}_{filing_date}"

    def _is_expired(self, path: Path) -> bool:
        if not path.exists():
            return True
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime > timedelta(days=self.TTL_DAYS)

    def get_text(self, ticker: str, filing_date: str, no_cache: bool = False) -> str | None:
        """キャッシュされた 10-K 生テキストを返す。未キャッシュ・期限切れ・no_cache の場合は None。"""
        if no_cache or not filing_date:
            return None
        path = self.text_dir / f"{self._cache_key(ticker, filing_date)}.txt"
        if self._is_expired(path):
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def save_text(self, ticker: str, filing_date: str, text: str) -> None:
        """10-K 生テキストをキャッシュファイルに保存する。"""
        if not filing_date or not text:
            return
        path = self.text_dir / f"{self._cache_key(ticker, filing_date)}.txt"
        path.write_text(text, encoding="utf-8")

    def get_analysis(self, ticker: str, filing_date: str, no_cache: bool = False) -> dict | None:
        """キャッシュされた LLM 解析結果を返す。{"analysis": dict, "meta": dict} 形式。"""
        if no_cache or not filing_date:
            return None
        path = self.analysis_dir / f"{self._cache_key(ticker, filing_date)}.json"
        if self._is_expired(path):
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def save_analysis(self, ticker: str, filing_date: str, analysis: dict, meta: dict) -> None:
        """LLM 解析結果をキャッシュファイルに保存する。"""
        if not filing_date:
            return
        path = self.analysis_dir / f"{self._cache_key(ticker, filing_date)}.json"
        payload = {"analysis": analysis, "meta": meta}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
