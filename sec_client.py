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


def _analyze_with_gemini(filing_text: str, ticker: str, form_type: str) -> dict:
    """
    2段階パイプラインで 10-K/10-Q を解析する。
    Stage 1 (Flash): 生テキスト → 要約（トークン圧縮）
    Stage 2 (Pro):   要約 → 構造化JSON
    """
    # ── Stage 1: Flash で要約（40K → ~3K chars） ──
    summarize_prompt = f"""
以下は {ticker} の {form_type} レポートからの抜粋です。
証券アナリストの視点で、投資判断に重要な情報を日本語で簡潔に要約してください。

【要約対象】
- 主要リスク（上位3つ）
- 競争優位性（堀：ブランド/特許/ネットワーク効果等）
- R&D注力分野
- 経営陣のトーン（強気/慎重など）

{filing_text[:40000]}

3000文字以内で要約してください。
"""
    print(f"  ⚡ [SEC] Flash で {form_type} を要約中...")
    summary = call_gemini(summarize_prompt, model="flash")
    if not summary:
        print(f"  ⚠️ Flash 要約失敗、直接 Pro で解析します")
        summary = filing_text[:15000]

    # ── Stage 2: Pro で構造化分析 ──
    analysis_prompt = f"""
あなたは米国株の証券アナリストです。以下は {ticker} の {form_type} レポートの要約です。
この要約を分析して、以下のJSON形式で情報を構造化してください。

{summary}

【出力JSON形式（厳守）】
{{
  "risk_top3": [
    {{"risk": "リスク名（日本語）", "detail": "影響と具体的な根拠（日本語）", "severity": "高/中/低"}},
    {{"risk": "リスク名", "detail": "影響", "severity": "高/中/低"}},
    {{"risk": "リスク名", "detail": "影響", "severity": "高/中/低"}}
  ],
  "moat": {{
    "type": "堀の種類（日本語: ブランド力 / ネットワーク効果 / コスト優位性 / スイッチングコスト / 特許・知的財産 / 規模の経済性）",
    "durability": "高/中/低",
    "source": "堀の源泉（日本語）",
    "description": "堀の根拠（日本語、具体的に）"
  }},
  "rd_focus": [
    {{"area": "R&D注力分野1（日本語）", "detail": "詳細"}},
    {{"area": "R&D注力分野2（日本語）", "detail": "詳細"}}
  ],
  "management_tone": {{
    "overall": "強気/中立/慎重/弱気",
    "detail": "経営陣のトーンの根拠（日本語）",
    "key_phrases": ["キーフレーズ1", "キーフレーズ2"]
  }}
}}

JSONのみ返答してください。
"""
    print(f"  🧠 [SEC] Pro で構造化分析中...")
    result = call_gemini(analysis_prompt, parse_json=True, model="pro")
    if not result:
        return {}
    
    # データ形式の正規化（analyzers.py が期待する形式に合わせる）
    mt = result.get("management_tone", {})
    if isinstance(mt, str):
        result["management_tone"] = {"overall": mt, "detail": "", "key_phrases": []}
    
    rd = result.get("rd_focus", [])
    if isinstance(rd, str):
        result["rd_focus"] = [{"area": rd, "detail": ""}]
    
    moat = result.get("moat", {})
    if isinstance(moat, str):
        result["moat"] = {"type": moat, "durability": "中", "source": "", "description": ""}
    
    return result


def extract_sec_data(ticker: str) -> dict:
    """
    米国株の SEC 10-K / 10-Q を取得・解析し、
    EDINET の yuho_data と同じ形式で返す。
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

    # Gemini で解析
    analysis = _analyze_with_gemini(text, ticker, form_type)

    return {
        "available": True,
        "source": f"SEC EDGAR {form_type}",
        "filing_date": filing['date'],
        "risk_top3": analysis.get("risk_top3", []),
        "moat": analysis.get("moat", {}),
        "rd_focus": analysis.get("rd_focus", ""),
        "management_tone": analysis.get("management_tone", "不明"),
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
