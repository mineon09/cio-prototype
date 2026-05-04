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
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# .env ファイルから環境変数を読み込む
load_dotenv()

# SEC EDGAR API は User-Agent が必須
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "CIO-Prototype/1.0 (cio-analysis-safety@example.com)")
SEC_HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept": "application/json",
}

def _request_with_retry(url: str, max_retries: int = 3, timeout: int = 15, **kwargs) -> requests.Response:
    """HTTPリクエストをバックオフ付きで再試行する（レートリミット対策）"""
    import urllib.error
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=timeout, **kwargs)
            if resp.status_code == 429:
                delay = 2 ** attempt
                print(f"  ⚠️ SEC Rate Limit (429). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            elif resp.status_code == 403:
                # 403 Forbidden の場合も一時的なブロックの可能性があるためリトライ
                delay = 2 ** attempt
                print(f"  ⚠️ SEC Forbidden (403). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            delay = 2 ** attempt
            print(f"  ⚠️ SEC Request Failed ({e}). Retrying in {delay}s...")
            time.sleep(delay)
    raise Exception(f"Failed to fetch {url} after {max_retries} attempts.")

# Gemini / Groq（data_fetcherから借用）
try:
    from .data_fetcher import call_gemini, call_groq
except ImportError:
    def call_gemini(prompt, parse_json=False):
        print("⚠️ Gemini API 未設定（SEC定性分析スキップ）")
        return None
    def call_groq(prompt, parse_json=False):
        print("⚠️ Groq API 未設定（SEC定性分析スキップ）")
        return None, None

# Groq の無料tier TPM 制限 (~12,000 tokens) に収まる文字数の上限
# 1 token ≈ 4 chars; プロンプトのオーバーヘッド (~500 tokens) を差し引いた安全値
_GROQ_MAX_CHARS = 30_000

# セクション抽出モジュール
try:
    from .sec_parser import extract_sections as _extract_sections
    HAS_SEC_PARSER = True
except ImportError:
    HAS_SEC_PARSER = False

# SEC キャッシュ・チャンク解析（利用可能な場合のみ）
try:
    from pathlib import Path as _Path
    import sys as _sys
    _project_root = str(_Path(__file__).parent.parent)
    if _project_root not in _sys.path:
        _sys.path.insert(0, _project_root)
    from sec_cache import SecCache as _SecCache
    from sec_analyzer_patch import analyze_10k_with_groq_chunked as _chunked_groq
    from sec_analyzer_patch import inject_warning_into_prompt  # noqa: F401
    _sec_cache = _SecCache()
    HAS_SEC_CACHE = True
except ImportError:
    HAS_SEC_CACHE = False
    _sec_cache = None


def is_us_stock(ticker: str) -> bool:
    """米国株かどうかを判定する（.T/.L 等のサフィックスがなければ米国株と推定）"""
    return '.' not in ticker


def _get_cik(ticker: str) -> str | None:
    """ティッカーから CIK（Central Index Key）を逆引きする（キャッシュ付き）"""
    from pathlib import Path
    
    # ローカルキャッシュのパス（data/company_tickers.json）
    cache_path = Path(__file__).parent.parent / "data" / "company_tickers.json"
    data = None
    
    # キャッシュが存在し、24時間以内ならそれを使用
    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < 86400:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    # キャッシュがない、または古い場合はダウンロード
    if not data:
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            resp = _request_with_retry(url, headers=SEC_HEADERS, timeout=15)
            data = resp.json()
            # 取得できたら保存
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"  ⚠️ CIKリスト取得失敗: {e}")
            return None

    ticker_upper = ticker.upper().replace('.', '')
    for entry in data.values():
        if entry.get('ticker', '').upper() == ticker_upper:
            cik = str(entry['cik_str']).zfill(10)
            return cik
    return None


def _get_latest_filing(cik: str, form_type: str = "10-K") -> dict | None:
    """CIK から最新の 10-K または 10-Q のファイリング情報を取得する"""
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = _request_with_retry(url, headers=SEC_HEADERS, timeout=15)
        data = resp.json()

        entity_name = data.get('name', '')

        recent = data.get('filings', {}).get('recent', {})
        forms = recent.get('form', [])
        dates = recent.get('filingDate', [])
        accessions = recent.get('accessionNumber', [])
        primary_docs = recent.get('primaryDocument', [])
        report_dates = recent.get('reportDate', [])

        for i, form in enumerate(forms):
            if form == form_type:
                if i >= len(dates) or i >= len(accessions) or i >= len(primary_docs):
                    continue
                report_date = report_dates[i] if i < len(report_dates) else ''
                return {
                    'form': form,
                    'date': dates[i],
                    'report_date': report_date,
                    'accession': accessions[i].replace('-', ''),
                    'primary_doc': primary_docs[i],
                    'cik': cik,
                    'entity_name': entity_name,
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
        
        # Determine the correct URL. If it's an iXBRL viewer link or just the base doc,
        # we fetch the raw HTML file from EDGAR archives.
        unhyphenated_acc = acc.replace('-', '')
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{unhyphenated_acc}/{doc}"

        resp = _request_with_retry(url, headers=SEC_HEADERS, timeout=30)
        text = resp.text

        # ----------------------------------------------------------------------------
        # Bug #4 Fix:
        # If the fetched text is basically empty (e.g. 146 chars like IONQ's wrapper),
        # it might be an xml wrapper or an index page. Let's attempt to find the actual 
        # htm or txt file from the index.json of that accession.
        # ----------------------------------------------------------------------------
        if len(text) < 15000:
            print(f"  ℹ️ テキストが異常に短いです ({len(text)}文字)。直接ファイルではなくインデックスの可能性があります。実際のファイルを検索します...")
            index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{unhyphenated_acc}/index.json"
            try:
                idx_resp = _request_with_retry(index_url, headers=SEC_HEADERS, timeout=15)
                if idx_resp.status_code == 200:
                    idx_data = idx_resp.json()
                    files = idx_data.get('directory', {}).get('item', [])
                    
                    # Try to find a larger .htm or .txt file containing '10-k' or '10-q'
                    target_file = None
                    for f in files:
                        name = f.get('name', '').lower()
                        # Typically the primary document starts with the ticker or form name
                        # Since IONQ uses ionq-20251231.htm, we should just look for a large .htm file
                        # that is not an exhibit ('ex') or a graphic.
                        if name.endswith('.htm') or name.endswith('.txt'):
                            size_str = f.get('size', '0')
                            size = int(size_str) if size_str.isdigit() else 0
                            # Main reports are usually > 500KB.
                            if size > 500000 and '-ex' not in name:
                                target_file = f.get('name')
                                break
                    
                    if target_file and target_file != doc:
                        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{unhyphenated_acc}/{target_file}"
                        print(f"  🔗 代替URLで再取得中: {url}")
                        resp = _request_with_retry(url, headers=SEC_HEADERS, timeout=30)
                        text = resp.text
            except Exception as e:
                print(f"  ⚠️ 代替ファイルの検索に失敗しました: {e}")

        # Parse with BeautifulSoup instead of dangerous regex strip
        # Use lxml if available for speed and robustness with huge documents
        try:
            soup = BeautifulSoup(text, 'lxml')
        except Exception:
            soup = BeautifulSoup(text, 'html.parser')
        
        # Remove scripts, styles, and empty structures safely
        for script in soup(["script", "style", "meta", "noscript"]):
            script.decompose()

        # Get plain text separated by single spaces
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text).strip()

        # セクション抽出: Risk Factors + MD&A
        # 方式1: sec_parser を使用（TOC vs 本文を正しく区別）
        if HAS_SEC_PARSER:
            parsed = _extract_sections(text, max_total=60_000, max_1a=30_000, max_7=30_000)
            if parsed["extraction_success"] and parsed["total_chars"] > 5000:
                sections = []
                if parsed["1a"]:
                    sections.append("【Risk Factors】\n" + parsed["1a"])
                if parsed["7"]:
                    sections.append("【MD&A】\n" + parsed["7"])
                return "\n\n".join(sections)[:max_chars]

        # 方式2: フォールバック（従来の正規表現）
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

        full_sections_text = "\n\n".join(sections)
        if len(full_sections_text) > 5000:
            return full_sections_text[:max_chars]

        # セクション抽出に失敗、または短すぎる（TOC等の可能性）場合、先頭から取得
        # HTML tag stripping was so destructive that 5MB files became 166 bytes.
        # Now we safely extract and return it.
        # If text is still extremely short, it's likely a parsing failure or blank wrapper.
        if len(text) < 500:
             print("  ⚠️ テキスト抽出結果が短すぎます。タグ除去を緩和します...")
             # Regex fallback (strip tags only)
             text = re.sub(r'<[^>]+>', ' ', text)
             text = re.sub(r'\s+', ' ', text).strip()

        return text[:max_chars]

    except Exception as e:
        print(f"  ⚠️ ファイリングダウンロード失敗: {e}")
        return None


def _build_sec_analysis_prompt(text: str, ticker: str) -> str:
    """SEC解析プロンプトを生成する（テキストサイズ可変）"""
    return f"""
You are a securities analyst.
From the following SEC 10-K/10-Q filing text for {ticker}, extract key qualitative information for investment analysis.
Output MUST be in JSON format. All text values should be in Japanese.

【Extraction Items】
1. risk_top3 (list): Top 3 risks from "Risk Factors" section.
   - risk: Risk name (Japanese)
   - severity: "高" or "中" or "低"
   - detail: Details including stock price impact (Japanese)
2. moat (dict): Economic Moat assessment.
   - type: One of "ブランド", "スイッチングコスト", "ネットワーク効果", "コスト優位性", "規模の経済", "なし"
   - source: Source of competitive advantage (Japanese)
   - durability: "高" (10+ years), "中" (few years), "低" (fragile)
   - description: Detailed description (Japanese)
3. management_tone (dict): Management tone from MD&A section.
   - overall: "強気", "中立", "慎重", "弱気"
   - key_phrases: Notable keywords (list, max 3, Japanese)
   - detail: Summary of management confidence/concerns (Japanese)
4. rd_focus (list): R&D focus areas (max 3).
   - area: Area name (Japanese)
   - detail: Details (Japanese)
5. management_challenges (str): Key challenges management acknowledges (Japanese, 200 chars max).
6. summary (str): Summary of company's current state and outlook (Japanese, 200 chars max).

【Filing Text】
{text}
    """


def _analyze_sec_with_gemini(text: str, ticker: str) -> dict:
    """
    SEC 10-K/10-Q のテキストを Gemini で解析し、
    score_qualitative が期待する構造化データを返す。
    edinet_client._analyze_yuho_with_gemini と同等の出力形式。
    Gemini 失敗時は空の dict を返す（Groq フォールバックは呼び出し元で処理）。
    """
    if not text:
        return {}

    # Gemini 用: 80k文字まで（約20k tokens）
    clean_text = re.sub(r'\s+', ' ', text)[:80000]
    prompt = _build_sec_analysis_prompt(clean_text, ticker)

    print(f"  🧠 Gemini で 10-K/10-Q を解析中（テキストサイズ: {len(clean_text)//1000}k文字）...")
    response = call_gemini(prompt, parse_json=True)

    result = None
    if isinstance(response, tuple) and len(response) >= 1:
        result = response[0]
    elif response and not isinstance(response, tuple):
        result = response

    if isinstance(result, dict) and result:
        return result

    return {}


# Groq 単発解析用プロンプト（セクション抽出済みテキスト向け）
_GROQ_SINGLE_ANALYSIS_PROMPT = """\
You are a securities analyst.
From the following SEC 10-K (Risk Factors / MD&A sections) for {ticker}, \
extract key qualitative information for investment analysis.

Output MUST be in JSON format. All text values should be in Japanese.

{{
  "risk_top3": [
    {{"risk": "リスク名", "severity": "高/中/低", "detail": "株価影響を含む説明"}},
    {{"risk": "リスク名", "severity": "高/中/低", "detail": "説明"}},
    {{"risk": "リスク名", "severity": "高/中/低", "detail": "説明"}}
  ],
  "moat": {{
    "type": "ブランド/スイッチングコスト/ネットワーク効果/コスト優位性/規模の経済/なし",
    "source": "競争優位性の源泉",
    "durability": "高/中/低",
    "description": "詳細説明"
  }},
  "management_tone": {{
    "overall": "強気/中立/慎重/弱気",
    "key_phrases": ["キーフレーズ1", "キーフレーズ2", "キーフレーズ3"],
    "detail": "経営陣の自信・懸念の要約"
  }},
  "rd_focus": [
    {{"area": "分野名", "detail": "詳細"}},
    {{"area": "分野名", "detail": "詳細"}},
    {{"area": "分野名", "detail": "詳細"}}
  ],
  "management_challenges": "経営課題の要約（200文字以内）",
  "summary": "会社の現状と見通しの総括（200文字以内）"
}}

Output ONLY the JSON object. No other text.
If information is not found for a field, use empty string or empty list.

Filing text:
{text}"""


def _analyze_sec_with_groq_single(
    text: str,
    ticker: str,
    verbose: bool = True,
) -> tuple:
    """
    セクション抽出済みテキストを Groq に 1 回で送って解析する。
    チャンク分割・待機は不要。

    Returns
    -------
    (analysis_dict, meta)
    """
    clean_text = re.sub(r'\s+', ' ', text).strip()

    if verbose:
        print(f"  🚀 Groq 単発解析: {len(clean_text):,}文字...")

    prompt = _GROQ_SINGLE_ANALYSIS_PROMPT.format(ticker=ticker, text=clean_text)
    response, _ = call_groq(prompt, parse_json=True)

    result = None
    if isinstance(response, dict) and response:
        result = response
    elif isinstance(response, tuple) and len(response) >= 1:
        result = response[0] if isinstance(response[0], dict) else None

    meta = {
        "chunk_count": 1,
        "total_chars": len(clean_text),
        "truncated": False,
        "method": "section_extraction",
    }

    if result and isinstance(result, dict):
        if verbose:
            print(f"  ✅ Groq 単発解析完了")
        return result, meta

    if verbose:
        print(f"  ⚠️ Groq 単発解析: パース失敗、空の結果を返します")
    return {}, meta


def extract_sec_data(ticker: str, no_cache: bool = False) -> dict:
    """
    米国株の SEC 10-K / 10-Q を取得し、
    生テキストを返す（AI解析は最終レポート生成時に一括で行う）。
    """
    print(f"  🔍 SEC EDGAR で {ticker} を検索中...")

    # CIK 取得
    cik = _get_cik(ticker)
    if not cik:
        print(f"  ⚠️ {ticker} の CIK が見つかりません")
        return {"available": False, "reason": "CIK未検出"}

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
        return {"available": False, "reason": "最新ファイリング未検出"}

    print(f"  📄 {form_type} 取得: {filing['date']}")

    # レート制限（SEC は 10req/sec が上限）
    time.sleep(0.2)

    filing_date = filing.get('date', '')

    # テキスト取得（キャッシュ優先）
    text = None
    if HAS_SEC_CACHE and _sec_cache:
        text = _sec_cache.get_text(ticker, filing_date, no_cache=no_cache)
        if text:
            print(f"  ✅ 10-K テキストキャッシュ使用: {ticker}_{filing_date}")

    if text is None:
        text = _download_filing_text(filing)
        if HAS_SEC_CACHE and _sec_cache and text and filing_date:
            _sec_cache.save_text(ticker, filing_date, text)

    if not text:
        return {"available": False, "reason": "本文テキスト取得またはパース失敗"}

    print(f"  📝 テキスト取得: {len(text):,} 文字")

    # raw_text の選定: _download_filing_text が既にセクション抽出済みの場合はそのまま使用。
    # そうでなければ "Item 1A." を検索して Risk Factors 周辺を抽出する。
    # XBRL タクソノミ URL（"http://fasb.org/..." 等）を含む行はプロンプトへの混入を防ぐためスキップする。
    if text.startswith("【Risk Factors】") or text.startswith("【MD&A】"):
        # _download_filing_text が構造化テキストを返した場合はそのまま利用
        filing_summary = text[:10000]
    else:
        filing_text = text.replace("\n", " ")
        risk_start = filing_text.find("Item 1A.")
        if risk_start == -1:
            risk_start = filing_text.find("ITEM 1A.")
        if risk_start != -1:
            filing_summary = filing_text[risk_start:risk_start + 10000]
        else:
            filing_summary = filing_text[:10000]

    # XBRL タクソノミ URI を含む行を除去して可読性を高める
    xbrl_pattern = re.compile(r'https?://[^\s]+#\w+')
    clean_lines = [line for line in filing_summary.splitlines()
                   if not xbrl_pattern.search(line)]
    filing_summary = " ".join(clean_lines).strip()
    # 連続スペースを圧縮
    filing_summary = re.sub(r'\s{3,}', '  ', filing_summary)

    # doc_info を構築（format_yuho_for_prompt が期待するキーを含む）
    submit_date = filing.get('date', '')
    report_date = filing.get('report_date', '')
    entity_name = filing.get('entity_name', ticker.upper())
    # 期間情報: report_date があればそれを period_end に使用、なければ submit_date から推定
    if report_date:
        period_end = report_date
        # 10-K は通常12ヶ月間なので period_start は period_end の1年前
        try:
            from datetime import datetime as _dt, timedelta as _td
            pe = _dt.strptime(report_date, '%Y-%m-%d')
            period_start = (pe.replace(year=pe.year - 1) + _td(days=1)).strftime('%Y-%m-%d')
        except Exception:
            period_start = ''
    else:
        period_end = submit_date
        period_start = ''

    doc_info = {
        "form": form_type,
        "filer_name": entity_name,
        "submit_date": submit_date,
        "period_start": period_start,
        "period_end": period_end,
        "accession": filing['accession'],
        "primary_doc": filing['primary_doc'],
        "cik": filing['cik'],
    }

    # AI解析: キャッシュ確認 → Gemini → Groq セクション抽出＋単発解析フォールバック
    chunking_meta = None
    sections = {}  # HAS_SEC_PARSER が False の場合の初期値

    # Groq フォールバック用にセクション抽出済みテキストを準備
    groq_fallback_text = text
    if HAS_SEC_PARSER:
        sections = _extract_sections(text)
        if sections["extraction_success"]:
            groq_fallback_text = sections["combined"]
            print(f"  ✂️  セクション抽出成功: {sections['total_chars']:,}文字 "
                  f"(1A: {len(sections['1a']):,}文字 / 7: {len(sections['7']):,}文字)")
        else:
            groq_fallback_text = re.sub(r'\s+', ' ', text)[:20_000]
            print(f"  ⚠️  セクション抽出失敗: 先頭20,000文字にフォールバック")

    if HAS_SEC_CACHE and _sec_cache:
        cached = _sec_cache.get_analysis(ticker, filing_date, no_cache=no_cache)
        if cached:
            print(f"  ✅ 10-K 解析キャッシュ使用: {ticker}_{filing_date}")
            analysis_result = cached.get("analysis", {})
            chunking_meta = cached.get("meta")
            # section_extraction でテキストが抽出されていれば古いチャンク警告を上書き
            if sections.get("extraction_success"):
                chunking_meta = {
                    "chunk_count": 1,
                    "total_chars": sections.get("total_chars", 0),
                    "truncated": False,
                    "method": "section_extraction",
                }
        else:
            analysis_result = _analyze_sec_with_gemini(text, ticker)
            if not analysis_result:
                print(f"  🔀 Groq 単発解析にフォールバック（{len(groq_fallback_text):,}文字）...")
                analysis_result, chunking_meta = _analyze_sec_with_groq_single(
                    groq_fallback_text, ticker, verbose=True
                )
            if analysis_result and filing_date:
                _sec_cache.save_analysis(ticker, filing_date, analysis_result, chunking_meta or {})
    else:
        analysis_result = _analyze_sec_with_gemini(text, ticker)
        if not analysis_result:
            print(f"  🔀 Groq 単発解析にフォールバック（{len(groq_fallback_text):,}文字）...")
            analysis_result, chunking_meta = _analyze_sec_with_groq_single(
                groq_fallback_text, ticker, verbose=True
            )

    return {
        "available": True,
        "doc_info": doc_info,
        "raw_text": filing_summary,
        "risk_top3": analysis_result.get("risk_top3", []),
        "moat": analysis_result.get("moat", {}),
        "management_tone": analysis_result.get("management_tone", {}),
        "rd_focus": analysis_result.get("rd_focus", []),
        "management_challenges": analysis_result.get("management_challenges", ""),
        "summary": analysis_result.get("summary", "SEC 10-K/10-Q Raw Text Extracted"),
        "chunking_meta": chunking_meta,
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
