"""
sec_client.py - SEC EDGAR 10-K/10-Q 取得モジュール
====================================================
米国株の年次報告書 (10-K) / 四半期報告書 (10-Q) を SEC EDGAR から取得し、
Gemini AI で構造化データ（リスク、堀、R&D、経営陣トーン）を抽出する。

APIキー不要（SEC EDGAR は無料公開API）。
User-Agent ヘッダーに連絡先メールアドレスを設定する必要あり（SEC要件）。
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timedelta

# SEC EDGAR API は User-Agent が必須
SEC_USER_AGENT = "CIO-Prototype/1.0 (cio-analysis@example.com)"
SEC_HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept": "application/json",
}

# Gemini（data_fetcherから借用）
try:
    from data_fetcher import call_gemini
except ImportError:
    def call_gemini(prompt, parse_json=False):
        print("⚠️ Gemini API 未設定（SEC定性分析スキップ）")
        return None


def is_us_stock(ticker: str) -> bool:
    """米国株かどうかを判定する（.T/.L 等のサフィックスがなければ米国株と推定）"""
    return '.' not in ticker


def _get_cik(ticker: str) -> str | None:
    """ティッカーから CIK（Central Index Key）を逆引きする"""
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        ticker_upper = ticker.upper().replace('.', '')
        for entry in data.values():
            if entry.get('ticker', '').upper() == ticker_upper:
                cik = str(entry['cik_str']).zfill(10)
                return cik
        return None
    except Exception as e:
        print(f"  ⚠️ CIK検索失敗: {e}")
        return None


def _get_latest_filing(cik: str, form_type: str = "10-K") -> dict | None:
    """CIK から最新の 10-K または 10-Q のファイリング情報を取得する"""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        recent = data.get('filings', {}).get('recent', {})
        forms = recent.get('form', [])
        dates = recent.get('filingDate', [])
        accessions = recent.get('accessionNumber', [])
        primary_docs = recent.get('primaryDocument', [])

        for i, form in enumerate(forms):
            if form == form_type:
                return {
                    'form': form,
                    'date': dates[i],
                    'accession': accessions[i].replace('-', ''),
                    'primary_doc': primary_docs[i],
                    'cik': cik,
                }
        return None
    except Exception as e:
        print(f"  ⚠️ ファイリング検索失敗: {e}")
        return None


def _download_filing_text(filing: dict, max_chars: int = 80000) -> str | None:
    """ファイリングのHTMLからテキストを抽出する（リスクファクター + MD&A セクション）"""
    try:
        cik = filing['cik']
        acc = filing['accession']
        doc = filing['primary_doc']
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

        resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text

        # HTMLタグを除去して純粋テキストに変換
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # セクション抽出: Risk Factors + MD&A
        sections = []

        # Risk Factors
        risk_match = re.search(
            r'(Item\s*1A[.\s]*Risk\s*Factors.*?)(Item\s*1B|Item\s*2\b)',
            text, re.IGNORECASE | re.DOTALL
        )
        if risk_match:
            sections.append("【Risk Factors】\n" + risk_match.group(1)[:30000])

        # MD&A
        mda_match = re.search(
            r'(Item\s*7[.\s]*Management.*?Discussion.*?)(Item\s*7A|Item\s*8\b)',
            text, re.IGNORECASE | re.DOTALL
        )
        if mda_match:
            sections.append("【MD&A】\n" + mda_match.group(1)[:30000])

        if sections:
            return "\n\n".join(sections)[:max_chars]

        # セクション抽出に失敗した場合、先頭から取得
        return text[:max_chars]

    except Exception as e:
        print(f"  ⚠️ ファイリングダウンロード失敗: {e}")
        return None


def extract_sec_data(ticker: str) -> dict:
    """
    米国株の SEC 10-K / 10-Q を取得し、
    生テキストを返す（AI解析は最終レポート生成時に一括で行う）。
    """
    print(f"  🔍 SEC EDGAR で {ticker} を検索中...")

    # CIK 取得
    cik = _get_cik(ticker)
    if not cik:
        print(f"  ⚠️ {ticker} の CIK が見つかりません")
        return {"available": False}

    print(f"  ✅ CIK: {cik}")

    # 10-K を優先、なければ 10-Q
    filing = _get_latest_filing(cik, "10-K")
    form_type = "10-K"
    if not filing:
        print(f"  ℹ️ 10-K が見つかりません。10-Q を検索中...")
        filing = _get_latest_filing(cik, "10-Q")
        form_type = "10-Q"

    if not filing:
        print(f"  ⚠️ {ticker} のファイリングが見つかりません")
        return {"available": False}

    print(f"  📄 {form_type} 取得: {filing['date']}")

    # レート制限（SEC は 10req/sec が上限）
    time.sleep(0.2)

    # テキスト取得
    text = _download_filing_text(filing)
    if not text:
        return {"available": False}

    print(f"  📝 テキスト取得: {len(text):,} 文字")

    # 生テキストをそのまま返す（AI解析は最終レポートで一括）
    return {
        "available": True,
        "source": f"SEC EDGAR {form_type}",
        "filing_date": filing['date'],
        "raw_text": text[:8000],  # 最終プロンプトに詰める分量に制限
        "risk_top3": [],
        "moat": {},
        "rd_focus": "",
        "management_tone": "不明",
    }


# ==========================================
# テスト実行
# ==========================================
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"🧪 SEC Client テスト: {ticker}")
    result = extract_sec_data(ticker)
    print(json.dumps(result, indent=2, ensure_ascii=False))
