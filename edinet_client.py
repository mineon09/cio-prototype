"""
edinet_client.py - EDINET API v2 有価証券報告書取得モジュール
================================================================
日本株（.T サフィックス）のティッカーから EDINET API v2 を通じて
最新の有価証券報告書（有報）を検索・取得し、Gemini で要約する。

改善点:
  - 金融庁 EDINETコードリストCSV によるマッピング対応
  - 検索期間 400日（年次有報の年1回発行に対応）
  - 経営陣トーン分析をGeminiプロンプトに追加

API キー未設定・取得失敗時は空辞書を返し、メインフローを中断しない。
"""

import os, re, json, time, csv, io, zipfile
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

EDINET_API_KEY = os.environ.get('EDINET_API_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

EDINET_BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"

# 有報の docTypeCode
DOC_TYPE_YUHO          = "120"   # 有価証券報告書
DOC_TYPE_QUARTERLY     = "140"   # 四半期報告書

# EDINETコードリストのキャッシュパス
_CACHE_DIR = Path(__file__).parent / ".edinet_cache"
_CODE_LIST_PATH = _CACHE_DIR / "edinet_code_list.csv"

try:
    with open("config.json", encoding="utf-8") as f:
        _CFG = json.load(f)
except Exception:
    _CFG = {}

EDINET_CFG = _CFG.get("edinet", {
    "search_days": 400,
    "doc_type_code": "120",
    "target_sections": ["事業等のリスク", "経営方針、経営環境及び対処すべき課題等", "研究開発活動"],
})


# ==========================================
# EDINETコードリスト管理
# ==========================================

_edinet_code_map: dict | None = None  # secCode(5桁) → edinetCode マッピング


def _download_edinet_code_list() -> bool:
    """
    EDINET API v2 からEDINETコードリスト（ZIP→CSV）をダウンロードしてキャッシュ。
    エンドポイント: GET /api/v2/EdinetcodeDlInfo.json?type=2
    """
    if not EDINET_API_KEY:
        return False

    url = f"{EDINET_BASE_URL}/EdinetcodeDlInfo.json"
    params = {"type": 2, "Subscription-Key": EDINET_API_KEY}

    try:
        print("  📋 EDINETコードリストをダウンロード中...")
        # リダイレクトループを避けるため allow_redirects=True (デフォルト) を明示しつつ、
        # エラー発生時は即座にスキップするようにする
        resp = requests.get(url, params=params, timeout=30, allow_redirects=True)
        
        if resp.status_code != 200:
            print(f"  ⚠️ コードリスト取得スキップ (status={resp.status_code})")
            return False

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # レスポンスはZIPファイル
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            # ZIP内のCSVファイルを探す
            csv_names = [n for n in zf.namelist() if n.endswith('.csv')]
            if not csv_names:
                print("  ⚠️ ZIP内にCSVが見つかりません")
                return False

            with zf.open(csv_names[0]) as csv_file:
                content = csv_file.read()
                _CODE_LIST_PATH.write_bytes(content)

        print(f"  ✅ EDINETコードリスト保存完了 ({_CODE_LIST_PATH.name})")
        return True

    except Exception as e:
        print(f"  ⚠️ コードリストダウンロードエラー: {e}")
        return False


def _load_edinet_code_map() -> dict:
    """
    キャッシュされたCSVから secCode → edinetCode のマッピングを構築。
    CSVが古い場合（30日以上）or 存在しない場合はダウンロードを試行。
    """
    global _edinet_code_map
    if _edinet_code_map is not None:
        return _edinet_code_map

    # キャッシュが古いか存在しない場合は再ダウンロード
    need_download = True
    if _CODE_LIST_PATH.exists():
        age = time.time() - _CODE_LIST_PATH.stat().st_mtime
        if age < 30 * 24 * 3600:  # 30日以内
            need_download = False

    if need_download:
        _download_edinet_code_list()

    _edinet_code_map = {}
    if not _CODE_LIST_PATH.exists():
        return _edinet_code_map

    try:
        raw = _CODE_LIST_PATH.read_bytes()
        # BOM付きUTF-8やShift_JISの両方に対応
        for encoding in ['utf-8-sig', 'cp932', 'utf-8']:
            try:
                text = raw.decode(encoding)
                break
            except (UnicodeDecodeError, ValueError):
                continue
        else:
            return _edinet_code_map

        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            sec_code = row.get('証券コード', '').strip()
            edinet_code = row.get('ＥＤＩＮＥＴコード', row.get('EDINETコード', '')).strip()
            if sec_code and edinet_code:
                _edinet_code_map[sec_code] = edinet_code

        print(f"  📋 EDINETコードマッピング読込: {len(_edinet_code_map)}社")
    except Exception as e:
        print(f"  ⚠️ コードリスト読込エラー: {e}")

    return _edinet_code_map


def get_edinet_code(sec_code: str) -> str | None:
    """secCode (5桁) から EDINETコード (例: E02144) を取得"""
    code_map = _load_edinet_code_map()
    return code_map.get(sec_code)


# ==========================================
# ティッカー → secCode 変換
# ==========================================

def is_japanese_stock(ticker: str) -> bool:
    """ティッカーが日本株（.T サフィックス）かどうかを判定"""
    return ticker.upper().endswith('.T')


def ticker_to_sec_code(ticker: str) -> str | None:
    """
    yfinance のティッカー（例: "7203.T"）を EDINET の secCode（5桁）に変換。
    EDINET secCode は証券コード4桁 + チェックディジット "0" の5桁。
    """
    if not is_japanese_stock(ticker):
        return None
    code = ticker.replace('.T', '').strip()
    if not code.isdigit() or len(code) != 4:
        return None
    return code + "0"


# ==========================================
# 書類一覧 API — 最新有報の検索
# ==========================================

def find_latest_yuho(sec_code: str, search_days: int | None = None) -> dict | None:
    """
    EDINET 書類一覧 API を日付を遡りながら検索し、
    指定 secCode の最新有価証券報告書のメタデータを返す。

    検索戦略:
      1. EDINETコードリストで edinetCode を取得し、secCode + edinetCode の両方で照合
      2. docTypeCode=120（有報）を最優先、見つからなければ 140（四半期）にフォールバック
      3. 検索範囲はデフォルト400日（年次有報の年1回発行に対応）
      4. 土日はEDINETに提出がないためスキップ（API呼び出し約30%削減）
    """
    if not EDINET_API_KEY:
        print("  ⚠️ EDINET_API_KEY 未設定 — 有報取得をスキップ")
        return None

    days = search_days or EDINET_CFG.get("search_days", 400)
    edinet_code = get_edinet_code(sec_code)
    if edinet_code:
        print(f"  🔗 EDINETコード: {edinet_code} (secCode: {sec_code})")

    # Phase 1: 有報（120）を最優先で検索
    # Phase 2: 見つからなければ四半期報告書（140）にフォールバック
    for doc_type in [DOC_TYPE_YUHO, DOC_TYPE_QUARTERLY]:
        doc_label = "有報" if doc_type == DOC_TYPE_YUHO else "四半期報告書"
        print(f"  🔍 {doc_label}(docTypeCode={doc_type})を検索中...")

        today = datetime.now()
        api_calls = 0
        for offset in range(days):
            target = today - timedelta(days=offset)

            # 土日はEDINETに提出がないためスキップ
            if target.weekday() >= 5:  # 5=土, 6=日
                continue

            target_date = target.strftime("%Y-%m-%d")
            url = f"{EDINET_BASE_URL}/documents.json"
            params = {
                "date": target_date,
                "type": 2,  # メタデータ付き
                "Subscription-Key": EDINET_API_KEY,
            }

            try:
                resp = requests.get(url, params=params, timeout=30)
                api_calls += 1

                if resp.status_code == 429:
                    print(f"  ⏳ EDINET レート制限 — 30秒待機...")
                    time.sleep(30)
                    continue
                if resp.status_code != 200:
                    continue

                data = resp.json()
                results = data.get("results", [])

                for doc in results:
                    if doc.get("docTypeCode") != doc_type:
                        continue

                    # secCode または edinetCode でマッチ
                    match = False
                    if doc.get("secCode") == sec_code:
                        match = True
                    elif edinet_code and doc.get("edinetCode") == edinet_code:
                        match = True

                    if match:
                        print(f"  📄 {doc_label}発見: {doc.get('filerName', '不明')} "
                              f"({doc.get('docDescription', '')}) [{target_date}]")
                        return {
                            "doc_id":          doc.get("docID"),
                            "edinet_code":     doc.get("edinetCode", ""),
                            "filer_name":      doc.get("filerName", ""),
                            "doc_description": doc.get("docDescription", ""),
                            "doc_type_code":   doc_type,
                            "submit_date":     doc.get("submitDateTime", target_date),
                            "period_start":    doc.get("periodStart", ""),
                            "period_end":      doc.get("periodEnd", ""),
                        }

            except requests.RequestException as e:
                print(f"  ⚠️ EDINET API エラー ({target_date}): {e}")
                continue

            # レート制限対策: 5回ごとに1秒スリープ
            if api_calls % 5 == 0:
                time.sleep(1)

            # 進捗表示: 50回ごと
            if api_calls % 50 == 0:
                print(f"    ... {api_calls} 日分検索済み")

        # 有報が見つからなかった場合のみ四半期報告書にフォールバック
        if doc_type == DOC_TYPE_YUHO:
            print(f"  ⚠️ 有報が直近{days}日に見つからず、四半期報告書を検索...")

    print(f"  ⚠️ secCode={sec_code} の書類が直近{days}日に見つかりませんでした")
    return None


# ==========================================
# 書類取得 API — PDF ダウンロード
# ==========================================

def download_yuho_pdf(doc_id: str) -> bytes | None:
    """指定 docID の有報を PDF 形式でダウンロードし、バイナリを返す。"""
    if not EDINET_API_KEY or not doc_id:
        return None

    url = f"{EDINET_BASE_URL}/documents/{doc_id}"
    params = {
        "type": 2,  # PDF
        "Subscription-Key": EDINET_API_KEY,
    }

    try:
        print(f"  📥 有報 PDF ダウンロード中 (docID: {doc_id})...")
        resp = requests.get(url, params=params, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 1000:
            print(f"  ✅ PDF取得成功 ({len(resp.content) / 1024:.0f} KB)")
            return resp.content
        else:
            print(f"  ⚠️ PDF取得失敗 (status={resp.status_code}, size={len(resp.content)})")
            return None
    except requests.RequestException as e:
        print(f"  ⚠️ PDF ダウンロードエラー: {e}")
        return None


# ==========================================
# Gemini による有報テキスト解析
# ==========================================

def analyze_yuho_with_gemini(pdf_bytes: bytes, company_name: str) -> dict:
    """
    2段階パイプラインで有報を解析する。
    Stage 1 (Flash): PDF → 要約テキスト（トークン圧縮）
    Stage 2 (Pro):   要約テキスト → 構造化JSON
    """
    if not GEMINI_API_KEY or not pdf_bytes:
        return {}

    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)

        # PDF を Gemini にアップロード
        uploaded_file = client.files.upload(
            file=pdf_bytes,
            config={
                "display_name": f"{company_name}_yuho.pdf",
                "mime_type": "application/pdf",
            }
        )

        target_sections = EDINET_CFG.get("target_sections", [
            "事業等のリスク",
            "経営方針、経営環境及び対処すべき課題等",
            "研究開発活動",
        ])
        sections_str = "」「".join(target_sections)

        # ── Stage 1: Flash で PDF を要約 ──
        summarize_prompt = f"""
添付された有価証券報告書（{company_name}）を読み、投資判断に重要な情報を要約してください。

【重点セクション】「{sections_str}」

【要約項目】
1. 主要リスク上位3つ（リスク名、深刻度、具体的内容を含めて）
2. 競争優位性（堀）の種類と源泉（特許件数、顧客数など数値を含めて）
3. 経営陣のトーン（リスク説明が防御的か攻めかを分析）
4. R&D注力分野
5. 経営陣が認識する最重要課題

3000文字以内の日本語で要約してください。数値や固有名詞は省略せず含めてください。
"""
        print(f"  ⚡ Flash で有報要約中...")
        res = client.models.generate_content(
            model='gemini-2.5-flash-preview-05-20',
            contents=[uploaded_file, summarize_prompt],
        )
        summary = res.text

        if not summary or len(summary) < 100:
            print(f"  ⚠️ Flash 要約失敗")
            return {}

        print(f"  ✅ Flash 要約完了 ({len(summary):,}文字)")

        # ── Stage 2: Pro で構造化分析 ──
        analysis_prompt = f"""
あなたはモルガン・スタンレーのシニア証券アナリストです。
以下は {company_name} の有価証券報告書の要約です。
この要約から以下のJSON形式で情報を構造化してください。

{summary}

【出力形式（JSON厳守）】
{{
  "risk_top3": [
    {{"risk": "リスク名", "detail": "具体的内容（1-2文）", "severity": "高/中/低"}},
    {{"risk": "リスク名", "detail": "具体的内容（1-2文）", "severity": "高/中/低"}},
    {{"risk": "リスク名", "detail": "具体的内容（1-2文）", "severity": "高/中/低"}}
  ],
  "moat": {{
    "type": "ブランド/特許/技術/ネットワーク効果/コスト優位/スイッチングコスト/規制障壁",
    "source": "堀の源泉となる具体的な資産・能力（数値を含めて）",
    "description": "競争優位性の具体的説明（2-3文）",
    "durability": "高/中/低"
  }},
  "management_tone": {{
    "overall": "強気/中立/慎重/弱気",
    "detail": "経営陣の姿勢の根拠（2-3文）",
    "key_phrases": ["注目すべきキーフレーズ（最大3つ）"]
  }},
  "rd_focus": [
    {{"area": "研究分野", "detail": "具体的内容（1文）"}}
  ],
  "management_challenges": "経営陣が認識する最重要課題（2-3文）",
  "summary": "投資判断上の重要ポイント（3-4文）"
}}

【注意】
- 要約に記載がない項目は推測せず "データなし" と記載すること
- JSONのみを返答すること
"""

        from data_fetcher import call_gemini
        print(f"  🧠 Pro で構造化分析中...")
        result = call_gemini(analysis_prompt, parse_json=True, model="pro")

        if result:
            print(f"  ✅ 有報解析完了 — リスク{len(result.get('risk_top3', []))}件抽出"
                  f", トーン: {result.get('management_tone', {}).get('overall', '?')}")
            return result
        else:
            print(f"  ⚠️ Pro 解析失敗")
            return {"summary": summary[:500]}

    except Exception as e:
        print(f"  ⚠️ 有報 Gemini 解析エラー: {e}")
        return {}


# ==========================================
# 統合関数: ティッカーから有報データを取得
# ==========================================

def extract_yuho_data(ticker: str) -> dict:
    """
    メインフローから呼ばれるエントリーポイント。
    日本株ティッカーから有報を取得・解析し、構造化データを返す。
    非日本株やエラー時は空辞書を返す。

    Returns:
        dict: {
            "available": bool,
            "doc_info": {...},          # EDINET メタデータ
            "risk_top3": [...],          # 経営リスクTOP3
            "moat": {...},               # 競争優位性（堀）
            "management_tone": {...},    # 経営陣のトーン分析
            "rd_focus": [...],           # R&D 注力分野
            "management_challenges": str,
            "summary": str,
        }
    """
    if not is_japanese_stock(ticker):
        return {"available": False, "reason": "非日本株のためEDINET対象外"}

    if not EDINET_API_KEY:
        return {"available": False, "reason": "EDINET_API_KEY未設定"}

    sec_code = ticker_to_sec_code(ticker)
    if not sec_code:
        return {"available": False, "reason": "証券コード変換失敗"}

    print(f"  📋 EDINET 有報検索中 (secCode: {sec_code})...")

    # Step 1: 最新有報を検索
    doc_info = find_latest_yuho(sec_code)
    if not doc_info:
        return {"available": False, "reason": "有報が見つからない"}

    # Step 2: PDF をダウンロード
    pdf_bytes = download_yuho_pdf(doc_info["doc_id"])
    if not pdf_bytes:
        return {
            "available": False,
            "reason": "PDFダウンロード失敗",
            "doc_info": doc_info,
        }

    # Step 3: Gemini で解析
    company_name = doc_info.get("filer_name", ticker)
    analysis = analyze_yuho_with_gemini(pdf_bytes, company_name)

    if not analysis:
        return {
            "available": False,
            "reason": "Gemini解析失敗",
            "doc_info": doc_info,
        }

    return {
        "available": True,
        "doc_info": doc_info,
        **analysis,
    }


# ==========================================
# セルフテスト
# ==========================================

if __name__ == "__main__":
    print("=== edinet_client.py セルフテスト ===\n")

    # テスト 1: ティッカー変換
    tests = [
        ("7203.T", "72030"),
        ("8306.T", "83060"),
        ("AAPL",    None),
        ("MSFT",    None),
    ]
    for ticker, expected in tests:
        result = ticker_to_sec_code(ticker)
        status = "✅" if result == expected else "❌"
        print(f"  {status} ticker_to_sec_code('{ticker}') = {result} (期待値: {expected})")

    # テスト 2: 日本株判定
    print()
    for ticker, expected in [("7203.T", True), ("AAPL", False), ("9984.T", True)]:
        result = is_japanese_stock(ticker)
        status = "✅" if result == expected else "❌"
        print(f"  {status} is_japanese_stock('{ticker}') = {result}")

    # テスト 3: API キー確認
    print(f"\n  EDINET_API_KEY: {'設定済み' if EDINET_API_KEY else '未設定'}")
    print(f"  GEMINI_API_KEY: {'設定済み' if GEMINI_API_KEY else '未設定'}")

    # テスト 4: EDINETコードマッピング
    if EDINET_API_KEY:
        code_map = _load_edinet_code_map()
        toyota_code = get_edinet_code("72030")
        print(f"\n  EDINETコードマッピング: {len(code_map)}社読込")
        print(f"  トヨタ(72030) → {toyota_code or '未マッチ'}")

    # テスト 5: フォールバック（APIキーなし）
    print()
    result = extract_yuho_data("AAPL")
    print(f"  extract_yuho_data('AAPL') => available={result.get('available')}, "
          f"reason={result.get('reason')}")

    if not EDINET_API_KEY:
        result = extract_yuho_data("7203.T")
        print(f"  extract_yuho_data('7203.T') => available={result.get('available')}, "
              f"reason={result.get('reason')}")
    else:
        print("\n  🔑 APIキー検出 — 7203.T (トヨタ) で実データテストを実行")
        result = extract_yuho_data("7203.T")
        print(f"\n  結果: available={result.get('available')}")
        if result.get("risk_top3"):
            for i, r in enumerate(result["risk_top3"], 1):
                print(f"    リスク{i}: {r.get('risk', 'N/A')} [{r.get('severity', '?')}]")
        if result.get("moat"):
            print(f"    堀: {result['moat'].get('type', 'N/A')} "
                  f"(源泉: {result['moat'].get('source', 'N/A')}, "
                  f"耐久性: {result['moat'].get('durability', '?')})")
        if result.get("management_tone"):
            tone = result["management_tone"]
            print(f"    経営陣トーン: {tone.get('overall', '?')}")
            print(f"    キーフレーズ: {tone.get('key_phrases', [])}")

    print("\n=== テスト完了 ===")
