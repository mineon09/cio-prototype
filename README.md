# stock_analyze / AI投資司令塔

`.gitignore` で除外されないファイルを起点に現行実装を確認し、実コード準拠で整理したプロジェクト概要です。

## 何ができるか

| 導線 | 役割 | 主な出力 |
| --- | --- | --- |
| `main.py` | 総合分析のCLI本体。競合選定、4軸スコア、マクロ判定、EDINET/SEC補助情報、最終レポート生成をまとめて実行 | Markdownレポート、`data/results.json`、任意でNotion |
| `app.py` | Streamlitダッシュボード。分析実行、履歴閲覧、バックテスト実行、Prompt Studioへの導線を提供 | ブラウザUI |
| `generate_prompt.py` | 外部LLMへ貼り付けるための投資分析プロンプトを生成 | `prompts/*.txt`、`prompts/*_context.json` |
| `save_claude_result.py` | Claude等の回答を `data/results.json` と任意のNotion DBへ保存 | `data/results.json` |
| `analyze.py` | GitHub Models API を使った一気通貫分析 | `data/reports/YYYYMM/*.md` |
| `src/backtester.py` | 単体バックテスト / ローリングバックテスト | 標準出力サマリー |
| `scripts/optimize_strategy.py` | LLMで戦略パラメータを反復最適化 | `data/optimization/*.json` |
| `verify_predictions.py` | 予測と実績の30/90/180日検証 | `data/results.json`、`data/accuracy_history.json` |
| `alert_check.py` | LINE Notify によるアラート送信 | LINE通知 |

## 主要構成

```text
.
├── main.py
├── app.py
├── analyze.py
├── generate_prompt.py
├── save_claude_result.py
├── verify_predictions.py
├── alert_check.py
├── portfolio_manager.py
├── list_latest_models.py
├── get_prompt.py
├── prompt_builder.py
├── scripts/
│   ├── optimize_strategy.py
│   ├── apply_optimization_results.py
│   └── validate_catalyst_dates.py
├── src/
│   ├── data_fetcher.py
│   ├── analyzers.py
│   ├── strategies.py
│   ├── backtester.py
│   ├── investment_judgment.py
│   ├── macro_regime.py
│   ├── dcf_model.py
│   ├── news_fetcher.py
│   ├── edinet_client.py
│   ├── sec_client.py
│   ├── copilot_client.py
│   └── ...
├── pages/
│   └── 01_prompt_studio.py
├── docs/
├── tests/
├── config.json
├── requirements.txt
└── .env.example
```

## セットアップ

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env
```

## 環境変数の要点

| 種別 | キー |
| --- | --- |
| 総合分析でほぼ必須 | `GEMINI_API_KEY` |
| 米国株のSEC取得 | `SEC_USER_AGENT` |
| 日本株の追加データソース | `EDINET_API_KEY`, `EDINETDB_API_KEY`, `JQUANTS_API_KEY` |
| ニュース/検索強化 | `FINNHUB_API_KEY`, `EXA_API_KEY`, `PERPLEXITY_API_KEY`, `TAVILY_API_KEY` |
| Claude最適化 | `ANTHROPIC_API_KEY` |
| Notion保存 | `NOTION_API_KEY`, `NOTION_DATABASE_ID` |
| LINE通知 | `LINE_NOTIFY_TOKEN` または `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID` |
| Google Sheets | `GOOGLE_SERVICE_ACCOUNT_JSON` または `GOOGLE_SHEETS_KEY_PATH`, `SPREADSHEET_ID` |

`analyze.py`、`main.py --engine copilot`、`scripts/optimize_strategy.py --model gpt-4o` を使う場合は、追加で `gh auth login` が必要です。

## よく使う流れ

### 1. 総合分析をCLIで実行

```bash
./venv/bin/python3 main.py 7203.T
./venv/bin/python3 main.py 7203.T 8306.T AAPL
./venv/bin/python3 main.py --ticker AAPL --strategy breakout
./venv/bin/python3 main.py AAPL --engine copilot
```

### 2. ブラウザで使う

```bash
streamlit run app.py
```

`app.py` から Prompt Studio（`pages/01_prompt_studio.py`）へ移動できます。

### 3. Claude向けプロンプトを作って結果を取り込む

```bash
./venv/bin/python3 generate_prompt.py 7203.T --copy
./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard
```

### 4. GitHub Modelsで完結させる

```bash
./venv/bin/python3 analyze.py AMAT
./venv/bin/python3 analyze.py 7203.T --model gpt-4o-mini
./venv/bin/python3 analyze.py --help
```

### 5. バックテストと改善ループ

```bash
./venv/bin/python3 -m src.backtester --ticker 7203.T --strategy long --start 2024-01-01 --months 12
./venv/bin/python3 scripts/optimize_strategy.py --ticker 8035.T --strategy bounce --dry-run
./venv/bin/python3 scripts/apply_optimization_results.py --dry-run
./venv/bin/python3 verify_predictions.py --stats
./venv/bin/python3 src/weight_optimizer.py --dry-run
```

## 保存先

| パス | 用途 |
| --- | --- |
| `data/results.json` | ダッシュボード兼履歴ストア |
| `data/reports/YYYYMM/` | Markdownレポート |
| `prompts/*.txt` | 生成した分析プロンプト |
| `prompts/*_context.json` | `save_claude_result.py` 用コンテキスト |
| `data/optimization/*.json` | 戦略最適化結果 |
| `data/accuracy_history.json` | 検証履歴・重み最適化用サマリー |

## 関連ドキュメント

| ファイル | 内容 |
| --- | --- |
| `docs/how_to_use.md` | 実行手順の詳細 |
| `docs/architecture.md` | 現行アーキテクチャの要約 |
| `docs/system_design.md` | 主要フローの設計観点 |
| `docs/spec.md` | AI/開発者向けの実装リファレンス |
| `docs/investment_judgment_guide.md` | シグナルやスコアの解釈 |
| `docs/YUHO_SYSTEM_DESIGN.md` | EDINET/SECまわりの詳細設計 |

## 現状の注意点

- `portfolio_manager.py` は台帳CLIの実装を含みますが、現スナップショットでは先頭に異常テキストが混入しており、そのままでは実行できません。
- `.gignore` は存在せず、除外設定は `.gitignore` にあります。

## License

MIT
