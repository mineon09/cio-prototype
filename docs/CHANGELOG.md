# 変更履歴 (CHANGELOG)

本ドキュメントでは、機能追加、バグ修正、環境設定（エンコード対策等）などのすべての変更を「日付・カテゴリ・変更内容・理由」の形式で記録する。

---

### [v2.1.0] - 2026-02-22 (External Review Fixes)
- **日付**: 2026-02-22
- **カテゴリ**: Quant Logic / Architecture / State Management
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
- **理由**: 外部AIレビュー (A/B/C パターン) で検出された全16項目の指摘事項へ完全対応。

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
