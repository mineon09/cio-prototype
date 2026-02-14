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
from pdfminer.high_level import extract_text
from io import BytesIO

# 循環インポート回避のため関数内でインポートするか、data_fetcher側でedinet_clientを使わない構成にする
# 今回は edinet_client -> data_fetcher (call_gemini) の依存のみとする
import data_fetcher

load_dotenv()

def _get_edinet_key():
    return os.environ.get('EDINET_API_KEY', '')

EDINET_BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"

# 有報の docTypeCode
DOC_TYPE_YUHO          = "120"   # 有価証券報告書
DOC_TYPE_QUARTERLY     = "140"   # 四半期報告書

# EDINETコードリストのキャッシュパス
_CACHE_DIR = Path(__file__).parent / ".edinet_cache"
_CODE_LIST_PATH = _CACHE_DIR / "edinet_code_list.csv"
_LIST_CACHE_DIR = _CACHE_DIR / "lists"

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
    if not _get_edinet_key():
        return False

    url = f"{EDINET_BASE_URL}/EdinetcodeDlInfo.json"
    params = {"type": 2, "Subscription-Key": _get_edinet_key()}

    session = requests.Session()
    session.max_redirects = 5  # リダイレクトループ防止

    for attempt in range(2):
        try:
            print("  📋 EDINETコードリストをダウンロード中...")
            resp = session.get(url, params=params, timeout=30)
            
            if resp.status_code == 429:
                print(f"  ⏳ EDINET レート制限 (DL) — 65秒待機... ({attempt+1}/2)")
                time.sleep(65)
                continue

            if resp.status_code != 200:
                print(f"  ⚠️ コードリスト取得スキップ (status={resp.status_code})")
                return False

            _CACHE_DIR.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_names = [n for n in zf.namelist() if n.endswith('.csv')]
                if not csv_names:
                    print("  ⚠️ ZIP内にCSVが見つかりません")
                    return False

                with zf.open(csv_names[0]) as csv_file:
                    content = csv_file.read()
                    _CODE_LIST_PATH.write_bytes(content)

            print(f"  ✅ EDINETコードリスト保存完了 ({_CODE_LIST_PATH.name})")
            return True

        except requests.TooManyRedirects:
            print("  ⚠️ コードリスト取得: リダイレクトループ — スキップ（secCodeで照合します）")
            return False
        except Exception as e:
            print(f"  ⚠️ コードリストダウンロードエラー: {e}")
            if attempt < 1:
                time.sleep(5)
                continue
            return False
    return False


def _get_edinet_metadata(target_date: str) -> list:
    """
    書類一覧 API を叩く。キャッシュがあればそれを返し、なければ取得してキャッシュする。
    """
    _LIST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _LIST_CACHE_DIR / f"list_{target_date}.json"

    # 1. キャッシュチェック
    if cache_path.exists():
        try:
            # 24時間以内のキャッシュなら再利用
            age = time.time() - cache_path.stat().st_mtime
            if age < 24 * 3600:
                print(f"    📦 キャッシュヒット: {target_date}")
                return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 2. API 呼び出し
    url = f"{EDINET_BASE_URL}/documents.json"
    params = {
        "date": target_date,
        "type": 2,  # メタデータ付き
        "Subscription-Key": _get_edinet_key(),
    }

    for attempt in range(2):
        try:
            # EDINET API v2 は 30回/分（平均2秒に1回）の制限があるため、
            # 安全のためリクエスト前に2秒待機
            time.sleep(2.0)
            
            resp = requests.get(url, params=params, timeout=30)
            
            if resp.status_code == 429:
                print(f"    ⏳ EDINET レート制限 (List) — 65秒待機... ({attempt+1}/2)")
                time.sleep(65)
                continue

            if resp.status_code != 200:
                return []

            data = resp.json()
            results = data.get("results", [])

            # キャッシュ保存
            if results:
                cache_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
                
            return results

        except Exception as e:
            print(f"    ⚠️ API エラー ({target_date}): {e}")
            if attempt < 1:
                time.sleep(5)
                continue
            break
            
    return []


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
    if not _get_edinet_key():
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
        api_count = 0
        for offset in range(days):
            target = today - timedelta(days=offset)

            # 土日はEDINETに提出がないためスキップ
            if target.weekday() >= 5:  # 5=土, 6=日
                continue

            target_date = target.strftime("%Y-%m-%d")
            results = _get_edinet_metadata(target_date)
            api_count += 1

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

            # 進捗表示: 50回ごと
            if api_count % 50 == 0:
                print(f"    ... {api_count} 日分検索済み")

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
    if not _get_edinet_key() or not doc_id:
        title = "doc_id不明"
        return None

    url = f"{EDINET_BASE_URL}/documents/{doc_id}"
    params = {
        "type": 2,  # 2=PDF
        "Subscription-Key": _get_edinet_key(),
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
# 有報データ（AI解析）
# ==========================================

def _extract_text_from_pdf_bytes(pdf_bytes: bytes, max_pages: int = 50) -> str:
    """
    pdfminer.six を使用してPDFバイナリからテキストを抽出する。
    処理時間短縮のため、max_pages でページ数を制限可能（デフォルト50ページ）。
    """
    try:
        # PDF全体のテキスト抽出（maxpages=0 は全ページ）
        # 有報は数百ページになることがあるため、冒頭〜重要部分が含まれる範囲に限定してもよいが、
        # "事業等のリスク"などは後半にあることもあるため、一旦全ページ取得を試みる。
        # ただしタイムアウト回避のため max_pages を設ける検討も必要。
        # ここでは重要なセクションが散らばっているため、全ページ取得を試みるが、
        # パフォーマンスを考慮し、一旦 max_pages=0 (全ページ) とする。
        text = extract_text(BytesIO(pdf_bytes), maxpages=0)
        return text
    except Exception as e:
        print(f"  ⚠️ PDFテキスト抽出エラー: {e}")
        return ""

def _analyze_yuho_with_gemini(text: str, filer_name: str) -> dict:
    """
    抽出した有報テキストをGeminiに投げ、リスク・堀・経営課題などを抽出する。
    """
    if not text:
        return {}

    # トークン数削減のため、不要な空白や改行を圧縮
    clean_text = re.sub(r'\s+', ' ', text)[:80000] # Gemini 1.5/Proなら長文OKだが、念のため安全圏に

    prompt = f"""
あなたは証券アナリストです。
以下の有価証券報告書（{filer_name}）のテキストから、投資判断に必要な定性情報を抽出してください。
出力は必ず JSON 形式にしてください。

【抽出項目】
1. risk_top3 (list): 「事業等のリスク」などから、特に影響度が大きく、解決困難なリスクを3つ。
   - risk: リスク名
   - severity: "高" or "中" or "低"
   - detail: 詳細（株価への影響含む）
2. moat (dict): 企業の競争優位性（Economic Moat）。
   - type: "ブランド", "スイッチングコスト", "ネットワーク効果", "コスト優位性", "規模の経済", "なし" のいずれか
   - source: 優位性の源泉（具体的な技術や資産）
   - durability: "高" (10年以上), "中" (数年), "低" (すぐ崩れる)
   - description: 詳細説明
3. management_tone (dict): 経営陣のトーン分析（「経営方針」「対処すべき課題」などの記述から）。
   - overall: "強気", "中立", "慎重", "弱気"
   - key_phrases: 印象的なキーワード（リスト, 最大3つ）
   - detail: 経営陣の自信や懸念点の要約
4. rd_focus (list): 研究開発活動の注力分野（最大3つ）。
   - area: 分野名
   - detail: 詳細
5. management_challenges (str): 経営者が認識している課題（「対処すべき課題」から要約）。
6. summary (str): この有報から読み取れる企業の現状と将来性の要約（200文字以内）。

【テキスト】
{clean_text}
    """
    
    print(f"  🧠 Gemini で有報を解析中（テキストサイズ: {len(clean_text)//1000}k文字）...")
    result = data_fetcher.call_gemini(prompt, parse_json=True, model="flash") # 高速化のためFlash推奨

    if isinstance(result, dict):
        return result
    return {}


# ==========================================
# 統合関数: ティッカーから有報データを取得
# ==========================================

def extract_yuho_data(ticker: str) -> dict:
    """
    メインフローから呼ばれるエントリーポイント。
    日本株ティッカーから有報メタデータを取得する（AI解析は最終レポートで一括）。
    非日本株やエラー時は空辞書を返す。
    """
    if not is_japanese_stock(ticker):
        return {"available": False, "reason": "非日本株のためEDINET対象外"}

    if not _get_edinet_key():
        return {"available": False, "reason": "EDINET_API_KEY未設定"}

    sec_code = ticker_to_sec_code(ticker)
    if not sec_code:
        return {"available": False, "reason": "証券コード変換失敗"}

    print(f"  📋 EDINET 有報検索中 (secCode: {sec_code})...")

    # Step 1: 最新有報を検索
    doc_info = find_latest_yuho(sec_code)
    if not doc_info:
        return {"available": False, "reason": "有報が見つからない"}

    # PDF の有無だけ確認（AI解析は最終レポートで一括）
    # PDF の有無を確認し、ダウンロード＆解析
    print(f"  ✅ 有報メタデータ取得成功: {doc_info.get('filer_name', '不明')}")
    
    # 実際の内容を取得・解析
    doc_id = doc_info.get("doc_id")
    pdf_bytes = download_yuho_pdf(doc_id)
    
    analysis_result = {}
    raw_text_extract = ""
    
    if pdf_bytes:
        print("  📄 PDFテキスト抽出中...")
        raw_text_extract = _extract_text_from_pdf_bytes(pdf_bytes)
        if raw_text_extract:
            print(f"  ✅ テキスト抽出完了 ({len(raw_text_extract)}文字)")
            analysis_result = _analyze_yuho_with_gemini(raw_text_extract, doc_info.get('filer_name', ''))
            # 続きの分析（Layer3）のために生テキストの一部（最大2万文字程度）を保持する手もあるが、
            # ここで構造化データにしてしまった方が扱いやすい。
            # 今回はフォーマット済みの analysis_result を優先使用する。
        else:
            print("  ⚠️ テキスト抽出失敗または空")
    else:
        print("  ⚠️ PDFダウンロード失敗")

    return {
        "available": True,
        "doc_info": doc_info,
        "risk_top3": analysis_result.get("risk_top3", []),
        "moat": analysis_result.get("moat", {
            "type": "データなし", "source": "", "durability": "", "description": ""
        }),
        "management_tone": analysis_result.get("management_tone", {
            "overall": "データなし", "key_phrases": [], "detail": ""
        }),
        "rd_focus": analysis_result.get("rd_focus", []),
        "management_challenges": analysis_result.get("management_challenges", ""),
        "summary": analysis_result.get("summary", ""),
        # 必要に応じて生テキストの冒頭/重要部分を渡すことも可能だが、サイズに注意
        "raw_text": raw_text_extract[:10000] if raw_text_extract else ""
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
    print(f"\n  EDINET_API_KEY: {'設定済み' if _get_edinet_key() else '未設定'}")

    # テスト 4: EDINETコードマッピング
    if _get_edinet_key():
        code_map = _load_edinet_code_map()
        toyota_code = get_edinet_code("72030")
        print(f"\n  EDINETコードマッピング: {len(code_map)}社読込")
        print(f"  トヨタ(72030) → {toyota_code or '未マッチ'}")

    # テスト 5: フォールバック（APIキーなし）
    print()
    result = extract_yuho_data("AAPL")
    print(f"  extract_yuho_data('AAPL') => available={result.get('available')}, "
          f"reason={result.get('reason')}")

    if not _get_edinet_key():
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
