# 有価証券報告書（有報）データ取得システム設計書

**版数**: v1.1  
**更新日**: 2026-03-18  
**作成者**: CIO Intelligence Development Team  
**ステータス**: 本番適用済み

---

## 目次

1. [概要](#1-概要)
2. [システム全体像](#2-システム全体像)
3. [問題背景](#3-問題背景)
4. [改善要件](#4-改善要件)
5. [詳細設計](#5-詳細設計)
6. [データフロー](#6-データフロー)
7. [インターフェース設計](#7-インターフェース設計)
8. [エラーハンドリング](#8-エラーハンドリング)
9. [テスト設計](#9-テスト設計)
10. [運用設計](#10-運用設計)
11. [変更履歴](#11-変更履歴)

---

## 1. 概要

### 1.1 目的

本モジュールは、日本株（EDINET）および米国株（SEC）の有価証券報告書を取得し、定性分析（Qualitative Analysis）に必要なデータを抽出・提供する。

### 1.2 範囲

- **対象**: 株式分析システムの定性分析レイヤー
- **対象外**: 株価データ取得、定量分析、ポートフォリオ管理

### 1.3 用語定義

| 用語 | 定義 |
|------|------|
| 有報 | 有価証券報告書（日本：EDINET、米国：SEC 10-K/10-Q） |
| 定性分析 | 財務数値以外の企業価値評価（競争優位性、リスク、経営陣など） |
| 生テキスト | AI 解析前の PDF/HTML から抽出した_raw text_ |
| AI 解析 | Gemini による構造化データ抽出（リスク、堀、R&D など） |

---

## 2. システム全体像

### 2.1 アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                    CIO Intelligence System                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Data       │  │   Analyzer   │  │    Report    │      │
│  │   Fetcher    │→ │   (4 軸)     │→ │   Generator  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         ↑                ↑                                      │
│         │                │                                      │
│  ┌──────────────────────────────────┐                         │
│  │    有報データ取得モジュール      │                         │
│  │  ┌────────────┐ ┌────────────┐  │                         │
│  │  │ EDINET     │ │   SEC      │  │                         │
│  │  │ Client     │ │   Client   │  │                         │
│  │  │ (日本株)   │ │  (米国株)  │  │                         │
│  │  └────────────┘ └────────────┘  │                         │
│  └──────────────────────────────────┘                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 コンポーネント構成

| コンポーネント | ファイル | 責任 |
|---------------|----------|------|
| EDINET Client | `src/edinet_client.py` | 日本株の有報取得・解析 |
| SEC Client | `src/sec_client.py` | 米国株の 10-K/10-Q 取得・解析 |
| Analyzers | `src/analyzers.py` | 定性スコア計算・プロンプト生成 |
| Data Fetcher | `src/data_fetcher.py` | Gemini API 呼び出し |

---

## 3. 問題背景

### 3.1 事象

定性分析レイヤーで以下のメッセージが表示され、有報データが取得できない：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. 定性データ・有価証券報告書要約
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
（有報データ未取得）
```

### 3.2 原因分析

1. **API キー未設定時の早期失敗**
   - EDINET API キー未設定の場合、キャッシュチェック前にエラーリターン
   - 結果、キャッシュがある場合でもデータ取得不可

2. **AI 解析失敗時のフォールバック不在**
   - AI 解析が失敗すると、生テキストも返さずに `available: False`
   - 定性分析スコアが「スキップ」扱いに

3. **生テキストの活用不足**
   - AI 解析結果がない場合、Gemini プロンプトに生テキストを含まない
   - 最終レポート生成時に有報データを解析できない

### 3.3 影響範囲

- **機能影響**: 定性分析スコアが常に 5.0（中立）で固定
- **ユーザー影響**: 有報に基づく深い企業分析が不可能
- **ビジネス影響**: 投資判断の質が低下

---

## 4. 改善要件

### 4.1 機能要件

| ID | 要件 | 優先度 |
|----|------|--------|
| F-001 | EDINET API キー未設定時もキャッシュを利用できること | 高 |
| F-002 | AI 解析が失敗しても生テキストは返すこと | 高 |
| F-003 | 生テキストがあれば定性分析を「取得済み」とすること | 高 |
| F-004 | 生テキストを Gemini プロンプトに含めること | 高 |
| F-005 | 生テキストの文字量を 20,000 文字に増やすこと | 中 |

### 4.2 非機能要件

| ID | 要件 | 優先度 |
|----|------|--------|
| NF-001 | API 呼び出し失敗時もシステムを停止しないこと | 高 |
| NF-002 | キャッシュは 30 日間有効であること | 中 |
| NF-003 | エラーはログに出力し、ユーザーに通知すること | 中 |
| NF-004 | 既存の API との互換性を保つこと | 高 |

---

## 5. 詳細設計

### 5.1 `edinet_client.py` 変更点

#### 5.1.1 `extract_yuho_data()` 関数

**変更前**:
```python
def extract_yuho_data(ticker: str) -> dict:
    if not is_japanese_stock(ticker):
        return {"available": False, "reason": "非日本株のため EDINET 対象外"}
    
    if not _get_edinet_key():  # ← 早期チェック
        return {"available": False, "reason": "EDINET_API_KEY 未設定"}
    
    # ... 以下処理
```

**変更後**:
```python
def extract_yuho_data(ticker: str) -> dict:
    if not is_japanese_stock(ticker):
        return {"available": False, "reason": "非日本株のため EDINET 対象外"}
    
    # API キーチェックをキャッシュ確認後に移動
    sec_code = ticker_to_sec_code(ticker)
    
    # キャッシュチェック
    doc_info = _get_cached_doc_info(sec_code)
    
    if not doc_info:
        # キャッシュがない場合のみ API キーをチェック
        if not _get_edinet_key():
            print("⚠️ EDINET_API_KEY 未設定 — キャッシュもありません")
            return {"available": False, "reason": "EDINET_API_KEY 未設定"}
        
        doc_info = find_latest_yuho(sec_code)
        _save_cache(doc_info)
    
    # ... 以下処理
```

#### 5.1.2 AI 解析の条件付き実行

**変更前**:
```python
if raw_text_extract:
    print(f"✅ テキスト抽出完了 ({len(raw_text_extract)}文字)")
    analysis_result = _analyze_yuho_with_gemini(raw_text_extract, ...)
    # 常に AI 解析を実行
```

**変更後**:
```python
if raw_text_extract:
    print(f"✅ テキスト抽出完了 ({len(raw_text_extract)}文字)")
    # API キーがあれば AI 解析、なければ生テキストのみ
    if _get_edinet_key():
        analysis_result = _analyze_yuho_with_gemini(raw_text_extract, ...)
    else:
        print("ℹ️ API キー未設定のため AI 解析スキップ（生テキストのみ返す）")
```

#### 5.1.3 戻り値の改善

**変更前**:
```python
return {
    "available": True,  # 常に True
    "doc_info": doc_info,
    "raw_text": raw_text_extract[:10000] if raw_text_extract else ""
    # ...
}
```

**変更後**:
```python
# 生テキストがあれば「利用可能」として返す
has_data = bool(raw_text_extract) or bool(analysis_result)

return {
    "available": has_data,  # データの有無で判定
    "doc_info": doc_info,
    "raw_text": raw_text_extract[:20000] if raw_text_extract else ""
    # ...
}
```

### 5.2 `sec_client.py` 変更点

#### 5.2.1 `extract_sec_data()` 関数

**変更前**:
```python
# AI 解析：生テキストから構造化データを抽出
analysis_result = _analyze_sec_with_gemini(text, ticker)

return {
    "available": True,
    "raw_text": filing_summary,
    # ...
}
```

**変更後**:
```python
# AI 解析：エラー時はフォールバック
analysis_result = {}
try:
    analysis_result = _analyze_sec_with_gemini(text, ticker)
except Exception as e:
    print(f"⚠️ AI 解析失敗（生テキストのみ返す）: {e}")
    analysis_result = {}

# 生テキストがあれば「利用可能」として返す
has_data = bool(text) or bool(analysis_result)

return {
    "available": has_data,
    "raw_text": text[:20000] if text else "",
    # ...
}
```

### 5.3 `analyzers.py` 変更点

#### 5.3.1 `score_qualitative()` 関数

**変更前**:
```python
def score_qualitative(yuho_data: dict) -> dict:
    if not yuho_data or not yuho_data.get("available"):
        reason = yuho_data.get("reason", "有報データなし") if yuho_data else "有報データなし"
        return {
            "layer": "Qualitative",
            "score": 5.0,
            "details": [f"定性分析スキップ（{reason}）"],
            "data_points": 0,
        }
    # ... 以下処理
```

**変更後**:
```python
def score_qualitative(yuho_data: dict) -> dict:
    if not yuho_data or not yuho_data.get("available"):
        reason = yuho_data.get("reason", "有報データなし") if yuho_data else "有報データなし"
        # 生テキストがあれば「取得済み」扱い
        if yuho_data and yuho_data.get("raw_text"):
            return {
                "layer": "Qualitative",
                "score": 5.0,
                "details": ["有報/10-K データ取得済み（AI 解析は最終レポートで実施）"],
                "data_points": 1,
            }
        return {
            "layer": "Qualitative",
            "score": 5.0,
            "details": [f"定性分析スキップ（{reason}）"],
            "data_points": 0,
        }
    # ... 以下処理
```

#### 5.3.2 `format_yuho_for_prompt()` 関数

**変更前**:
```python
def format_yuho_for_prompt(yuho_data: dict) -> str:
    if not yuho_data or not yuho_data.get("available"):
        return ""
    
    # ... AI 解析結果のフォーマット
    
    return "\n".join(lines)
```

**変更後**:
```python
def format_yuho_for_prompt(yuho_data: dict) -> str:
    if not yuho_data:
        return ""
    
    # available が false でも raw_text があれば処理を続行
    has_raw_text = bool(yuho_data.get("raw_text"))
    if not yuho_data.get("available") and not has_raw_text:
        return ""
    
    # ... AI 解析結果のフォーマット
    
    # 生テキストがあれば追加（AI 解析が失敗した場合のフォールバック）
    if has_raw_text:
        raw = yuho_data["raw_text"]
        if len(raw) > 5000:
            lines.append(f"〈有報/10-K 生テキスト（抜粋）〉{raw[:5000]}\n...(中略)...{raw[-5000:]}")
        else:
            lines.append(f"〈有報/10-K 生テキスト〉{raw}")
    
    return "\n".join(lines)
```

---

## 6. データフロー

### 6.1 通常フロー（API キーあり）

```
[ユーザー入力: 7203.T]
        ↓
[edinet_client.extract_yuho_data()]
        ↓
[キャッシュチェック] → ミス
        ↓
[EDINET API: メタデータ検索]
        ↓
[PDF ダウンロード]
        ↓
[テキスト抽出 (pdfminer)]
        ↓
[Gemini AI 解析] ← API キー使用
        ↓
[構造化データ + 生テキスト]
        ↓
[analyzers.score_qualitative()]
        ↓
[定性スコア計算]
        ↓
[format_yuho_for_prompt()]
        ↓
[Gemini プロンプトに埋め込み]
        ↓
[最終レポート生成]
```

### 6.2 フォールバックフロー（API キーなし）

```
[ユーザー入力: 7203.T]
        ↓
[edinet_client.extract_yuho_data()]
        ↓
[キャッシュチェック] → ヒット/ミス
        ↓
[EDINET API: メタデータ検索] ← API キー不要（PDF ダウンロードのみ）
        ↓
[PDF ダウンロード] ← API キー不要（公開 PDF）
        ↓
[テキスト抽出 (pdfminer)]
        ↓
[AI 解析スキップ] ← API キーなし
        ↓
[生テキストのみ返却]
        ↓
[analyzers.score_qualitative()]
        ↓
[「データ取得済み」として処理]
        ↓
[format_yuho_for_prompt()]
        ↓
[生テキストをプロンプトに埋め込み]
        ↓
[Gemini が直接解析]
        ↓
[最終レポート生成]
```

### 6.3 エラーフロー（データ取得失敗）

```
[ユーザー入力: 7203.T]
        ↓
[edinet_client.extract_yuho_data()]
        ↓
[キャッシュチェック] → ミス
        ↓
[EDINET API キーチェック] → なし
        ↓
[エラーリターン]
        ↓
[available: False, reason: "EDINET_API_KEY 未設定"]
        ↓
[analyzers.score_qualitative()]
        ↓
[「定性分析スキップ」として処理]
        ↓
[format_yuho_for_prompt()] → 空文字返却
        ↓
[プロンプトに含めず]
        ↓
[最終レポート生成（定性分析なし）]
```

---

## 7. インターフェース設計

### 7.1 `extract_yuho_data()` / `extract_sec_data()`

**シグネチャ**:
```python
def extract_yuho_data(ticker: str) -> dict
def extract_sec_data(ticker: str) -> dict
```

**戻り値スキーマ**:
```typescript
{
  available: boolean,           // データ取得可否
  reason?: string,              // unavailable の場合の理由
  doc_info?: {
    filer_name: string,         // 提出者
    period_start: string,       // 対象期間開始
    period_end: string,         // 対象期間終了
    submit_date: string,        // 提出日
  },
  raw_text: string,             // 生テキスト（最大 20,000 文字）
  risk_top3: Array<{            // リスク TOP3（AI 解析結果）
    risk: string,
    severity: "高" | "中" | "低",
    detail: string,
  }>,
  moat: {                       // 競争優位性（AI 解析結果）
    type: string,
    source: string,
    durability: "高" | "中" | "低",
    description: string,
  },
  management_tone: {            // 経営陣トーン（AI 解析結果）
    overall: "強気" | "中立" | "慎重" | "弱気",
    key_phrases: string[],
    detail: string,
  },
  rd_focus: Array<{             // R&D 注力分野（AI 解析結果）
    area: string,
    detail: string,
  }>,
  management_challenges: string, // 経営課題（AI 解析結果）
  summary: string,               // サマリー（AI 解析結果）
}
```

### 7.2 `score_qualitative()`

**シグネチャ**:
```python
def score_qualitative(yuho_data: dict) -> dict
```

**戻り値スキーマ**:
```typescript
{
  layer: "Qualitative",
  score: number,                // 0-10
  details: string[],            // 評価詳細
  data_points: number,          // 評価に使用したデータポイント数
}
```

**スコア計算ロジック**:
```
if (データなし):
  score = 5.0, details = ["定性分析スキップ（{reason}）"], data_points = 0
elif (生テキストのみ):
  score = 5.0, details = ["有報/10-K データ取得済み（AI 解析は最終レポートで実施）"], data_points = 1
elif (AI 解析あり):
  score = (moat_score + risk_score + rd_score + tone_score) / count
  data_points = count
```

### 7.3 `format_yuho_for_prompt()`

**シグネチャ**:
```python
def format_yuho_for_prompt(yuho_data: dict) -> str
```

**出力フォーマット**:
```
【有価証券報告書分析】
提出者：{filer_name}
対象期間：{period_start} ～ {period_end}
提出日：{submit_date}

〈経営リスク TOP3〉
  1. [{severity}] {risk}: {detail}
  2. ...

〈競争優位性（堀）〉 {type} (源泉：{source}) (耐久性：{durability})
  {description}

〈経営陣トーン〉 {overall}
  {detail}
  キーフレーズ：{key_phrases}

〈R&D 注力分野〉
  ・{area}: {detail}

〈経営課題〉{management_challenges}

〈アナリスト要約〉{summary}

〈有報/10-K 生テキスト（抜粋）〉
{raw_text}
```

---

## 8. エラーハンドリング

### 8.1 エラー分類

| エラー種別 | コード | 処理 | ユーザー通知 |
|-----------|--------|------|-------------|
| API キー未設定 | `NO_API_KEY` | キャッシュ確認後エラー | 「API キー未設定」 |
| メタデータ未取得 | `NOT_FOUND` | エラーリターン | 「有報が見つからない」 |
| PDF ダウンロード失敗 | `DOWNLOAD_FAILED` | 生テキストなしで返却 | 「PDF 取得失敗」 |
| テキスト抽出失敗 | `EXTRACT_FAILED` | 生テキストなしで返却 | 「テキスト抽出失敗」 |
| AI 解析失敗 | `AI_ANALYSIS_FAILED` | 生テキストのみ返却 | ログのみ（続行） |

### 8.2 エラーハンドリング方針

```python
# 基本方針：可能な限りフォールバック、システムは停止しない

try:
    # AI 解析（失敗しても続行）
    analysis_result = _analyze_with_gemini(text)
except Exception as e:
    print(f"⚠️ AI 解析失敗（生テキストのみ返す）: {e}")
    analysis_result = {}

# データの有無で判定
has_data = bool(raw_text) or bool(analysis_result)

return {
    "available": has_data,
    # ...
}
```

### 8.3 ログ出力

```python
# 情報ログ
print(f"  📋 EDINET 有報検索中 (secCode: {sec_code})...")
print(f"  ✅ テキスト抽出完了 ({len(raw_text_extract)}文字)")

# 警告ログ
print(f"  ⚠️ EDINET_API_KEY 未設定 — キャッシュもありません")
print(f"  ⚠️ PDF ダウンロード失敗")

# エラーログ
print(f"  ⚠️ AI 解析失敗（生テキストのみ返す）: {e}")
```

---

## 9. テスト設計

### 9.1 単体テスト

#### テストケース 1: EDINET 通常系

```python
def test_extract_yuho_data_normal():
    """API キーあり、キャッシュなしの通常フロー"""
    result = extract_yuho_data("7203.T")
    
    assert result["available"] == True
    assert "doc_info" in result
    assert "raw_text" in result
    assert len(result["raw_text"]) > 0
```

#### テストケース 2: EDINET フォールバック

```python
def test_extract_yuho_data_fallback():
    """API キーなし、キャッシュありのフォールバック"""
    # キャッシュを事前準備
    _save_cache(mock_doc_info)
    
    # API キーを unset
    os.environ["EDINET_API_KEY"] = ""
    
    result = extract_yuho_data("7203.T")
    
    assert result["available"] == True
    assert "raw_text" in result
    assert "risk_top3" not in result  # AI 解析なし
```

#### テストケース 3: 定性スコア計算

```python
def test_score_qualitative_with_raw_text():
    """生テキストありの場合のスコア計算"""
    yuho_data = {
        "available": False,
        "raw_text": "test text",
    }
    
    result = score_qualitative(yuho_data)
    
    assert result["score"] == 5.0
    assert result["details"] == ["有報/10-K データ取得済み（AI 解析は最終レポートで実施）"]
    assert result["data_points"] == 1
```

### 9.2 結合テスト

#### テストケース 4: エンドツーエンド

```python
def test_end_to_end_qualitative_analysis():
    """定性分析の端到端テスト"""
    # 1. データ取得
    yuho_data = extract_yuho_data("7203.T")
    
    # 2. スコア計算
    score_result = score_qualitative(yuho_data)
    
    # 3. プロンプト生成
    prompt_text = format_yuho_for_prompt(yuho_data)
    
    # 4. 検証
    assert score_result["score"] >= 0
    assert len(prompt_text) > 0 or not yuho_data["available"]
```

### 9.3 テスト実行手順

```bash
# 単体テスト
python -m pytest tests/test_edinet_client.py -v
python -m pytest tests/test_sec_client.py -v
python -m pytest tests/test_analyzers.py::test_score_qualitative -v

# 結合テスト
python -m pytest tests/test_integration.py -v

# 手動テスト（実データ）
python -c "from src.edinet_client import extract_yuho_data; print(extract_yuho_data('7203.T'))"
```

---

## 10. 運用設計

### 10.1 監視項目

| 項目 | 閾値 | アラート |
|------|------|---------|
| EDINET API エラー率 | 10% 以上 | 警告 |
| SEC API エラー率 | 10% 以上 | 警告 |
| AI 解析エラー率 | 20% 以上 | 警告 |
| 定性分析スキップ率 | 30% 以上 | 注意 |

### 10.2 キャッシュ管理

#### キャッシュディレクトリ構成

```
.stock_analyze/
└── .edinet_cache/
    ├── edinet_code_list.csv          # EDINET コードリスト
    ├── lists/                        # 書類一覧キャッシュ
    │   └── list_2026-03-18.json
    └── found_docs/                   # 発見した有報キャッシュ
        └── 72030.json
```

#### キャッシュポリシー

| キャッシュ種別 | 有効期間 | 削除条件 |
|---------------|----------|----------|
| コードリスト | 30 日 | 30 日経過 or 手動削除 |
| 書類一覧 | 24 時間 | 24 時間経過 or 手動削除 |
| 発見した有報 | 30 日 | 30 日経過 or 手動削除 |

#### キャッシュクリアコマンド

```bash
# 全キャッシュクリア
rm -rf ~/.stock_analyze/.edinet_cache

# 特定の銘柄キャッシュのみクリア
rm ~/.stock_analyze/.edinet_cache/found_docs/72030.json
```

### 10.3 API キー管理

#### 環境変数

```bash
# .env ファイル
EDINET_API_KEY=your_edinet_api_key_here
SEC_USER_AGENT=Your-Contact-Email@example.com
```

#### API キー取得方法

**EDINET**:
1. https://api.edinet-fsa.go.jp/ にアクセス
2. ユーザー登録
3. API キーを発行

**SEC**:
- API キー不要（User-Agent のみ必須）
- `SEC_USER_AGENT` に連絡先メールアドレスを設定

### 10.4 障害対応

#### シナリオ 1: EDINET API ダウン

```
現象：メタデータ検索がタイムアウト
検知：API エラー率 10% 超
対応：
  1. キャッシュを利用したフォールバック
  2. ユーザーに「キャッシュデータ使用中」と通知
  3. API 復旧後、キャッシュ更新
```

#### シナリオ 2: Gemini API ダウン

```
現象：AI 解析が失敗
検知：AI 解析エラー率 20% 超
対応：
  1. 生テキストのみで続行
  2. 最終レポートで「AI 解析スキップ」と通知
  3. 生テキストをプロンプトに含め、Gemini が直接解析
```

---

## 11. 変更履歴

| 版数 | 日付 | 変更者 | 変更内容 |
|------|------|--------|----------|
| v1.0 | 2026-01-15 | Dev Team | 初版作成 |
| v1.1 | 2026-03-18 | Dev Team | 定性分析フォールバック機能追加 |

### v1.1 変更詳細

#### 変更 1: API キーチェックの遅延

**理由**: キャッシュがある場合でも API キー未設定で失敗していた  
**影響**: API キーなしでもキャッシュ利用可能に  
**ファイル**: `src/edinet_client.py`

#### 変更 2: AI 解析の条件付き実行

**理由**: AI 解析失敗時に生テキストも返さなかった  
**影響**: AI 解析失敗時も生テキストで続行可能に  
**ファイル**: `src/edinet_client.py`, `src/sec_client.py`

#### 変更 3: 生テキストの活用

**理由**: 生テキストがあれば Gemini が直接解析可能  
**影響**: 定性分析が「スキップ」から「取得済み」に改善  
**ファイル**: `src/analyzers.py`

#### 変更 4: 生テキスト量増加

**理由**: 10,000 文字では重要なセクションが欠落  
**影響**: より詳細な分析が可能に  
**ファイル**: `src/edinet_client.py`, `src/sec_client.py`

---

## 付録 A: 設定ファイルサンプル

### `.env` ファイル

```bash
# EDINET API
EDINET_API_KEY=your_edinet_api_key_here

# SEC EDGAR
SEC_USER_AGENT=CIO-Analysis/1.0 (your-email@example.com)

# Gemini API
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

### `config.json` 抜粋

```json
{
  "edinet": {
    "search_days": 400,
    "doc_type_code": "120",
    "target_sections": [
      "事業等のリスク",
      "経営方針、経営環境及び対処すべき課題等",
      "研究開発活動"
    ]
  },
  "scoring": {
    "qualitative": {
      "moat_weight": 1.0,
      "risk_weight": 1.0,
      "rd_weight": 1.0,
      "tone_weight": 1.0
    }
  }
}
```

---

## 付録 B: 出力サンプル

### 定性分析スコア出力

```json
{
  "layer": "Qualitative",
  "score": 7.5,
  "details": [
    "堀：ブランド — 耐久性 [高] → 長期優位性あり",
    "リスク：高 severity 1 件，中 2 件",
    "  主要リスク：地政学リスク，為替変動リスク，技術変革リスク",
    "R&D 注力：EV 電池，自動運転，AI — 将来成長への投資あり",
    "経営陣トーン：[強気] — 攻めの姿勢",
    "  キーフレーズ：変革，成長，グローバル"
  ],
  "data_points": 4
}
```

### 定性分析プロンプト出力

```
【有価証券報告書分析】
提出者：トヨタ自動車株式会社
対象期間：2023-04-01 ～ 2024-03-31
提出日：2024-06-20

〈経営リスク TOP3〉
  1. [高] 地政学リスク：国際情勢の悪化によりサプライチェーンが混乱
  2. [中] 為替変動リスク：円安進行により輸入コストが増加
  3. [中] 技術変革リスク：EV シフトの加速により既存事業が陳腐化

〈競争優位性（堀）〉 ブランド (源泉：長年の品質実績) (耐久性：高)
  世界的なブランド認知度と顧客ロイヤルティ

〈経営陣トーン〉 [強気]
  EV 投資と従来事業の両立で成長継続
  キーフレーズ：変革，成長，グローバル

〈R&D 注力分野〉
  ・EV 電池：全固体電池の実用化
  ・自動運転：Level 4 技術の開発
  ・AI: 生産工程の最適化

〈経営課題〉
  CASE 対応と収益性の両立

〈アナリスト要約〉
  自動車業界の構造変化に対応しつつ、安定収益を維持。

〈有報/10-K 生テキスト（抜粋）〉
[事業等のリスク]
1. 地政学的リスク...
2. 為替変動リスク...
...(以下 Gemini が直接解析)
```

---

**文書終了**
