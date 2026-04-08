"""
edinetdb_client.py - EDINET DB API クライアント
================================================
edinetdb.jp/v1 API を使用して日本株の財務データ・有報テキスト・
企業情報を取得する。dexter-jp (edinetdb/dexter-jp) と同様の
エンドポイントを Python から呼び出す。

設計方針:
- EDINETDB_API_KEY 未設定時は空辞書を返してメインフローを止めない
- cache/ ディレクトリに TTL 付きキャッシュ（財務: 24h, 有報テキスト: 72h）
- ティッカー (7203.T) → 4桁コード (7203) → EDINET コード (E02144) の変換を内蔵
"""

import os
import json
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ─── 定数 ───────────────────────────────────────────────
BASE_URL = "https://edinetdb.jp/v1"
CACHE_DIR = Path(".edinetdb_cache")
CACHE_DIR.mkdir(exist_ok=True)

# ─── 内部ヘルパー ────────────────────────────────────────

def _api_key() -> str:
    return os.environ.get("EDINETDB_API_KEY", "")


def _headers() -> dict:
    return {"X-API-Key": _api_key(), "Content-Type": "application/json"}


def _cache_path(endpoint: str, params: dict) -> Path:
    key = json.dumps({"ep": endpoint, "p": params}, sort_keys=True)
    hsh = hashlib.md5(key.encode()).hexdigest()[:12]
    safe = endpoint.replace("/", "_").strip("_")
    return CACHE_DIR / f"{safe}_{hsh}.json"


def _load_cache(path: Path, ttl_hours: float) -> Optional[Any]:
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    if datetime.now() - mtime > timedelta(hours=ttl_hours):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(path: Path, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get(endpoint: str, params: Optional[dict] = None, ttl_hours: float = 24.0) -> dict:
    """
    EDINET DB API に GET リクエストを送信し、キャッシュを返す。

    Parameters
    ----------
    endpoint   : パス（例: "/search"）
    params     : クエリパラメータ
    ttl_hours  : キャッシュ有効期間（時間）

    Returns
    -------
    API レスポンスの dict。失敗時は {}
    """
    if not _api_key():
        return {}

    params = params or {}
    cache = _cache_path(endpoint, params)
    cached = _load_cache(cache, ttl_hours)
    if cached is not None:
        return cached

    url = f"{BASE_URL}{endpoint}"
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _save_cache(cache, data)
        return data
    except requests.exceptions.HTTPError as e:
        print(f"  ⚠️ [EDINET DB] HTTP エラー {endpoint}: {e}")
        return {}
    except Exception as e:
        print(f"  ⚠️ [EDINET DB] リクエスト失敗 {endpoint}: {e}")
        return {}


# ─── ティッカー解決 ──────────────────────────────────────

def normalize_ticker(ticker: str) -> str:
    """7203.T → 7203 のように .T / .TYO などのサフィックスを除去"""
    return ticker.split(".")[0]


def resolve_edinet_code(ticker: str) -> Optional[str]:
    """
    ティッカーまたは銘柄コードから EDINET コード (E0XXXX) を解決する。

    Parameters
    ----------
    ticker : 例 "7203.T", "7203", "トヨタ", "E02144"

    Returns
    -------
    EDINET コード (例: "E02144") または None
    """
    # すでに EDINET コード
    import re
    if re.match(r"^E\d{5}$", ticker.strip()):
        return ticker.strip()

    sec_code = normalize_ticker(ticker)

    resp = _get("/search", {"q": sec_code, "limit": 1})
    companies = resp.get("data", [])
    if not companies:
        print(f"  ⚠️ [EDINET DB] 企業が見つかりません: {ticker}")
        return None
    return companies[0].get("edinet_code")


# ─── 公開 API ────────────────────────────────────────────

def get_company_info(ticker: str) -> dict:
    """
    企業基本情報 + 最新財務 + 主要指標を取得する。

    Returns
    -------
    {
      "name": str,
      "industry": str,
      "sec_code": str,
      "health_score": int,          # 0-100
      "latest_financials": {...},   # 最新期の財務データ
      "key_ratios": {...},          # ROE, PER, 配当利回り等
      "available": bool
    }
    """
    edinet_code = resolve_edinet_code(ticker)
    if not edinet_code:
        return {"available": False}

    resp = _get(f"/companies/{edinet_code}", ttl_hours=24)
    data = resp.get("data", resp)
    if not data:
        return {"available": False}

    return {
        "available": True,
        "edinet_code": edinet_code,
        "name": data.get("name", ""),
        "industry": data.get("industry", ""),
        "sec_code": data.get("sec_code", ""),
        "health_score": data.get("credit_score") or data.get("health_score") or 0,
        "latest_financials": data.get("latest_financials", {}),
        "key_ratios": data.get("key_ratios", {}),
        "raw": data,
    }


def get_financials(ticker: str, years: int = 3, period: str = "annual") -> dict:
    """
    財務時系列データを取得する（損益計算書・貸借対照表・CF計算書）。

    Parameters
    ----------
    ticker : 銘柄コードまたは EDINET コード
    years  : 取得年数（最大6）
    period : "annual" または "quarterly"

    Returns
    -------
    {
      "available": bool,
      "years": int,
      "financials": [...],  # 各期の財務データリスト
    }
    """
    edinet_code = resolve_edinet_code(ticker)
    if not edinet_code:
        return {"available": False}

    resp = _get(
        f"/companies/{edinet_code}/financials",
        {"years": years, "period": period},
        ttl_hours=24,
    )
    data = resp.get("data", resp)
    if not data:
        return {"available": False}

    records = data if isinstance(data, list) else data.get("records", [])
    return {
        "available": bool(records),
        "edinet_code": edinet_code,
        "years": years,
        "period": period,
        "financials": records,
    }


def get_analysis(ticker: str) -> dict:
    """
    AI 生成の企業分析と財務健全性スコアを取得する。

    Returns
    -------
    {
      "available": bool,
      "health_score": int,  # 0-100
      "summary": str,
      "score_history": [...],
    }
    """
    edinet_code = resolve_edinet_code(ticker)
    if not edinet_code:
        return {"available": False}

    resp = _get(f"/companies/{edinet_code}/analysis", ttl_hours=24)
    data = resp.get("data", resp)
    if not data:
        return {"available": False}

    return {
        "available": True,
        "edinet_code": edinet_code,
        "health_score": data.get("credit_score") or data.get("health_score") or 0,
        "summary": data.get("summary", ""),
        "score_history": data.get("score_history", []),
        "raw": data,
    }


def get_text_blocks(ticker: str) -> dict:
    """
    有価証券報告書のテキストブロック（リスク・MD&A・経営方針等）を取得する。

    Returns
    -------
    {
      "available": bool,
      "blocks": [{"section": str, "text": str}, ...]
    }
    """
    edinet_code = resolve_edinet_code(ticker)
    if not edinet_code:
        return {"available": False}

    resp = _get(f"/companies/{edinet_code}/text-blocks", ttl_hours=72)
    data = resp.get("data", resp)
    if not data:
        return {"available": False}

    blocks = data if isinstance(data, list) else data.get("blocks", [])
    return {
        "available": bool(blocks),
        "edinet_code": edinet_code,
        "blocks": blocks,
    }


def get_shareholders(ticker: str) -> dict:
    """
    大量保有報告書データ（5%超保有者）を取得する。

    Returns
    -------
    {
      "available": bool,
      "shareholders": [{"name": str, "ratio": float, ...}, ...]
    }
    """
    edinet_code = resolve_edinet_code(ticker)
    if not edinet_code:
        return {"available": False}

    resp = _get(f"/companies/{edinet_code}/shareholders", ttl_hours=72)
    data = resp.get("data", resp)
    if not data:
        return {"available": False}

    holders = data if isinstance(data, list) else data.get("shareholders", [])
    return {
        "available": bool(holders),
        "edinet_code": edinet_code,
        "shareholders": holders,
    }


def get_full_company_data(ticker: str) -> dict:
    """
    企業情報・財務データ・AI分析を一括で取得する統合関数。
    日本株分析の main フロー呼び出し用。

    Returns
    -------
    {
      "available": bool,
      "company_info": {...},
      "financials": {...},
      "analysis": {...},
    }
    """
    if not _api_key():
        return {"available": False, "_reason": "EDINETDB_API_KEY not set"}

    company = get_company_info(ticker)
    if not company.get("available"):
        return {"available": False, "_reason": "company not found"}

    financials = get_financials(ticker)
    analysis = get_analysis(ticker)

    return {
        "available": True,
        "ticker": ticker,
        "company_info": company,
        "financials": financials,
        "analysis": analysis,
        "health_score": analysis.get("health_score") or company.get("health_score", 0),
        "name": company.get("name", ""),
        "industry": company.get("industry", ""),
    }
