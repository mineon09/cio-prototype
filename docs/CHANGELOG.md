# 変更履歴 (CHANGELOG)

本ドキュメントでは、機能追加、バグ修正、環境設定（エンコード対策等）などのすべての変更を「日付・カテゴリ・変更内容・理由」の形式で記録する。

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
