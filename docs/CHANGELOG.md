# 変更履歴 (CHANGELOG)

本ドキュメントでは、機能追加、バグ修正、環境設定（エンコード対策等）などのすべての変更を「日付・カテゴリ・変更内容・理由」の形式で記録する。

---

## [v2.4.2] - 2026-05-04 (app.py ニュース未取得・DCF表示バグ修正)

### バグ修正
- **ニュースが「ニュースなし」になる問題を修正** (`app.py`):
  - `app.py` の分析フローに `fetch_all_news` 呼び出し（Step 3.5）が欠けており、Streamlit GUI 経由での分析でニュースが常に空になっていた
  - `main.py` の `run()` には実装済みだったが、`app.py` → `analyze_all()` ルートでは呼ばれていなかった
- **DCF 現在株価が $0 になるバグを修正** (`main.py`):
  - `save_to_dashboard_json()` の DCF 保存ブロックに `current_price` / `margin_of_safety` / `scenarios` キーが欠落しており、ダッシュボードで「現在株価 $0」「安全域 0%」が表示されていた
  - これらのフィールドを `dcf_data` から正しく保存するよう修正
- **`macro.description` キー欠落を修正** (`main.py`):
  - `save_to_dashboard_json()` は `detail` キーで保存していたが、`app.py` 表示側は `description` を参照しており不一致だった
  - `description` キーを追加（`detail` は後方互換のために残存）
- **`analyze_all()` に `macro_data` / `dcf_data` が未渡しだった問題を修正** (`app.py`):
  - Streamlit GUI からのレポート生成時にマクロ環境・DCF情報がプロンプトに含まれておらず、分析精度が低下していた

### 理由
AMAT の分析結果でニュースが取得されず「センチメント: 中立 (ニュースなし)」となり、DCF 現在株価が $0 になるという報告を受けて調査・修正。`app.py` と `main.py` の処理フローが乖離していたことが根本原因。

---

## [v2.4.1] - 2026-03-27 (カタリスト日付ガード・ドキュメント全面刷新)

### バグ修正
- **カタリスト日付の過去化防止**: `main.py` の `analyze_all()` 冒頭に `TEMPORAL CONSTRAINTS` ブロックを注入
  - `_today / _current_year / _current_quarter / _next_quarter` を計算してプロンプトに埋め込み
  - LLMが訓練データカットオフ（2024年）でカタリストを生成するのを防止
- **カタリスト年の動的注入**: `generate_prompt.py` の JSON テンプレートにも同様の年度注入を実装
- **ダッシュボードのティッカー2重入力解消**: Prompt Studio ページのティッカー入力バグを修正

### 改善
- **ニュース取得**: `src/news_fetcher.py` で過去 14 日分のニュースを取得（yfinance + Gemini google_search）
- **Notion AI 回答保存**: Copilot/Claude の回答を Notion に自動保存

### ドキュメント
- **`docs/architecture.md`**: 現在の `main.py` ベースのアーキテクチャに全面刷新。全 23 モジュールの一覧・LLM フォールバック・TEMPORAL ガードの仕組みを追記
- **`docs/system_design.md`**: v2.4.1 まで変更履歴を更新。投資判断エンジン詳細・インフラ情報を追記
- **`docs/how_to_use.md`**: `--engine copilot` オプションをCLI例に追記

### 理由
`industry_trends.py` は前回修正済みだったが `main.py` の `analyze_all()` 内のプロンプトには今日の日付が注入されていなかった。LLM のカットオフ依存を根本解消するため TEMPORAL CONSTRAINTS ブロックを追加。

---

## [v2.4.0] - 2026-03-15 (投資判断エンジン導入)

### 新規機能
- **投資判断エンジン**: `src/investment_judgment.py` 新設
  - API ベースエンジン（Gemini/Qwen 対応）
  - ツールベースエンジン（ルールベース）
  - デュアルエンジン（比較・統合）
- **比較レポート機能**: 2 つのエンジンの結果を比較・表示
- **単体テスト**: `tests/test_investment_judgment.py` (24 テスト)

### 改善
- **ドキュメント**: `docs/investment_judgment_guide.md` 追加
  - 使用ガイド・API リファレンス
  - 統合例・カスタマイズ方法

### テスト結果
```
Ran 24 tests in 0.033s
OK
```

---

## [v2.3.0] - 2026-03-15 (コード品質改善・単体テスト導入)

### 概要
外部レビュー指摘事項に基づくコード品質改善。単体テストの導入、設定ファイルの整理、ドキュメントの拡充を実施。

### 新規機能
- **単体テストフレームワーク導入**: `tests/` ディレクトリ新設
  - `test_analyzers.py`: 4 軸スコアリングエンジンのテスト（30 テスト）
  - `test_strategies.py`: 戦略ロジックのテスト（17 テスト）
  - `test_dcf_model.py`: DCF 理論株価算出のテスト（19 テスト）
  - 合計 66 テスト、カバレッジ：コアロジックの主要関数を網羅

### 改善
- **API キー管理の明確化**: `.env.example` を刷新
  - 各 API キーの取得元 URL を記載
  - Google Sheets 認証の 2 方法（JSON 文字列 vs ファイルパス）を明記
  - EDINET_API_KEY を追加
  - セクション別に見やすく整理

- **スコアリング閾値の外部化**: `config.json` に `scoring_thresholds` セクション追加
  - CF 品質閾値（excellent/good/fair）
  - R&D 比率閾値
  - 配当利回り閾値
  - BB 位置閾値
  - 出来高比率閾値
  - `analyzers.py` は config から読み込み（フォールバック値付き）

- **ロギングシステムの改善**: `src/logging_utils.py` 新設
  - 統一ログフォーマット
  - 名前付きロガー
  - ファイルハンドラー追加機能
  - `analyzers.py` で使用開始

- **パフォーマンス最適化**: `src/parallel_utils.py` 新設
  - 複数銘柄データ取得の並列処理（ThreadPoolExecutor）
  - `main.py` の競合他社データ取得に適用（最大 4 ワーカー）
  - エラーハンドリング付きフォールバック機構

### ドキュメント
- **レビュー指摘事項対応レポート**: `docs/issues/review_fixes_v2.3.0.md`
  - 外部レビューでの指摘事項と対応内容を記録
  - 各変更の理由とテスト結果を記載

### テスト結果
```
Ran 66 tests in 2.856s
OK
```

---

## [v2.2.3] - 2026-03-10 (ログ精査バグ修正)

- **google_search レスポンス取得修正**: `call_gemini` で `use_search=True` 時に `response.text` が空になる問題を修正。`response.candidates[0].content.parts` からテキストを結合取得するフォールバック追加 (`data_fetcher.py`)
- **JSONパースの堅牢化**: GeminiがJSONの後に余分なテキストを返した場合（`Extra data` エラー）に対応するため、`raw_decode` を用いた `_extract_json` ヘルパーを追加 (`data_fetcher.py`)
- **スコア制約の厳格化**: 分析プロンプトにて「上方修正に限定せず、上下いずれの数値修正も禁止」することを明記し、スコア上書きを完全に抑制 (`main.py`)
- **RISK_OFF BUY閾値適用**: `main.py` の `generate_scorecard` 呼び出しで `buy_threshold` が渡されず、RISK_OFF の閾値 7.5 が無視されていた問題を修正。regime_overrides から閾値を解決して渡すように変更
- **定性スコア重み 0% は仕様通り**: 有報/10-Kデータ未取得時に qualitative ウェイトを 0% に再配分するのは設計意図通りの動作（`analyzers.py` L843-848）

---

## [v2.2.2] - 2026-03-05 (パフォーマンス改善・ニュース対応)

- **EDINET found_doc キャッシュ**: 銘柄ごとに有報検索結果をキャッシュし150日フルスキャン回避（30日有効）
- **Notion MD Link 除外**: `file://` URL を Notion API が拒否するため送信データから除外
- **Gemini デフォルト 2.5-flash**: quota 枯渇フォールバック遅延を回避
- **yfinance ニュース取得**: ハードコード空配列 → 7日以内のニュースを動的取得（米国株対応）
- **日本株 google_search 有効化**: yfinance ニュースが日本株で空のため、Gemini に `google_search` ツールを有効化
- **スコア制約プロンプト強化**: 変更時に `(提供スコア X に対し、[理由] により Y に修正)` 形式を強制、上方修正は数値根拠必須

---

### [v2.2.1] - 2026-03-04 (ログ精査4件修正)

- **日付**: 2026-03-04
- **カテゴリ**: Bug Fix / Prompt Engineering / DCF Model
- **変更内容**:
  - 🔴 **ティッカー誤パース防止**: `main.py` の argparse にティッカー正規表現バリデーション追加（パスやコマンドの誤混入を防止）
  - 🔴 **DCF信頼度フラグ**: `dcf_model.py` に `reliability` フィールド追加（FCF 4期以上＆全正: high、それ以外: low）。成長率クランプ（-5%〜25%）も追加
  - 🟡 **マクロ文脈注入**: `analyze_all` プロンプトに `【マクロ環境と判断指針】` セクション追加（VIX/金利/ドル円の解釈指示）。ニュース空でもマクロから推論させる指示付き
  - 🟡 **スコア乖離制約強化**: プロンプトの `【スコア制約（厳守）】` で4軸スコアを ±1.0 以内に制限、旧「一致不要」文言を削除
  - `analyze_all` シグネチャに `macro_data`, `dcf_data` 引数を追加
- **理由**: ログ精査で発見された4件の問題（ティッカー誤検知、AMAT DCF $63、ニュース空でセンチメント形骸化、スコア乖離）への対応。

---

### [v2.2.0] - 2026-03-04 (Breakout Strategy Alpha改善)

- **日付**: 2026-03-04
- **カテゴリ**: Strategy / Quant Logic / Code Quality
- **変更内容**:
  - **Exit戦略改善**: `BreakoutStrategy.should_sell` を全面刷新
    - Chandelier Exit 導入（最新ATRベースの段階的Trailing Stop: tight/mid/loose 3段階）
    - Death Cross 条件厳格化（MA5/MA25 → MA10/MA20 + 終値がMA長期を下回る条件追加）
    - ATR Stop を 2.0 → 3.0 に拡大（初動ボラティリティ対応）
    - Take Profit 上限を 8.0% → 10.0% に引き上げ
  - **Entry精度向上**: `BreakoutStrategy.analyze_entry` に偽ブレイクフィルター追加
    - 陽線確認（Close > Open）で上ヒゲ・陰線スパイクを排除
    - 終値ベース20日高値更新チェック（ヒゲ先ブレイクの排除）
  - **コード品質**: `should_sell` の引数 `daily_data` → `past_slice` に統一（全戦略クラス + backtester.py 呼び出し元）
  - **FutureWarning対応**: `macro_regime.py` の `yf.download` から `auto_adjust=True` を除去
  - `config.json`: `chandelier_tight_mult`, `chandelier_mid_mult`, `chandelier_loose_mult`, `ma_short`, `ma_long`, `require_bullish_close` を追加
- **理由**: Payoff Ratio ≒ 1.0、WinRate 50% のベースライン改善。Chandelier Exit でトレンド追随力を強化し、偽ブレイク排除でエントリー精度を向上させ、インデックス対比Alpha改善を図る。

---

### [v2.1.1] - 2026-02-22 (8306.T Strategy Fix)

- **日付**: 2026-02-22
- **カテゴリ**: Config Fix / Backtest Accuracy
- **変更内容**:
  - 8306.T bounce: `enabled_regimes` に `YIELD_INVERSION` を追加、`fundamental_min` を 5.0 → 4.0 に緩和
  - 8306.T breakout: `enabled: false` を撤廃し有効化、`enabled_regimes` に `YIELD_INVERSION` を追加、`fundamental_min` を 4.0 に設定
  - Issue #05 として原因分析ドキュメント作成 (`docs/issues/05_8306T_bounce_block.md`)
- **理由**: 2024年のYIELD_INVERSION レジーム期間中、bounce/breakout 両戦略が8306.Tで0トレードとなる問題を解消（レジームフィルター + ファンダメンタル閾値 + enabled:false の多段ブロック）。根本解決（案C: 日本株用マクロ判定分離）は別Issueとして管理。

---

### [v2.1.0] - 2026-02-22 (External Review Fixes + Hotfix)

- **日付**: 2026-02-22
- **カテゴリ**: Quant Logic / Architecture / State Management / Bug Fix
- **変更内容**:
  - **B-1a**: PIT EPS計算を単四半期×4 → TTM (Trailing 12 Months) に変更 (`data_fetcher.py`)
  - **B-1b**: yfinance 分割調整株価の制限事項を明記 (`data_fetcher.py`)
  - **B-1c**: `_get_fcf_history()` に PIT (Point-In-Time) フィルタ追加 (`dcf_model.py`)
  - **B-2**: WACC を Cost of Equity → 正式 WACC (負債コスト込み) に修正 (`dcf_model.py`)
  - **B-3**: モンテカルロに `position_pct` を反映 (`backtester.py`)
  - **B-4**: ローリングバックテストに Sharpe Ratio 集計追加 (`backtester.py`)
  - **A-1**: `detect_regime()` 失敗時の `UNAVAILABLE` 初期値で NEUTRAL と区別 (`main.py`)
  - **A-2**: マクロキャッシュを `MacroHistoryCache` クラスに (TTL + clear()) (`macro_regime.py`)
  - **A-3**: `extract_yuho_data()` に try/except 追加 (`main.py`)
  - **A-4**: `_determine_regime()` RATE_HIKE/CUT 判定を bps 差分にし、VIX との優先度を整理 (`macro_regime.py`)
  - **C-1**: `holding` / `position_size` を `results.json` に書き込み (`main.py`)
  - **C-2**: Sheets シグナルを scorecard 優先に変更 (`sheets_writer.py`)
  - **C-3**: `results.json` に `filelock` 排他ロック追加 (`main.py`)
  - **C-5**: System_Log ワークシート行数 1000→10000 (`sheets_writer.py`)
  - `filelock>=3.12.0` を `requirements.txt` に追加
  - **Hotfix**: `save_to_dashboard_json()` 内の `new_entry` 未定義 NameError を修正 (`main.py`)
  - **Hotfix**: `json.dump` に numpy型安全化ハンドラ `_json_safe` を追加 (`main.py`)
- **理由**: 外部AIレビュー (A/B/C パターン) で検出された全16項目の指摘事項へ完全対応 + 実行時検証で発見した2件のhotfix。

---

### [v2.0.0] - 2026-02-22 (Cleanup)

- **日付**: 2026-02-22
- **カテゴリ**: Cleanup / DevOps
- **変更内容**:
  - 不要ファイル14件を削除（旧 `backtest.py`、テスト出力txt x3、ログ x3、検証スクリプト x3、旧レビュー資料 x2、一時DB）
  - `.gitignore` を強化（`.edinet_cache/`、`data/*.db`、`test_*.txt`、`verify_*.py`、`.streamlit/secrets.toml` 等を追加）
  - `git rm --cached` で不要ファイルのトラッキングを解除
- **理由**: リポジトリの可読性向上と、機密情報・一時ファイルの漏洩防止。

---

### [v2.0.0] - 2026-02-22

- **日付**: 2026-02-22
- **カテゴリ**: Bug Fix / Security / Architecture / Quality
- **変更内容**:
  - CRIT-001: `backtester.py` の `profit_factor` が `Infinity`（JSON仕様外）を出力する問題を修正 → `999.99` に変更
  - CRIT-002: `main.py` L51 の文字化けコメント（`ï¼ˆ`）を正しいUTF-8に修正
  - CRIT-003: `portfolio.py` の BUY シグナル=保有中という誤った前提を修正。明示的な `holding` フラグを参照する設計に改善
  - CRIT-005: `data_fetcher.py` の `rd_ratio = 0` 固定に意図を明記するコメント追加
  - HIGH-001: `dcf_model.py` の中国語コメント `企业价值` → `企業価値` に修正
  - HIGH-002: `dcf_model.py` の WACC 計算をハードコードから `macro_regime` のリアルタイム金利対応に改善
  - HIGH-004: `edinet_client.py` のモジュールレベル循環インポートを関数内インポートに変更
  - HIGH-005: `main.py` の `analyze_all` 戻り値型ヒントを `tuple[str, str]` → `tuple[str, str, str]` に修正
  - HIGH-007: `sheets_writer.py` の `write_system_log` メッセージ切り捨て上限を 1000 → 5000 文字に拡大
  - IMP-002: `dcf_model.py` の `estimate_fair_value` 失敗時にログ出力を追加
  - IMP-006: `edinet_client.py` の未使用 `TypedDict` import を削除
  - DESIGN-003: `main.py` の `run_strategy_analysis` 内の関数レベル import をモジュールレベルに移動
  - DESIGN-004: `requirements.txt` に依存ライブラリのバージョン上限を追加
- **理由**: 厳格レビュー（v1.5.1 採点レポート）で指摘された致命的・重大問題を全件修正し、プロダクション品質に近づけるため。

---

### [Unreleased]

- **日付**: 2026-02-22
- **カテゴリ**: Documentation / Setup
- **変更内容**: `docs/architecture.md` の新規作成と次期開発方針の策定。
- **理由**: システムの全体設計、データフロー、GitHub Actions等のトリガー条件の最新状態を可視化し、今後の堅牢化開発の指針とするため。

---

### [v1.5.1] - 2025-02

- **日付**: 2025-02
- **カテゴリ**: Bug Fix / Optimization
- **変更内容**: モンテカルロのブートストラップ化、オーケストレーション修正、型安全性の強化、安全側デフォルトの徹底。
- **理由**: バックテストの精度向上と、v2.0 Review対応における運用上の安定性の確保。

---

*(これ以前の履歴については、設計書の初期バージョンからの引き継ぎ)*
