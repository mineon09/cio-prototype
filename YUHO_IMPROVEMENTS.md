# 有価証券報告書（有報）データ取得の改善

## 概要
定性分析（Layer 3: Qualitative）が「有報データ未取得」でスキップされる問題を改善。

## 問題点
1. EDINET/SEC API キー未設定時に即座に失敗してデータを返さなかった
2. AI 解析が失敗すると、生テキストも返さずに「 unavailable」としていた
3. その結果、定性分析スコアがスキップ扱いになっていた

## 改善内容

### 1. `src/edinet_client.py` の改善

#### 変更点 1: API キーチェックの遅延
- **Before**: 関数開始時に API キー未設定なら即座にリターン
- **After**: キャッシュチェック後に API キーをチェック
  - キャッシュがあれば API キーがなくても使用可能に
  - キャッシュがない場合のみ「API キー未設定」エラー

```python
# Before
if not _get_edinet_key():
    return {"available": False, "reason": "EDINET_API_KEY 未設定"}

# After
if not doc_info:
    if not _get_edinet_key():
        print("⚠️ EDINET_API_KEY 未設定 — キャッシュもありません")
        return {"available": False, "reason": "EDINET_API_KEY 未設定"}
```

#### 変更点 2: AI 解析の条件付き実行
- **Before**: 常に AI 解析を実行し、失敗すると全体が失敗
- **After**: API キーがあれば AI 解析、なければ生テキストのみ返す

```python
if raw_text_extract:
    print(f"✅ テキスト抽出完了 ({len(raw_text_extract)}文字)")
    if _get_edinet_key():
        analysis_result = _analyze_yuho_with_gemini(raw_text_extract, ...)
    else:
        print("ℹ️ API キー未設定のため AI 解析スキップ（生テキストのみ返す）")
```

#### 変更点 3: 生テキスト量の増加
- **Before**: 10,000 文字
- **After**: 20,000 文字（Gemini での直接解析用に十分な量を確保）

### 2. `src/sec_client.py` の改善

#### 変更点：AI 解析エラーのフォールバック
```python
analysis_result = {}
try:
    analysis_result = _analyze_sec_with_gemini(text, ticker)
except Exception as e:
    print(f"⚠️ AI 解析失敗（生テキストのみ返す）: {e}")
    analysis_result = {}

has_data = bool(text) or bool(analysis_result)
```

### 3. `src/analyzers.py` の改善

#### 変更点 1: `score_qualitative` のフォールバック処理
```python
# 生テキストがあれば「取得済み」扱い
if yuho_data and yuho_data.get("raw_text"):
    return {
        "layer": "Qualitative",
        "score": 5.0,
        "details": ["有報/10-K データ取得済み（AI 解析は最終レポートで実施）"],
        "data_points": 1,
    }
```

#### 変更点 2: `format_yuho_for_prompt` の生テキスト出力
- AI 解析結果がなくても、生テキストがあればプロンプトに含める
- Gemini が直接テキストを解析できるようにする

```python
# 生テキストがあれば追加（AI 解析が失敗した場合のフォールバック）
if has_raw_text:
    raw = yuho_data["raw_text"]
    if len(raw) > 5000:
        lines.append(f"〈有報/10-K 生テキスト（抜粋）〉{raw[:5000]}\\n...(中略)...{raw[-5000:]}")
    else:
        lines.append(f"〈有報/10-K 生テキスト〉{raw}")
```

## 動作フロー（改善後）

### ケース 1: EDINET API キーあり
1. キャッシュチェック → なし
2. EDINET API でメタデータ検索
3. PDF ダウンロード
4. テキスト抽出
5. **AI 解析実行** ← Gemini で構造化データ抽出
6. 結果を返す

### ケース 2: EDINET API キーなし（キャッシュあり）
1. キャッシュチェック → **あり**
2. **キャッシュからメタデータ取得** ← API 呼び出し不要
3. PDF ダウンロード（API キー不要）
4. テキスト抽出
5. **AI 解析スキップ** ← 生テキストのみ返す
6. 最終レポートで Gemini が生テキストを直接解析

### ケース 3: EDINET API キーなし（キャッシュなし）
1. キャッシュチェック → なし
2. **エラーリターン** ← 「API キー未設定」メッセージ

## 定性分析の表示改善

### Before
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. 定性データ・有価証券報告書要約
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
（有報データ未取得）
```

### After（ケース別）

#### AI 解析成功時
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. 定性データ・有価証券報告書要約
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【有価証券報告書分析】
提出者：トヨタ自動車株式会社
対象期間：2023-04-01 ～ 2024-03-31

〈経営リスク TOP3〉
  1. [高] 地政学リスク：...
  2. [中] 為替変動リスク：...
  3. [中] 技術変革リスク：...

〈競争優位性（堀）〉 ブランド (源泉：...) (耐久性：高)
...
```

#### 生テキストのみ取得時
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. 定性データ・有価証券報告書要約
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【有価証券報告書分析】
提出者：トヨタ自動車株式会社
対象期間：2023-04-01 ～ 2024-03-31

〈有報/10-K 生テキスト（抜粋）〉
[事業等のリスク]
1. 地政学的リスク...
2. 為替変動リスク...
...(以下 Gemini が直接解析)
```

## テスト方法

### 日本株（EDINET）
```bash
# API キーあり
export EDINET_API_KEY="your_key"
python -c "from src.edinet_client import extract_yuho_data; print(extract_yuho_data('7203.T'))"

# API キーなし（キャッシュ利用）
python -c "from src.edinet_client import extract_yuho_data; print(extract_yuho_data('7203.T'))"
```

### 米国株（SEC）
```bash
python -c "from src.sec_client import extract_sec_data; print(extract_sec_data('AAPL'))"
```

## 注意点

1. **EDINET API キー**: 本格的な AI 解析には依然として必要
   - 取得先：https://api.edinet-fsa.go.jp/
   
2. **キャッシュの有効性**:
   - メタデータキャッシュ：30 日
   - 有報 PDF：提出から 400 日以内
   
3. **生テキストの制限**:
   - 最大 20,000 文字に制限
   - 重要なセクション（事業等のリスク、MD&A 等）を優先的に抽出

## 今後の改善案

1. **キャッシュの自動更新**: 新規提出があったら自動更新
2. **テキスト抽出の最適化**: 重要なセクションのみ抽出
3. **AI 解析の非同期実行**: 分析をバックグラウンドで実行
4. **ローカル LLM の利用**: Ollama 等でのオフライン解析
