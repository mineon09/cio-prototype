# アーキテクチャ（v2.4+）

## 全体フロー

```plaintext
main.py（エントリポイント / オーケストレーター）
  │
  ├─ src/data_fetcher.py
  │    ├─ yfinance                → 株価・財務・テクニカルデータ取得
  │    ├─ select_competitors()    → ルールベース＋Gemini で競合選定（API節約）
  │    └─ call_gemini()           → Gemini API 呼び出し（google_search ツール付き）
  │
  ├─ src/macro_regime.py
  │    └─ detect_regime()         → VIX/金利/ドル円からレジーム判定
  │         MacroHistoryCache（TTL 12h）
  │
  ├─ src/edinet_client.py         → 日本株: EDINET 有価証券報告書取得
  ├─ src/sec_client.py            → 米国株: SEC EDGAR 10-K/10-Q 取得
  │
  ├─ src/news_fetcher.py          → yfinance + Gemini google_search でニュース取得
  │
  ├─ src/dcf_model.py             → DCF理論株価算出（負債コスト込み正式WACC）
  │    └─ FCF PITフィルタ（決算発表45日ラグ考慮）
  │
  ├─ src/analyzers.py
  │    ├─ generate_scorecard()    → 4軸スコアカード算出
  │    │    Fundamental / Valuation / Technical / Qualitative
  │    ├─ resolve_sector_profile()→ セクター別閾値解決
  │    └─ generate_scorecard()    → BUY閾値: regime_overrides から解決
  │
  ├─ src/strategies.py            → BounceStrategy / BreakoutStrategy
  │    └─ TechnicalAnalyzer       → ATR・BB・RSI・MA計算
  │
  ├─ run_strategy_analysis()      → 戦略別エントリー判定（app.py からも利用）
  │
  ├─ analyze_all()                → LLM プロンプト構築・最終レポート生成
  │    ├─ 対戦表（4軸比較テーブル）
  │    ├─ マクロ文脈・DCFセクション
  │    ├─ TEMPORAL CONSTRAINTS（今日の日付・カレントQを注入）
  │    └─ Gemini / GitHub Models (copilot) に送信
  │
  └─ 出力
       ├─ src/md_writer.py         → data/reports/{TICKER}_{DATE}.md
       ├─ src/notion_writer.py     → Notion データベースに保存
       └─ save_to_dashboard_json() → data/results.json（履歴蓄積・filelock排他制御）
```

## キャッシュ設計

```plaintext
cache/
├─ sec_text/
│   └─ {ticker}_{filing_date}.txt       TTL: 90日
├─ sec_analysis/
│   └─ {ticker}_{filing_date}.json      TTL: 90日
└─ (macro: インメモリ MacroHistoryCache  TTL: 12h)

.edinet_cache/
└─ {ticker}_found_doc.json             TTL: 30日（有報ドキュメントID検索結果）
```

**キャッシュキーは提出日ベース**（例: `amat_2025-12-12`）。
同じ10-Kは初回のみ解析し、2回目以降はLLM呼び出しゼロで返す。

## モジュール一覧

| モジュール | 責務 | 戻り値の型 |
|---|---|---|
| `main.py` | オーケストレーション・CLIエントリポイント | — |
| `app.py` | Streamlit ダッシュボード | — |
| `src/data_fetcher.py` | yfinance データ取得・競合選定・Gemini API 呼び出し | `dict` |
| `src/analyzers.py` | 4軸スコアカード算出・セクタープロファイル解決 | `dict` |
| `src/strategies.py` | BounceStrategy / BreakoutStrategy エントリー判定 | `dict` |
| `src/macro_regime.py` | マクロレジーム判定（NEUTRAL/RISK_OFF/RATE_HIKE など） | `dict` |
| `src/dcf_model.py` | DCF理論株価（PITフィルタ付き） | `dict` |
| `src/edinet_client.py` | EDINET 有価証券報告書取得（日本株） | `dict` |
| `src/sec_client.py` | SEC EDGAR 10-K/10-Q 取得（米国株） | `dict` |
| `src/sec_parser.py` | 10-K から Item1A / Item7 を抽出 | `dict` |
| `src/news_fetcher.py` | yfinance + Gemini google_search でニュース取得 | `dict` |
| `src/investment_judgment.py` | API / ツールベース投資判断エンジン | `JudgmentResult` |
| `src/backtester.py` | バックテスト（PIT・モンテカルロ・ローリング） | `dict` |
| `src/portfolio.py` | ポジションサイジング・セクター集中度チェック | `tuple[float, str]` |
| `src/md_writer.py` | Markdown レポート出力 | `Path` |
| `src/notion_writer.py` | Notion API 書き込み（Add-On-Demand対応） | — |
| `src/sheets_writer.py` | Google Sheets 書き込み | — |
| `src/copilot_client.py` | GitHub Models API 呼び出し（GPT-4o） | `tuple[str, str]` |
| `src/parallel_utils.py` | 複数銘柄の並列データ取得（ThreadPoolExecutor） | `list[dict]` |
| `src/logging_utils.py` | 統一ログ設定・名前付きロガー | — |
| `src/utils.py` | config.json のロード・ティッカー別オーバーライド | `dict` |
| `src/data_cache.py` | 汎用ファイルキャッシュ（TTL付き） | — |
| `src/analyst_ratings.py` | アナリスト格付け取得 | `dict` |
| `src/industry_trends.py` | 業界トレンド分析（Gemini） | `dict` |
| `src/notifier.py` | 通知ユーティリティ | — |

> ⚠️ `run_strategy_analysis()` は `main.py` と `app.py` の両方から呼ばれる共有ロジック。引数を変更するときは両方を確認すること。

## LLM 優先順位・フォールバック

```plaintext
分析エンジン:
  1. Gemini 2.5 Flash（デフォルト）
     └─ --engine=copilot 時は GitHub Models (GPT-4o) を使用
  2. フォールバック: Groq Llama 3（Gemini 429 / 503 時）
  3. ローカルフォールバック: スコアカード数値のみで簡易レポート生成
```

## 設計上の重要ポイント

### API呼び出しは最大3回

1. 競合選定（Gemini が JSON で直接/代替/ベンチマーク銘柄を返す）
2. 有報解析（日本株: EDINET → Gemini / 米国株: SEC テキスト → Gemini）
3. 最終レポート生成（対戦表 + 4軸分析 + 投資判断を一括生成）

### TEMPORALガード（カタリスト日付の過去化防止）

`analyze_all()` 冒頭で今日の日付・カレントQ・次Qを計算し、プロンプトに
`TEMPORAL CONSTRAINTS` ブロックとして注入。LLMが訓練データのカットオフ日付で
カタリストを生成するのを防止する。

### Point-in-Time (PIT) フィルタ

バックテストおよびDCF算出時、財務データは決算発表から45日後に
「利用可能になった」とみなし、ルックアヘッドバイアスを排除。

*Last Updated: 2026-03-27 (v2.4.1)*
