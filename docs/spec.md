# CIO Prototype — システム仕様書（AI向け完全リファレンス）

> **対象読者**: このリポジトリを初めて扱うAIエージェント / 開発者  
> **最終更新**: 2026-04-01 (v2.4.1 ベース)

---

## 目次

1. [システム概要](#1-システム概要)
2. [リポジトリ構造](#2-リポジトリ構造)
3. [エントリーポイント一覧](#3-エントリーポイント一覧)
4. [コアモジュール詳細（src/）](#4-コアモジュール詳細src)
5. [Streamlit UI（app.py / pages/）](#5-streamlit-uiapppy--pages)
6. [データフロー](#6-データフロー)
7. [外部API・サービス一覧](#7-外部apiサービス一覧)
8. [設定ファイル仕様](#8-設定ファイル仕様)
9. [データ構造](#9-データ構造)
10. [キャッシュ設計](#10-キャッシュ設計)
11. [主要設計パターン](#11-主要設計パターン)
12. [テスト](#12-テスト)
13. [環境変数](#13-環境変数)
14. [依存パッケージ](#14-依存パッケージ)

---

## 1. システム概要

**CIO Prototype (Professional Edition)** は、銘柄コード 1 つを入力するだけで AI が投資分析を自動実行するシステムです。

### 何をするか

- **入力**: 銘柄コード（例: `7203.T`, `AAPL`）
- **処理**: 株価データ取得 → 競合選定 → 有報/10-K 定性分析 → 4 軸スコアリング → マクロ判定 → AI 最終判断
- **出力**: `BUY / WATCH / SELL` シグナル + 目標価格 + 損切りライン + 根拠テキスト

### 対応市場

| 市場 | ティッカー例 | 有報ソース |
|---|---|---|
| 東証（日本株） | `7203.T`, `8306.T` | EDINET 有価証券報告書 |
| NYSE / NASDAQ（米国株） | `AAPL`, `AMAT` | SEC EDGAR 10-K / 10-Q |

### バージョン履歴（要点）

| バージョン | 主な変更 |
|---|---|
| v2.0.0 | PIT フィルタ、filelock 排他制御、正式 WACC |
| v2.1.0 | TTM EPS、外部レビュー 16 項目対応 |
| v2.2.0 | 競合選定ルールベース化（API 節約）、Notion Add-On-Demand |
| v2.3.0 | 単体テスト 66 件、logging_utils、スコア閾値外部化 |
| v2.4.0 | 投資判断エンジン（API/ツール/デュアル） |
| v2.4.1 | カタリスト日付ガード（TEMPORAL CONSTRAINTS） |

---

## 2. リポジトリ構造

```
stock_analyze/
│
├── main.py                     # CLI オーケストレーター（最重要エントリーポイント）
├── app.py                      # Streamlit ダッシュボード
├── analyze.py                  # GitHub Models API 分析（--engine copilot）
├── generate_prompt.py          # 高品質プロンプト生成 → クリップボード
├── get_prompt.py               # シンプルなデータ取得
├── save_claude_result.py       # Claude 回答の results.json 取り込み
├── prompt_builder.py           # プロンプト生成ライブラリ
├── analyze_trades.py           # 簡易トレード分析
├── portfolio_manager.py        # 保有銘柄台帳 CLI
├── alert_check.py              # LINE Notify アラート
├── verify_predictions.py       # 予測 vs 実績 照合
│
├── src/                        # コアロジック（27 モジュール）
│   ├── data_fetcher.py         # データ取得 + AI 呼び出し（937 行）
│   ├── analyzers.py            # 4 軸スコアリング（1319 行）
│   ├── strategies.py           # トレード戦略（457 行）
│   ├── backtester.py           # バックテスト（591 行）
│   ├── backtest_reporter.py    # BT 結果 → LLM フィードバック（444 行）
│   ├── macro_regime.py         # マクロレジーム判定（635 行）
│   ├── dcf_model.py            # DCF 理論株価（289 行）
│   ├── edinet_client.py        # EDINET 有報取得（602 行）
│   ├── sec_client.py           # SEC 10-K/10-Q 取得（574 行）
│   ├── sec_parser.py           # SEC テキスト抽出（179 行）
│   ├── jquants_client.py       # J-Quants OHLC（244 行）
│   ├── edinetdb_client.py      # EDINET DB API（344 行）
│   ├── news_fetcher.py         # ニュース取得（1261 行）
│   ├── investment_judgment.py  # 投資判断エンジン（714 行）
│   ├── llm_strategy_optimizer.py # LLM 戦略最適化（703 行）
│   ├── industry_trends.py      # 業界トレンド分析（597 行）
│   ├── analyst_ratings.py      # アナリスト評価（423 行）
│   ├── portfolio.py            # ポジションサイジング
│   ├── notion_writer.py        # Notion API（163 行）
│   ├── sheets_writer.py        # Google Sheets（183 行）
│   ├── copilot_client.py       # GitHub Models API
│   ├── notifier.py             # LINE Notify
│   ├── logging_utils.py        # ロギング
│   ├── data_cache.py           # キャッシュ管理（264 行）
│   ├── md_writer.py            # Markdown 出力
│   ├── utils.py                # config.json ロード・ティッカー別 override
│   └── parallel_utils.py       # 並列処理（ThreadPoolExecutor）
│
├── pages/
│   └── 01_prompt_studio.py     # Streamlit プロンプトスタジオ（15305 行）
│
├── scripts/
│   ├── optimize_strategy.py         # LLM 戦略最適化 CLI
│   ├── apply_optimization_results.py # 最適化結果 → config.json 反映
│   └── validate_catalyst_dates.py   # カタリスト日付バリデーション
│
├── tests/                      # pytest テスト群（18+ ファイル）
│
├── docs/                       # ドキュメント群
│   ├── spec.md                 # ← このファイル（AI 向け完全仕様）
│   ├── architecture.md         # アーキテクチャ図（コードフロー）
│   ├── system_design.md        # 設計書（バージョン履歴・ロジック詳細）
│   ├── how_to_use.md           # 使い方マニュアル
│   ├── investment_judgment_guide.md # スコア・シグナル解釈ガイド
│   ├── YUHO_SYSTEM_DESIGN.md   # 有報システム詳細設計
│   └── CHANGELOG.md            # バージョン別変更履歴
│
├── data/
│   ├── results.json            # 分析結果履歴（filelock 排他制御）
│   ├── portfolio.json          # 保有銘柄台帳
│   ├── cache/                  # スコア・テクニカルキャッシュ
│   ├── optimization/           # BT 最適化結果
│   └── reports/                # Markdown レポート
│
├── prompts/                    # 生成プロンプト + コンテキスト JSON
├── cache/                      # ルートキャッシュ（一部スクリプトが使用）
├── config.json                 # 全体設定（閾値・プロファイル・戦略パラメータ）
├── requirements.txt            # Python 依存パッケージ
├── .env.example                # 環境変数テンプレート
└── AGENTS.md                   # エージェント作業ルール
```

---

## 3. エントリーポイント一覧

### 3.1 `main.py` — CLI オーケストレーター（883 行）

最も重要なエントリーポイント。複数銘柄の並列分析を担う。

```bash
# 単一銘柄（Gemini デフォルト）
./venv/bin/python3 main.py 7203.T

# 複数銘柄
./venv/bin/python3 main.py 7203.T 8306.T AAPL

# 戦略指定（bounce / breakout / long）
./venv/bin/python3 main.py 7203.T --strategy bounce

# GitHub Models GPT-4o を使用
./venv/bin/python3 main.py AAPL --engine copilot

# バックテストモード
./venv/bin/python3 main.py 7203.T --backtest --start 2025-01-01

# ドライラン（API 呼び出しなし）
./venv/bin/python3 main.py 7203.T --dry-run
```

**主要関数:**

| 関数 | 役割 |
|---|---|
| `analyze_all(tickers, strategy)` | 複数銘柄の並列分析。競合選定→有報→スコア→AI 判断の一気通貫 |
| `save_to_dashboard_json(ticker, result, strategy)` | `data/results.json` に filelock 付きで追記 |
| `run_strategy_analysis(ticker, strategy)` | 戦略別エントリー判定（`app.py` と共有） |
| `_validate_market_bug_logic(prompt, result)` | AI 出力の矛盾チェック |

**処理フロー:**
```
1. Gemini で競合銘柄選定（direct 3 / substitute 2 / benchmark 2）
2. EDINET（日本株）or SEC（米国株）から有報/10-K 取得・解析
3. 4 軸スコアカード算出（analyzers.py）
4. マクロレジーム判定（macro_regime.py）
5. 対戦表 + AI 最終判断生成（Gemini / GPT-4o）
6. results.json に書き込み
7. Notion（設定時）に書き込み
```

---

### 3.2 `app.py` — Streamlit ダッシュボード（617 行）

```bash
streamlit run app.py
# → http://localhost:8501
```

**主要コンポーネント:**

| 関数 | 役割 |
|---|---|
| `load_results()` | `data/results.json` 読み込み |
| `render_scorecard_tabs()` | 4 軸スコアカードタブ表示 |
| `render_price_history()` | yfinance 株価チャート |
| `render_alert_section()` | アラート条件表示 |
| `render_prediction_accuracy()` | 予測精度（30/90/180 日）表示 |

---

### 3.3 `generate_prompt.py` — プロンプト生成（1455 行）

```bash
# プロンプト生成 + クリップボードコピー
./venv/bin/python3 generate_prompt.py 7203.T --copy

# ファイル出力
./venv/bin/python3 generate_prompt.py AAPL -o report_prompt.txt
```

生成したプロンプトは `prompts/{ticker}_context.json` に自動保存される。

**主要関数:**

| 関数 | 役割 |
|---|---|
| `collect_data_minimal(ticker, use_cache)` | データ収集（キャッシュ優先） |
| `build_high_quality_prompt(data)` | 高品質プロンプト生成 |
| `build_simple_prompt(data)` | フォールバック用シンプルプロンプト |
| `format_scorecard_text(scorecard)` | スコアカードのテキスト整形 |
| `fetch_news_with_fallback(ticker)` | ニュース取得（複数ソースフォールバック） |

---

### 3.4 `analyze.py` — GitHub Models API 統合分析（204 行）

```bash
./venv/bin/python3 analyze.py AMAT
./venv/bin/python3 analyze.py 7203.T --model gpt-4o-mini
./venv/bin/python3 analyze.py XOM --no-cache -o report.md
```

**サポートモデル:** `gpt-4o`（推奨）/ `gpt-4o-mini` / `llama405b` / `llama70b` / `mistral`

---

### 3.5 `save_claude_result.py` — Claude 回答取り込み

```bash
# クリップボードから取り込み
./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard

# ファイルから取り込み
./venv/bin/python3 save_claude_result.py 7203.T --file result.txt
```

---

### 3.6 `portfolio_manager.py` — 保有銘柄台帳

```bash
./venv/bin/python3 portfolio_manager.py add 8306.T --qty 100 --price 2450
./venv/bin/python3 portfolio_manager.py add AAPL --qty 50 --price 185.5 --currency USD
./venv/bin/python3 portfolio_manager.py list         # 含損益付き一覧
./venv/bin/python3 portfolio_manager.py show 8306.T  # 詳細
./venv/bin/python3 portfolio_manager.py remove 8306.T
```

---

### 3.7 `alert_check.py` — LINE Notify アラート

```bash
./venv/bin/python3 alert_check.py              # 全銘柄チェック
./venv/bin/python3 alert_check.py --ticker 8306.T
./venv/bin/python3 alert_check.py --dry-run    # 通知なし確認
```

**アラートトリガー:**
1. 損切りライン接近：現在価格が `stop_loss` の +3% 以内
2. シグナル変化：`BUY → WATCH` など
3. スコア急落：-1.5 以上の低下

**cron 例:**
```bash
0 8 * * * cd ~/projects/stock_analyze && ./venv/bin/python3 alert_check.py >> data/alert.log 2>&1
```

---

### 3.8 `verify_predictions.py` — 予測精度照合

```bash
./venv/bin/python3 verify_predictions.py                          # 全銘柄・全ウィンドウ
./venv/bin/python3 verify_predictions.py --ticker 8306.T --window 30
./venv/bin/python3 verify_predictions.py --stats                  # 精度統計表示
```

30 / 90 / 180 日後の実際の株価と AI 予測を照合する。

---

### 3.9 `scripts/optimize_strategy.py` — LLM 戦略最適化

```bash
./venv/bin/python3 scripts/optimize_strategy.py \
    --ticker 8035.T --strategy bounce --dry-run

./venv/bin/python3 scripts/optimize_strategy.py \
    --ticker 8035.T --strategy bounce --max-iter 5

# グループ一括最適化
./venv/bin/python3 scripts/optimize_strategy.py --group JP_semiconductor
```

**処理フロー:**
1. バックテスト実行
2. LLM にフィードバック（P1/P2/P3 レベル）を渡す
3. LLM から改善提案を取得
4. `config.json` に反映
5. 最大 `--max-iter` 回まで反復

**LLM 性能比較（論文実験値）:**

| モデル | P&L 改善率 |
|---|---|
| Claude Sonnet ⭐推奨 | +14.1% |
| Gemini | +7.3% |
| GPT-4o | -0.3% |

---

## 4. コアモジュール詳細（src/）

### 4.1 `data_fetcher.py` — データ取得・AI 呼び出し

#### AI 呼び出し関数

```python
call_gemini(
    prompt: str,
    parse_json: bool = False,
    max_retries: int = 5
) -> tuple[str | dict, str]  # (レスポンス, モデル名)

call_groq(
    prompt: str,
    parse_json: bool = False,
    model: str = "llama-3.3-70b-versatile"
) -> tuple[str | dict, str]
```

**フォールバックチェーン:** Gemini → Groq → キャッシュ / 簡易レポート

#### 株価データ取得

```python
fetch_stock_data(
    ticker: str,
    as_of_date: str | None = None   # PIT フィルタ用（バックテスト時）
) -> dict
```

**戻り値の主なフィールド:**
```json
{
  "name": "Toyota Motor Corp",
  "sector": "Consumer Cyclical",
  "currency": "JPY",
  "metrics": {
    "price": 2450.0,
    "market_cap": 24000000000000,
    "pe": 25.5,
    "pb": 2.1,
    "roe": 12.5,
    "operating_margin": 18.3,
    "debt_to_equity": 0.8,
    "current_ratio": 1.5,
    "eps_ttm": 320.0
  },
  "technical": {
    "rsi": 65.2,
    "ma50": 2380.0,
    "ma200": 2300.0,
    "bb_upper": 2500.0,
    "bb_middle": 2450.0,
    "bb_lower": 2400.0,
    "atr": 45.0,
    "volume_ratio": 1.2
  }
}
```

#### 競合選定

```python
select_competitors(
    target_data: dict,
    macro_data: dict | None = None
) -> dict
```

**戻り値:**
```json
{
  "direct": ["TSLA", "BYD", "F"],
  "substitute": ["UBER", "LYFT"],
  "benchmark": ["AAPL", "MSFT"]
}
```

ルールベース（同セクター・同市場）で候補を絞り、Gemini で補完する（API 節約設計）。

---

### 4.2 `analyzers.py` — 4 軸スコアリングエンジン

#### セクタープロファイル解決

```python
resolve_sector_profile(sector: str) -> tuple[str, dict, dict, dict, dict]
# returns: (profile_name, fund_cfg, val_cfg, tech_cfg, weights)
```

**セクタープロファイル種別:**

| プロファイル | 対象 | Fundamental重み | Valuation重み | Technical重み | Qualitative重み |
|---|---|---|---|---|---|
| `high_growth` | Technology 等 | 0.30 | 0.20 | 0.25 | 0.25 |
| `healthcare` | Healthcare | 0.30 | 0.15 | 0.20 | 0.35 |
| `value` | Industrials 等 | 0.35 | 0.30 | 0.20 | 0.15 |
| `financial` | 銀行・保険 | 0.35 | 0.30 | 0.15 | 0.20 |

#### スコアリング関数（すべて 0〜10 を返す）

```python
score_fundamental(metrics: dict, sector: str) -> dict
# {"score": 6.5, "reasoning": "ROE 12.5%（良好）..."}

score_valuation(metrics: dict, technical: dict, sector: str) -> dict
score_technical(technical: dict, sector: str) -> dict
score_qualitative(yuho_data: dict, metrics: dict, sector: str) -> dict
```

#### スコアカード統合

```python
generate_scorecard(
    metrics: dict,
    technical: dict,
    yuho_data: dict,
    sector: str,
    macro_data: dict
) -> dict
```

**戻り値:**
```json
{
  "fundamental": {"score": 6.5, "reasoning": "..."},
  "valuation":   {"score": 7.2, "reasoning": "..."},
  "technical":   {"score": 5.8, "reasoning": "..."},
  "qualitative": {"score": 5.0, "reasoning": "..."},
  "total_score": 6.4,
  "weights": {"fundamental": 0.35, "valuation": 0.25, "technical": 0.20, "qualitative": 0.20},
  "summary_text": "総合評価: WATCH ..."
}
```

#### テクニカル分析クラス

```python
class TechnicalAnalyzer:
    def calculate_rsi(df: DataFrame, period: int = 14) -> Series
    def calculate_bollinger_bands(df, period=20, std=2) -> tuple[Series, Series, Series]
    def calculate_macd(df) -> tuple[Series, Series, Series]  # (macd, signal, histogram)
    def calculate_atr(df, period=14) -> Series
    def get_technical_summary() -> str
```

#### ユーティリティ

```python
format_yuho_for_prompt(yuho_data: dict) -> str  # 有報データをテキスト形式に整形
```

---

### 4.3 `strategies.py` — トレード戦略

#### クラス階層

```
BaseStrategy
├── LongStrategy      # 中長期トレンドフォロー
├── BounceStrategy    # RSI 逆張り
└── BreakoutStrategy  # ブレイクアウト順張り
```

#### 共通インターフェース

```python
class BaseStrategy:
    def analyze_entry(row, daily_data, ta) -> dict
    # {"is_entry": bool, "details": [...], "metrics": {...}}

    def should_sell(row, past_slice, ta, ctx) -> tuple[bool, str, float]
    # (should_sell, reason, exit_price)

    def get_buy_threshold(regime: str) -> float
    # マクロレジームに応じた BUY 閾値を返す
```

#### BounceStrategy

- **エントリー条件**: RSI < 35 かつ BB 下限付近かつ出来高確認
- **エグジット**: hard_stop (-2.5%) / take_profit (+5.0%) / time_stop (20 bars)

#### BreakoutStrategy

- **エントリー条件**: 20 日高値ブレイク + 出来高増加 + 強気終値
- **エグジット**: hard_stop (-3.0%) / take_profit (+10.0%) / ATR トレイリング
- Death Cross 検出時に強制エグジット

#### LongStrategy

- **エントリー条件**: 4 軸スコア ≥ BUY 閾値（レジーム別調整）
- **Premium Quality Override**: Fundamental ≥ 8.0 の場合、min_score を緩和
- **Momentum Bonus**: スコア上昇トレンド時に +0.5 ボーナス

---

### 4.4 `backtester.py` — バックテスト

#### メイン関数

```python
run_backtest(
    ticker: str,
    start_date: str,
    duration_months: int,
    strategy: str,
    cli_overrides: dict = None,
    config_override: dict = None
) -> dict
```

**戻り値（主要フィールド）:**
```json
{
  "ticker": "7203.T",
  "strategy": "bounce",
  "start_date": "2024-01-01",
  "trades": [
    {
      "entry_date": "2024-01-15",
      "entry_price": 2450.0,
      "exit_date": "2024-01-22",
      "exit_price": 2570.0,
      "return_pct": 4.9,
      "reason": "take_profit"
    }
  ],
  "performance": {
    "total_return": 12.5,
    "sharpe_ratio": 0.85,
    "max_drawdown": -8.2,
    "win_rate": 0.62,
    "profit_factor": 1.8
  }
}
```

#### PIT（Point-in-Time）フィルタ

決算発表から **45 日後** を「市場に情報が届いた日」とみなす。  
`as_of_date` より 45 日以上前に発表された決算データのみ「既知」として使用し、ルックアヘッドバイアスを排除する。

#### モンテカルロシミュレーション

```python
run_monte_carlo(
    trades: list,
    iterations: int = 1000,
    initial_capital: float,
    position_pct: float
) -> dict
# {"mean_return": ..., "std_return": ..., "percentile_5": ..., "percentile_95": ...}
```

ブートストラップ法（1000 回リサンプリング）。

#### ローリングバックテスト（Walk-Forward）

```python
run_rolling_backtest(
    ticker: str,
    start_date: str,
    total_months: int,
    window_months: int,
    step_months: int,
    strategy: str
) -> dict
```

---

### 4.5 `macro_regime.py` — マクロレジーム判定

```python
detect_regime() -> dict
# {
#   "regime": "NEUTRAL",       # RISK_ON / NEUTRAL / RISK_OFF / RATE_HIKE
#   "vix": 18.5,
#   "us10y": 4.2,
#   "usdjpy": 150.2,
#   "details": "VIX 低位..."
# }
```

**判定ロジック:**

| レジーム | 条件（例） |
|---|---|
| `RISK_ON` | VIX < 15 かつ 金利安定 |
| `NEUTRAL` | VIX 15〜25 |
| `RISK_OFF` | VIX > 25 |
| `RATE_HIKE` | 金利上昇トレンド |

**レジームによるスコア閾値変動:**

| シグナル | RISK_ON | NEUTRAL | RISK_OFF |
|---|---|---|---|
| BUY | 5.5 | 6.5 | 7.5 |
| WATCH | 4.5 | 5.5 | 6.5 |

**キャッシュ:** `MacroHistoryCache` インメモリ（TTL=12h）

---

### 4.6 `dcf_model.py` — DCF 理論株価

```python
estimate_fair_value(
    ticker: str,
    as_of_date: str | None = None
) -> dict
# {
#   "fair_value": 340.0,
#   "current_price": 285.0,
#   "upside": 19.3,           # 上昇余地 %
#   "margin_of_safety": 16.2, # 安全域 %
#   "scenarios": {
#     "bull": {"growth": 15, "fair_value": 420},
#     "base": {"growth": 10, "fair_value": 340},
#     "bear": {"growth":  5, "fair_value": 260}
#   },
#   "wacc": 9.5,
#   "fcf_history": [...]
# }

calculate_wacc(ticker) -> tuple[float, float, float]
# (cost_of_equity, cost_of_debt, wacc)
```

FCF 取得時にも PIT フィルタ（`as_of_date` の 45 日前ラグ）を適用。

---

### 4.7 `edinet_client.py` — EDINET 有報取得（日本株）

```python
get_yuho_analysis(
    ticker: str,
    as_of_date: str | None = None
) -> dict
# {
#   "risks": ["円高リスク", "..."],
#   "moat": "ブランド力 + コスト競争力",
#   "rd_investment": "売上比 8.5%",
#   "management_tone": "慎重",
#   "financial_health_score": 7.2
# }
```

**キャッシュ:** `.edinet_cache/` TTL=30 日

---

### 4.8 `sec_client.py` — SEC 10-K/10-Q 取得（米国株）

```python
get_10k_analysis(
    ticker: str,
    as_of_date: str | None = None
) -> dict
# 有報と同様の構造
```

**キャッシュ:** `cache/sec_text/` と `cache/sec_analysis/` TTL=90 日

---

### 4.9 `news_fetcher.py` — ニュース取得（1261 行）

```python
get_recent_news(
    ticker: str,
    days: int = 14
) -> list[dict]
# [{"title": "...", "date": "2026-03-20", "source": "Bloomberg", "url": "..."}]
```

**フォールバックチェーン（日本株）:**
1. Gemini google_search ツール
2. Google News RSS
3. Exa / Perplexity / Tavily

**フォールバックチェーン（米国株）:**
1. Finnhub API
2. yfinance ニュース
3. Gemini google_search

---

### 4.10 `investment_judgment.py` — 投資判断エンジン（714 行）

3 種のエンジンを実装。

| エンジン | 方式 | 速度 | コスト |
|---|---|---|---|
| `APIJudgmentEngine` | LLM（Gemini / Qwen） | 2〜5 秒 | API 料金 |
| `ToolJudgmentEngine` | ルールベース | < 0.1 秒 | 無料 |
| `DualJudgmentEngine` | 両者比較・統合 | 2〜5 秒 | API 料金 |

```python
class JudgmentResult:
    signal: str           # "BUY" / "WATCH" / "SELL"
    score: float
    entry_price: float
    stop_loss: float
    take_profit: float
    reasoning: str
    confidence: float
```

---

### 4.11 `llm_strategy_optimizer.py` — LLM 戦略最適化（703 行）

論文ベースの P1/P2/P3 フィードバックレベル実装。

```python
optimize_strategy(
    ticker: str,
    strategy: str,
    backtest_result: dict,
    feedback_level: str = "P2",  # "P1" / "P2" / "P3"
    model: str = "claude"        # "claude" / "gemini" / "gpt4o"
) -> dict
# {
#   "rsi_threshold": 32,          # 改善されたパラメータ
#   "take_profit_pct": 5.5,
#   "optimization_notes": "..."
# }
```

**フィードバックレベル:**
- **P1**: Sharpe / MDD / 勝率 / レジーム別損益
- **P2**: P1 + エグジット理由別内訳
- **P3**: P2 + 損益曲線プロット

---

### 4.12 `notion_writer.py` — Notion 書き込み

```python
write_to_notion(ticker: str, result: dict) -> dict
# {"success": True, "page_id": "abcd...", "url": "https://notion.so/..."}
```

`NOTION_API_KEY` と `NOTION_DATABASE_ID` が設定されている場合のみ動作（Add-On-Demand）。

---

### 4.13 `portfolio.py` — ポジションサイジング

```python
calculate_position_size(
    ticker: str,
    signal: str,
    capital: float,
    config: dict
) -> tuple[float, str]
# (position_size, reasoning)
```

**チェック項目:**
1. 既存保有確認（`results.json` の `holding` フラグ）
2. セクター集中度（`max_sector_exposure_pct` 超過時に縮小）

---

### 4.14 `utils.py` — ユーティリティ

```python
load_config() -> dict             # config.json を読み込む
get_ticker_config(ticker: str, config: dict) -> dict  # ティッカー別 override を適用
```

---

## 5. Streamlit UI（app.py / pages/）

### ページ構成

| ページ | ファイル | 内容 |
|---|---|---|
| メイン | `app.py` | 銘柄検索・分析実行・ダッシュボード |
| プロンプトスタジオ | `pages/01_prompt_studio.py` | プロンプト生成 + Claude 統合 UI |

### プロンプトスタジオ（01_prompt_studio.py）の 3 ステップ

1. **STEP 1** — ティッカー入力 → プロンプト自動生成
2. **STEP 2** — 生成されたプロンプトを Claude に貼り付けて手動実行
3. **STEP 3** — Claude の回答を貼り付け → `results.json` に自動保存

---

## 6. データフロー

```
INPUT: 銘柄コード（例: 7203.T）
  │
  ├─[1] データ収集（data_fetcher.py）
  │      ├─ yfinance: 株価・財務・テクニカル
  │      ├─ EDINET: 日本株有報
  │      ├─ SEC EDGAR: 米国株 10-K
  │      └─ Finnhub / RSS: ニュース
  │
  ├─[2] 競合銘柄選定（select_competitors）
  │      └─ ルールベース + Gemini 補完
  │         → direct 3 / substitute 2 / benchmark 2
  │
  ├─[3] マクロレジーム判定（macro_regime.py）
  │      └─ VIX / 金利 / 為替 → RISK_ON / NEUTRAL / RISK_OFF
  │         キャッシュ TTL=12h
  │
  ├─[4] DCF 理論株価算出（dcf_model.py）
  │      └─ 正式 WACC + PIT フィルタ
  │
  ├─[5] 4 軸スコアカード（analyzers.py）
  │      ├─ Fundamental: ROE / 利益率 / CF
  │      ├─ Valuation:  PER / PBR / DCF 乖離
  │      ├─ Technical:  RSI / MA / BB / 出来高
  │      └─ Qualitative: 有報リスク / Moat / R&D / 経営陣トーン
  │         ↓ セクター別重み × マクロレジーム調整
  │         → 総合スコア（0〜10）
  │
  ├─[6] AI 最終判断生成（analyze_all in main.py）
  │      ├─ 対戦表（4 軸比較テーブル）
  │      ├─ TEMPORAL CONSTRAINTS 注入（日付ガード）
  │      └─ Gemini / GPT-4o に送信
  │         → BUY / WATCH / SELL + 目標価格 + 損切り
  │
  └─ OUTPUT:
       ├─ data/results.json（filelock 排他書き込み）
       ├─ data/reports/{TICKER}_{DATE}.md
       ├─ Notion データベース（設定時）
       └─ Google Sheets（設定時）
```

---

## 7. 外部API・サービス一覧

| API / サービス | 用途 | 必須 | 環境変数 |
|---|---|---|---|
| **yfinance** | 株価・財務・テクニカル | ✅ | 不要 |
| **Gemini 2.5 Flash** | AI 分析・プロンプト生成・ニュース検索 | ✅ | `GEMINI_API_KEY` |
| **EDINET API v2** | 日本株有報取得 | 推奨 | `EDINET_API_KEY` |
| **SEC EDGAR** | 米国株 10-K 取得 | 推奨 | User-Agent ヘッダー |
| **Groq Llama 3** | AI 分析フォールバック | ❌ | `GROQ_API_KEY` |
| **Anthropic Claude** | 戦略最適化（推奨モデル） | ❌ | `ANTHROPIC_API_KEY` |
| **GitHub Models GPT-4o** | `--engine copilot` 時 | ❌ | `gh auth login` |
| **Finnhub** | 米国株ニュース | ❌ | `FINNHUB_API_KEY` |
| **Google News RSS** | 日本株ニュース | ✅ | 不要 |
| **Exa** | ウェブ検索（日本株補完） | ❌ | `EXA_API_KEY` |
| **Perplexity** | ニュースフォールバック | ❌ | `PERPLEXITY_API_KEY` |
| **Tavily** | ニュースフォールバック | ❌ | `TAVILY_API_KEY` |
| **Notion API** | 分析結果書き込み | ❌ | `NOTION_API_KEY`, `NOTION_DATABASE_ID` |
| **Google Sheets** | ログ出力 | ❌ | `GOOGLE_SERVICE_ACCOUNT_JSON` |
| **LINE Notify** | アラート通知 | ❌ | `LINE_NOTIFY_TOKEN` |
| **J-Quants** | 東証公式 OHLC | ❌ | `JQUANTS_API_KEY` |
| **EDINET DB** | 財務スコア・AI 分析 | ❌ | `EDINETDB_API_KEY` |

### LLM フォールバックチェーン

```
分析エンジン:
  1. Gemini 2.5 Flash（デフォルト）
     └─ --engine=copilot → GitHub Models GPT-4o
  2. フォールバック: Groq Llama 3（Gemini 429 / 503 時）
  3. 最終フォールバック: スコアカード数値のみで簡易レポート生成

API 呼び出し回数（1 銘柄あたり最大 3 回）:
  1. 競合選定（JSON 返却）
  2. 有報/10-K 解析
  3. 最終レポート生成（対戦表 + 判断）
```

---

## 8. 設定ファイル仕様

### `config.json` の主要セクション

```jsonc
{
  // 基本設定
  "spreadsheet_id": "YOUR_GOOGLE_SHEET_ID",
  "execution_cost_bps": 15,
  "benchmark_ticker": "1306.T",

  // 競合選定
  "competitor_selection": {
    "direct_count": 3,
    "substitute_count": 2,
    "benchmark_count": 2
  },

  // スコア閾値（セクター横断的なデフォルト）
  "scoring_thresholds": {
    "fundamental": {
      "cf_quality_excellent": 1.5,   // OCF/純利益 >= 1.5 で高評価
      "rd_ratio_excellent": 15       // R&D/売上 >= 15% で高評価
    },
    "valuation": {
      "dividend_yield_high": 5       // 配当利回り >= 5% で割安判定
    },
    "technical": {
      "bb_position_oversold": 10,    // BB 位置 <= 10% で売られすぎ
      "volume_ratio_spike": 2.0      // 出来高比率 >= 2.0 で出来高急増
    }
  },

  // シグナル閾値とレジーム別 override
  "signals": {
    "BUY": {
      "min_score": 6.5,
      "regime_overrides": {
        "RISK_ON":   { "min_score": 5.5 },
        "RISK_OFF":  { "min_score": 7.5 }
      }
    },
    "SELL": { "max_score": 4.0 }
  },

  // セクタープロファイル（重み + 閾値カスタマイズ）
  "sector_profiles": {
    "high_growth": { "weights": {"fundamental": 0.30, ...}, ... },
    "healthcare":  { ... },
    "value":       { ... },
    "financial":   { ... }
  },

  // トレード戦略パラメータ（LLM 最適化で更新される）
  "strategies": {
    "bounce": {
      "entry": { "rsi_threshold": 35, "bb_period": 20 },
      "exit":  { "hard_stop_pct": -2.5, "take_profit_pct": 5.0 },
      "risk":  { "pct_per_trade": 0.1, "max_positions": 2 }
    },
    "breakout": {
      "entry": { "volume_multiplier": 1.2 },
      "exit":  { "hard_stop_pct": -3.0, "take_profit_pct": 10.0 }
    }
  },

  // 銘柄別 override（特定銘柄にのみ適用）
  "ticker_overrides": {
    "8306.T": { "sector_profile": "financial", ... }
  }
}
```

---

## 9. データ構造

### `data/results.json` — 分析結果履歴

```json
{
  "7203.T": {
    "name": "Toyota Motor Corp",
    "sector": "Consumer Cyclical",
    "currency": "JPY",
    "history": [
      {
        "date": "2026-03-20 14:30",
        "scores": {
          "fundamental": 5.2,
          "valuation": 6.8,
          "technical": 4.1,
          "qualitative": 5.5
        },
        "total_score": 5.4,
        "weights": {
          "fundamental": 0.35,
          "valuation": 0.25,
          "technical": 0.20,
          "qualitative": 0.20
        },
        "signal": "WATCH",
        "entry_price": 2480.0,
        "stop_loss": 2380.0,
        "take_profit": 2680.0,
        "macro_regime": "NEUTRAL",
        "confidence": 0.72,
        "risks": ["円高リスク", "業績鈍化"],
        "catalysts": ["Q2 決算", "EV 戦略発表"],
        "holding": false,
        "analyzed_at": "2026-03-20T14:30:00+09:00",
        "prediction_accuracy": {
          "30_day":  {"predicted": "BUY",   "actual": null},
          "90_day":  {"predicted": "WATCH", "actual": null},
          "180_day": {"predicted": "WATCH", "actual": null}
        }
      }
    ]
  }
}
```

### `data/portfolio.json` — 保有銘柄台帳

```json
{
  "8306.T": {
    "qty": 100,
    "avg_price": 2450.0,
    "currency": "JPY",
    "added_at": "2026-01-15T09:00:00+09:00"
  }
}
```

### `prompts/{ticker}_context.json` — 生成プロンプト

```json
{
  "ticker": "7203.T",
  "generated_at": "2026-03-20T14:00:00+09:00",
  "prompt": "...",
  "context": {
    "metrics": { ... },
    "technical": { ... },
    "scorecard": { ... },
    "news": [ ... ]
  }
}
```

---

## 10. キャッシュ設計

| キャッシュ対象 | 場所 | TTL | キャッシュキー |
|---|---|---|---|
| マクロ指標 | インメモリ（MacroHistoryCache） | 12 時間 | — |
| EDINET 有報 | `.edinet_cache/` | 30 日 | ticker + 提出日 |
| SEC 10-K テキスト | `cache/sec_text/` | 90 日 | ticker + 提出日 |
| SEC 10-K 解析結果 | `cache/sec_analysis/` | 90 日 | ticker + 提出日 |
| スコアカード / テクニカル | `data/cache/` | — | ticker + 日付 |
| ニュース | `data/cache/news/` | 7 日 | ticker + YYYYMMDD |
| EDINET コードリスト | `.edinet_cache/` | 定期更新 | — |
| J-Quants | `.jquants_cache/` | — | — |

**キャッシュポリシー:**
- 株価データはキャッシュせずリアルタイム取得
- バックテスト時は `as_of_date` を使って過去時点のデータを参照
- 同一 10-K は初回のみ LLM 解析し、2 回目以降はゼロ API コール

---

## 11. 主要設計パターン

### 11.1 filelock 排他制御

`data/results.json` への読み書きは `filelock.FileLock` で保護。  
複数プロセスが同時に実行されても競合書き込みが発生しない。

### 11.2 PIT（Point-in-Time）フィルタ

バックテストおよび DCF 算出時、財務データは「決算発表から 45 日後に市場へ届いた」とみなす。  
`as_of_date` パラメータで過去時点を指定可能。ルックアヘッドバイアスを排除。

### 11.3 TEMPORAL CONSTRAINTS（カタリスト日付ガード）

`analyze_all()` の冒頭で今日の日付・カレント Q・次 Q を計算し、  
プロンプトに以下のブロックを注入する。

```
TEMPORAL CONSTRAINTS:
- Today: 2026-04-01
- Current Quarter: 2026-Q2
- Next Quarter: 2026-Q3
- Do NOT generate catalyst dates before 2026.
- Use "2026H2" or "Q3 2026" notation when exact dates are unknown.
```

LLM の訓練データカットオフ（2024 年）依存によるカタリスト日付の過去化を防止する。

### 11.4 セクター別スコアリング

セクタープロファイル（`config.json` の `sector_profiles`）により、  
同じ ROE 値でも「高成長 Tech」と「銀行」では評価基準が異なる。

### 11.5 マクロレジーム適応

リアルタイムで VIX / 金利 / 為替を取得してレジームを判定し、  
BUY / WATCH / SELL の閾値と 4 軸スコアの重みを動的調整する。

### 11.6 TTM（Trailing Twelve Months）EPS

EPS 算出は直近 4 四半期合計。季節性バイアスを排除。

### 11.7 フォールバックチェーン

全 API 呼び出しは「メイン → サブ → キャッシュ / 簡易レポート」の 3 段フォールバック。  
どこかで失敗しても最低限の出力を保証する。

---

## 12. テスト

### テストファイル一覧

```
tests/
├── test_analyzers.py              # 4 軸スコアリング
├── test_backtester.py             # バックテスト
├── test_data_fetcher.py           # データ取得
├── test_dcf_model.py              # DCF モデル
├── test_investment_judgment.py    # 投資判断エンジン
├── test_strategies.py             # トレード戦略
├── test_edinet.py                 # EDINET クライアント
├── test_sec_generate.py           # SEC API
├── test_select_competitors.py     # 競合選定
├── test_save_claude_result.py     # Claude 結果保存
└── test_review_issues.py          # レビュー対応確認
```

### 実行方法

```bash
# 全テスト
./venv/bin/python3 -m pytest tests/ -v

# 特定テスト
./venv/bin/python3 -m pytest tests/test_analyzers.py -k "test_scorecard"
```

---

## 13. 環境変数

`.env.example` を `.env` にコピーして設定する。

```bash
# ===== 必須 =====
GEMINI_API_KEY=your_gemini_api_key

# ===== 推奨（日本株分析に必要） =====
EDINET_API_KEY=your_edinet_api_key

# ===== 推奨（LLM 戦略最適化に必要） =====
ANTHROPIC_API_KEY=your_anthropic_api_key

# ===== 推奨（Notion 出力） =====
NOTION_API_KEY=your_notion_api_key
NOTION_DATABASE_ID=your_notion_db_id

# ===== オプション =====
GROQ_API_KEY=your_groq_api_key
EDINETDB_API_KEY=your_edinetdb_api_key
JQUANTS_API_KEY=your_jquants_api_key
FINNHUB_API_KEY=your_finnhub_api_key
EXA_API_KEY=your_exa_api_key
PERPLEXITY_API_KEY=your_perplexity_api_key
TAVILY_API_KEY=your_tavily_api_key
LINE_NOTIFY_TOKEN=your_line_notify_token
GOOGLE_SERVICE_ACCOUNT_JSON=secret/key.json
SPREADSHEET_ID=your_spreadsheet_id
```

---

## 14. 依存パッケージ

```
# データ取得
yfinance>=0.2.28

# AI / LLM
google-genai>=1.0.0      # Gemini
anthropic>=0.20.0        # Claude（戦略最適化推奨）
groq>=0.5.0              # Groq Llama 3

# UI / 出力
streamlit>=1.30.0
notion-client>=2.2.1
gspread>=5.11.0

# データ処理
pandas>=2.0.0
numpy>=1.24.0

# ドキュメント解析
pdfminer.six>=20221105

# インフラ
python-dotenv>=1.0.0
tenacity>=8.4.1
requests>=2.31.0
filelock>=3.12.0         # results.json 排他制御

# 通知
line-bot-sdk>=3.0.0
finnhub-python>=2.4.0
```

---

## 関連ドキュメント

| ファイル | 内容 |
|---|---|
| `docs/architecture.md` | コードフロー図（モジュール依存関係） |
| `docs/system_design.md` | 設計意思決定の詳細・バージョン履歴 |
| `docs/how_to_use.md` | 使い方マニュアル（ステップバイステップ） |
| `docs/investment_judgment_guide.md` | スコア・シグナルの解釈ガイド |
| `docs/YUHO_SYSTEM_DESIGN.md` | EDINET 有報システム詳細設計 |
| `AGENTS.md` | AI エージェント向け作業ルール（このリポジトリで作業する AI 必読） |

---

*Last Updated: 2026-04-01 — Generated from codebase analysis (v2.4.1)*
