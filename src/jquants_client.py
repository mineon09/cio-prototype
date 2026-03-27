"""
jquants_client.py - J-Quants V2 API クライアント
=================================================
J-Quants API (api.jquants.com/v2) を使用して東証上場銘柄の
OHLC 株価データを取得する。

設計方針:
- JQUANTS_API_KEY 未設定時は空リストを返してメインフローを止めない
- .jquants_cache/ ディレクトリに TTL 付きキャッシュ（1時間）
- ティッカー変換: 7203.T → 7203 → 72030 (J-Quants は5桁コード)
- 日次OHLC エンドポイント: GET /v2/prices/daily_quotes
"""

import os
import json
import hashlib
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ─── 定数 ───────────────────────────────────────────────
BASE_URL = "https://api.jquants.com/v2"
CACHE_DIR = Path(".jquants_cache")
CACHE_DIR.mkdir(exist_ok=True)

# ─── 内部ヘルパー ────────────────────────────────────────

def _api_key() -> str:
    return os.environ.get("JQUANTS_API_KEY", "")


def _cache_path(endpoint: str, params: dict) -> Path:
    key = json.dumps({"ep": endpoint, "p": params}, sort_keys=True)
    hsh = hashlib.md5(key.encode()).hexdigest()[:12]
    safe = endpoint.replace("/", "_").strip("_")
    return CACHE_DIR / f"{safe}_{hsh}.json"


def _load_cache(path: Path, ttl_hours: float) -> Optional[list]:
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


def _save_cache(path: Path, data) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get(endpoint: str, params: dict, ttl_hours: float = 1.0) -> dict:
    """
    J-Quants V2 API に GET リクエストを送る。

    Returns
    -------
    API レスポンスの dict。失敗時は {}
    """
    if not _api_key():
        return {}

    cache = _cache_path(endpoint, params)
    cached = _load_cache(cache, ttl_hours)
    if cached is not None:
        return cached

    url = f"{BASE_URL}{endpoint}"
    try:
        resp = requests.get(
            url,
            headers={"x-api-key": _api_key()},
            params={k: v for k, v in params.items() if v is not None},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _save_cache(cache, data)
        return data
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status == 403:
            print(
                f"  ⚠️ [J-Quants] プランの制限により株価データを取得できません。"
                f"Free プランでは {endpoint} は利用不可です。yfinance にフォールバックします。"
            )
        else:
            print(f"  ⚠️ [J-Quants] HTTP エラー {endpoint}: {e}")
        return {}
    except Exception as e:
        print(f"  ⚠️ [J-Quants] リクエスト失敗 {endpoint}: {e}")
        return {}


# ─── ティッカー変換 ──────────────────────────────────────

def to_jquants_code(ticker: str) -> str:
    """
    ティッカーを J-Quants 5桁コードに変換する。

    7203.T → 7203 → 72030
    72030  → 72030 (そのまま)
    7203   → 72030

    Parameters
    ----------
    ticker : 例 "7203.T", "7203", "72030"

    Returns
    -------
    5桁文字列（例: "72030"）
    """
    # .T / .TYO などのサフィックスを除去
    base = ticker.split(".")[0]
    # 数字のみに絞る
    digits = "".join(c for c in base if c.isdigit())

    if len(digits) == 5:
        return digits
    if len(digits) == 4:
        return digits + "0"
    # それ以外はそのまま返す（企業名など）
    return digits


# ─── 公開 API ────────────────────────────────────────────

def get_stock_price(
    ticker: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> list:
    """
    J-Quants V2 から日次 OHLC を取得する。

    Parameters
    ----------
    ticker    : 銘柄コード（例: "7203.T", "7203", "72030"）
    from_date : 開始日（YYYY-MM-DD）。省略時は直近1件
    to_date   : 終了日（YYYY-MM-DD）。省略時は最新まで

    Returns
    -------
    [
      {
        "date": "YYYY-MM-DD",
        "open":   float,
        "high":   float,
        "low":    float,
        "close":  float,
        "volume": float,
      },
      ...
    ]
    失敗時は []
    """
    if not _api_key():
        return []

    code = to_jquants_code(ticker)
    params = {
        "code": code,
        "from": from_date,
        "to": to_date,
    }

    resp = _get("/prices/daily_quotes", params, ttl_hours=1.0)
    bars = resp.get("daily_quotes", [])

    if not bars:
        return []

    # J-Quants V2 /prices/daily_quotes のフィールド:
    # AdjustmentClose / AdjustmentOpen / AdjustmentHigh / AdjustmentLow / AdjustmentVolume
    # 調整前は Close / Open / High / Low / Volume
    result = []
    for bar in bars:
        open_  = bar.get("AdjustmentOpen")  or bar.get("Open")  or 0
        high   = bar.get("AdjustmentHigh")  or bar.get("High")  or 0
        low    = bar.get("AdjustmentLow")   or bar.get("Low")   or 0
        close  = bar.get("AdjustmentClose") or bar.get("Close") or 0
        volume = bar.get("AdjustmentVolume") or bar.get("Volume") or 0

        raw_date = bar.get("Date") or bar.get("date") or ""
        # "20240101" → "2024-01-01"
        if len(raw_date) == 8 and raw_date.isdigit():
            raw_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

        result.append({
            "date":   raw_date,
            "open":   float(open_),
            "high":   float(high),
            "low":    float(low),
            "close":  float(close),
            "volume": float(volume),
        })

    return result


def get_latest_price(ticker: str) -> dict:
    """
    最新の終値・出来高を1件取得する。

    Returns
    -------
    {"date": str, "open": float, "high": float, "low": float, "close": float, "volume": float}
    失敗時は {}
    """
    bars = get_stock_price(ticker)
    if not bars:
        return {}
    return bars[-1]


def get_price_history(ticker: str, days: int = 60) -> list:
    """
    直近 N 日間の OHLC を取得する。

    Parameters
    ----------
    ticker : 銘柄コード
    days   : 取得日数（デフォルト60日）

    Returns
    -------
    日次 OHLC リスト（古い順）
    """
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date   = datetime.now().strftime("%Y-%m-%d")
    return get_stock_price(ticker, from_date=from_date, to_date=to_date)
