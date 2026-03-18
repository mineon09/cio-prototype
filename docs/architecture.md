# アーキテクチャ

## 全体フロー

```
analyze.py（エントリポイント）
  │
  ├─ generate_prompt.py
  │    ├─ yfinance          → 株価・財務データ取得
  │    ├─ SEC EDGAR         → 10-K生テキスト取得
  │    └─ src/sec_parser.py → Item1A + Item7 を抽出
  │
  ├─ src/sec_cache.py       → テキスト・解析結果のキャッシュ管理
  │
  ├─ LLM解析（優先順位あり）
  │    ├─ Gemini 2.5 Flash  （メイン）
  │    ├─ Groq Llama 3      （Gemini 429時のフォールバック）
  │    └─ キャッシュ読み込み（解析済みなら即座に返す）
  │
  ├─ src/copilot_client.py  → GitHub Models API（GPT-4o）で最終分析
  │
  └─ 出力
       ├─ reports/{TICKER}_{DATE}.json
       └─ portfolio.csv
```

## キャッシュ設計

```
cache/
├─ sec_text/
│   └─ {ticker}_{filing_date}.txt     TTL: 90日
└─ sec_analysis/
    └─ {ticker}_{filing_date}.json    TTL: 90日
```

**キャッシュキーは提出日ベース**（例: `amat_2025-12-12`）。
同じ10-Kは初回のみ解析し、2回目以降はLLM呼び出しゼロで返す。

## モジュール一覧

| モジュール | 責務 | 戻り値の型 |
|---|---|---|
| `generate_prompt.py` | データ収集 → プロンプト生成 | `str`（プロンプト本文） |
| `src/sec_parser.py` | 10-K から Item1A/Item7 を抽出 | `dict` |
| `src/sec_cache.py` | キャッシュの読み書き管理 | `str \| None` / `dict \| None` |
| `src/sec_analyzer_patch.py` | Groq チャンク分割解析 | `tuple[str, dict]` ⚠️ |
| `src/copilot_client.py` | GitHub Models API 呼び出し | `tuple[str, str]` |
| `src/macro_regime.py` | マクロ環境の判定 | `dict` |
| `src/md_writer.py` | Markdown レポート出力 | `Path` |

> ⚠️ `sec_analyzer_patch.py` の戻り値はタプル。必ずアンパックして使うこと。

## 設計上の判断

### なぜセクション抽出（方針3）を採用したか

10-K全文（約80,000文字）をそのまま送ると Groq の TPM 上限（12,000トークン）を超過する。
必要な定性情報は Item 1A（リスク）と Item 7（MD&A）に集中しているため、
これだけ抽出すれば 15,000〜20,000 文字に収まり、Groq に1回で送れる。

| 方法 | Groq呼び出し | 処理時間 | 品質 |
|---|---|---|---|
| 全文チャンク分割 | 10回 + マージ | 約11分 | △（マージ精度低） |
| セクション抽出 ✅ | **1回** | **約10秒** | ◎ |
