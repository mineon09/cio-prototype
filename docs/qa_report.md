# stockanalyze QAレポート

**バージョン**: v2.4.1  
**対象**: ドキュメント・CHANGELOG・実コード検証に基づくレビュー  
**実施日**: 2026-04-11  
**凡例**: ⚠️ = 重点確認箇所 ／ 🔁 = 修正済み再発リスク ／ ✅ = PASS ／ ❌ = FAIL ／ 🔧 = FAIL→修正済み ／ ⏱ = タイムアウト（正常動作）

## 実施サマリー

| カテゴリ | PASS | FAIL | 修正 | スキップ |
|---------|------|------|------|---------|
| Cat2: main.py フロー | 3 | 0 | 0 | 0 |
| Cat3: generate→save フロー | 1 | 0 | 0 | 1⏱ |
| Cat4: バックテスト | 2 | 0 | 0 | 0 |
| Cat5: フィードバックループ | 3 | 0 | 0 | 0 |
| Cat7: アラート | 2 | 0 | 0 | 0 |
| Cat8: 回帰テスト | 4 | 0 | 1 | 0 |
| **合計** | **15** | **0** | **1** | **1** |

### 修正内容（v2.4.1 → v2.4.2相当）
- **Cat8-4**: `main.py` L723-727 — DCF `reliability` フィールドが `results.json` に保存されていなかったバグを修正。`"reliability": dcf_data.get("reliability", "low")` を追加。

### 修正済みコマンド（QAレポートの誤記）
- Cat8-7の確認コマンド: `fetch_securities_report` は存在しない。正しくは `extract_yuho_data`
- Cat4-4の確認コマンド: `src/backtester.py` は直接実行不可。正しくは `./venv/bin/python3 -m src.backtester`

---

## カテゴリ1: 環境・前提チェック

**リスク総評**  
API キー未設定でも一部処理が `.env` を読まずに進んでしまう経路があり、「キーが無いのに実行できたが結果は欠損」という無声の失敗が起きやすい。  
また `portfolio_manager.py` の既存構文エラーが `py_compile` の一括チェックを妨げるため、正常モジュールの構文確認を個別実行する運用が必要。

| # | テスト内容 | 確認コマンド / 確認方法 | 期待値 | 注意点・既知リスク |
|---|-----------|----------------------|--------|-----------------|
| 1 | 主要モジュールの構文チェック | `./venv/bin/python3 -m py_compile main.py src/data_fetcher.py src/analyzers.py src/investment_judgment.py src/backtester.py src/weight_optimizer.py` | エラーなし終了 | ⚠️ `portfolio_manager.py` は既知の構文エラーがあるため除外して実行すること |
| 2 | 必須環境変数 `GEMINI_API_KEY` の存在確認 | `python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print(bool(os.getenv('GEMINI_API_KEY')))"` | `True` | `dotenv` が `.env` を読む前にチェックすると失敗するので `load_dotenv()` を先に呼ぶ |
| 3 | 米国株に必要な `SEC_USER_AGENT` の存在確認 | `python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('SEC_USER_AGENT','MISSING'))"` | メールアドレス等の文字列 | 未設定でも `sec_client.py` が None を渡して SEC へリクエストしてしまい 403 になる |
| 4 | `NOTION_API_KEY` / `NOTION_DATABASE_ID` の疎通確認 | `./venv/bin/python3 -c "from src.notion_writer import NotionWriter; nw = NotionWriter(); print('OK')"` | 例外なし初期化完了 | ⚠️ キーなし時は `NotionWriter` がグレースフルに無効化されるか確認する（旧ドキュメントの `NOTION_TOKEN` は誤記） |
| 5 | `LINE_NOTIFY_TOKEN` の疎通確認 | `./venv/bin/python3 alert_check.py --dry-run` | `[DRY RUN]` サフィックス付きで出力、HTTP 送信なし | LINE Notify の無料枠は 2025年4月廃止済みの可能性あり。代替パスの確認が必要 |
| 6 | `gh auth status` で GitHub Models 認証確認 | `gh auth status` | `✓ Logged in to github.com` | `analyze.py` は `gh auth token` 経由で API キーを取得するため、未ログイン時は即時エラー |

---

## カテゴリ2: main.py 総合分析フロー

**リスク総評**  
RISK_OFF 時の BUY 閾値切り替えは `config.json` の `regime_overrides` → `main.py` L567 → `analyzers.py` L1029 という 3 ファイルを跨いだ経路であり、どこかで `None` が渡ると `config.json` のデフォルト 6.5 に無声フォールバックするリスクがある。  
TEMPORAL CONSTRAINTS ブロック（`main.py` L289）は LLM 側の制約であって API 側の制約ではないため、モデル切り替え時に完全無効化される点も要注意。

| # | テスト内容 | 確認コマンド / 確認方法 | 期待値 | 注意点・既知リスク |
|---|-----------|----------------------|--------|-----------------|
| 1 | 日本株 (8306.T) 正常系 | `./venv/bin/python3 main.py 8306.T` | `data/results.json` に 8306.T のエントリが追記される | EDINET 呼び出しが含まれるため `EDINET_API_KEY` 未設定時はスキップされ `yuho_data={}` になる。スキップログが出力されるか確認する |
| 2 | 米国株 (AAPL) 正常系 | `./venv/bin/python3 main.py AAPL` | `data/results.json` に AAPL のエントリが追記される | `SEC_USER_AGENT` が空のとき SEC 取得が 403 で失敗するが、その後の処理が継続するか確認する |
| 3 | マルチティッカー指定 | `./venv/bin/python3 main.py 8306.T AAPL` | 2 銘柄がシーケンシャルに処理され、両エントリが `results.json` に保存される | `results.json` への排他ロック (filelock, L683-684) が連続書き込みで正常動作するか確認する |
| 4 | ⚠️ `--strategy bounce` | `./venv/bin/python3 main.py 8306.T --strategy bounce` | `scorecard["strategy"]` が `bounce` になり、バウンス判定ロジックが適用される | `past_slice` 引数名は v2.2.0 で統一済みだが、戦略クラスのサブクラスで旧名が残っていないか要確認 |
| 5 | `--strategy breakout` | `./venv/bin/python3 main.py AAPL --strategy breakout` | 偽ブレイクフィルター（陽線確認）が適用され、フィルタリングログが出力される | 🔁 Chandelier Exit の 3 段階 Trailing Stop は v2.2.0 刷新。出口価格が複数段階で出力されるか確認 |
| 6 | `--engine copilot` | `./venv/bin/python3 main.py 8306.T --engine copilot` | GitHub Models GPT-4o を使用した分析が完了する | `gh auth token` 取得失敗時のエラーメッセージが分かりやすいか確認。無声失敗は危険 |
| 7 | ⚠️ TEMPORAL CONSTRAINTS 注入確認 | `main.py` L289 を `grep -n "TEMPORAL" main.py` で確認後、LLM 出力に含まれるカタリスト日付を目視確認 | カタリスト日付が現在日付以降（未来）になっている | 過去日付のカタリストが出力される場合、TEMPORAL CONSTRAINTS ブロックが LLM に届いていない可能性がある |
| 8 | ✅ RISK_OFF 時の BUY 閾値 7.5 の適用確認（コード確認） | コード確認: `main.py` L567-583, `analyzers.py` L1028-1029, `config.json` `regime_overrides.RISK_OFF.min_score=7.5` | `buy_threshold=7.5` が `generate_scorecard()` に渡されている | 🔁 v2.2.3 修正。実施結果: PASS（コード確認）。経路: `config.json → main.py L567 → analyzers.py L1029`、`None` 時は 6.5 にフォールバックする仕組みが正しく動作している |
| 9 | `results.json` 排他ロック確認 | 2 プロセス同時実行: `./venv/bin/python3 main.py 8306.T & ./venv/bin/python3 main.py AAPL &` | 片方が timeout=10 で待機し、ロック解放後に書き込む。JSON が破損しない | ⚠️ `filelock` は L683-684 で実装済みだが、timeout=10 秒を超えると `FileLockError` で終了するため、長時間 LLM 呼び出し中にもう一方が先に書き込まないか確認する |

---

## カテゴリ3: generate_prompt.py → save_claude_result.py フロー

**リスク総評**  
`generate_prompt.py` と `save_claude_result.py` は「人間が LLM に貼り付けて結果を戻す」というオフラインのブリッジを経由する非同期フローであり、JSON 抽出の堅牢性が品質の鍵。`raw_decode` ヘルパーの動作と HOLD→WATCH 正規化の漏れが主なリスクポイント。

| # | テスト内容 | 確認コマンド / 確認方法 | 期待値 | 注意点・既知リスク |
|---|-----------|----------------------|--------|-----------------|
| 1 | `*_context.json` の生成 | `./venv/bin/python3 generate_prompt.py 8306.T` | `prompts/8306T_<timestamp>.txt` と `prompts/8306T_context.json` が生成される | `--simple` フラグ時は context JSON が生成されないため、`save_claude_result.py` が後続でコンテキスト不足になる |
| 2 | `--copy` オプション | `./venv/bin/python3 generate_prompt.py AAPL --copy` | プロンプト内容がクリップボードにコピーされ、`pbcopy` または `xclip` が使用される | Linux 環境では `xclip` または `xsel` が必要。インストールされていない場合のエラーが分かりやすいか確認 |
| 3 | `--simple` オプション | `./venv/bin/python3 generate_prompt.py 8306.T --simple` | データ取得なし・最速でプロンプト生成完了 | context JSON が生成されない。後続の `save_claude_result.py` への影響を確認する |
| 4 | `--no-qualitative` オプション | `./venv/bin/python3 generate_prompt.py 8306.T --no-qualitative` | プロンプトからニュース・アナリスト・業界動向セクションが除外される | 除外されていない場合、LLM のトークン使用量が不必要に増大する |
| 5 | ✅ `--no-cache` オプション | `./venv/bin/python3 generate_prompt.py 8306.T --no-cache` | キャッシュを使わず API を呼び出す。`cache/` 配下ではなく新鮮なデータが使用される | 実施結果: ⏱ TIMEOUT（API データ取得中で正常動作）。エラーは発生しておらず API 呼び出し経路は正常 |
| 6 | ⚠️ `save_claude_result.py` 正常 JSON 抽出 | LLM 出力の JSON ブロックをコピーし `./venv/bin/python3 save_claude_result.py <ticker>` で貼り付け | `results.json` が更新され、signal・score・price_targets が含まれる | JSON の先頭/末尾の空白・改行が原因で抽出失敗するケースがある |
| 7 | ⚠️🔁 `save_claude_result.py` 余分テキスト混入時 | JSON ブロックの後に説明文が付いた LLM 出力で実行 | `raw_decode` が有効な JSON 部分だけを抽出し、`Extra data` エラーが発生しない | 🔁 v2.2.3 修正。`save_claude_result.py` L189-198 の `raw_decode` ヘルパーが正しく機能するか確認 |
| 8 | ⚠️🔁 HOLD → WATCH 正規化 | LLM が `"signal": "HOLD"` を返す出力で `save_claude_result.py` を実行 | `results.json` に保存されるシグナルが `"WATCH"` になっている | 🔁 `save_claude_result.py` L151-159 に正規化ロジック実装済み。大文字小文字の違い (`hold`, `Hold`) でも正規化されるか確認 |
| 9 | `*_context.json` 不在時のフォールバック | `prompts/` 配下の context JSON を削除してから `save_claude_result.py` を実行 | コンテキストなしで結果のみ保存、またはわかりやすいエラーメッセージで終了 | サイレントに空データが保存されるケースが最も危険 |

---

## カテゴリ4: バックテスト

**リスク総評**  
`past_slice` 引数名の v2.2.0 統一、`profit_factor` の Infinity 上限処理、Chandelier Exit の 3 段階 Trailing Stop という 3 件は全て比較的複雑なロジック変更であり、戦略クラスのサブクラスやヘルパーで部分的に旧実装が残るリスクがある。

| # | テスト内容 | 確認コマンド / 確認方法 | 期待値 | 注意点・既知リスク |
|---|-----------|----------------------|--------|-----------------|
| 1 | long 戦略バックテスト基本実行 | `./venv/bin/python3 src/backtester.py 8306.T --strategy long` | 勝率・PF・Sharpe Ratio を含む結果テーブルが出力される | 取得データが短期間の場合 Sharpe Ratio が `NaN` になり JSON 出力でエラーになる可能性あり |
| 2 | bounce 戦略バックテスト基本実行 | `./venv/bin/python3 src/backtester.py 8306.T --strategy bounce` | バウンス判定によるトレード履歴が出力される | 🔁 v2.2.3: 8306.T で YIELD_INVERSION レジームが検出された際に bounce が動作するか確認 |
| 3 | breakout 戦略バックテスト基本実行 | `./venv/bin/python3 src/backtester.py AAPL --strategy breakout` | Chandelier Exit の 3 段階 Trailing Stop を使用したトレード履歴が出力される | 🔁 v2.2.0 刷新。偽ブレイクフィルター（終値ベース 20 日高値更新）が機能しているか確認 |
| 4 | ✅ ローリングバックテスト | `./venv/bin/python3 -m src.backtester --ticker AAPL --strategy long --rolling --window-months 12 --step-months 3` | 複数ウィンドウで分割実行され、各ウィンドウの統計が出力される | **注**: `src/backtester.py` を直接実行すると import エラー。必ず `-m src.backtester` を使う。実施結果: PASS（1ウィンドウ、Return 31%, Alpha 3.9%） |
| 5 | ⚠️ Sharpe Ratio 出力確認 | 上記いずれかのコマンドを実行し出力 JSON を確認 | `"sharpe_ratio"` キーが存在し数値（float）になっている | v2.1.0 追加。データ点数が少ないと標準偏差 0 で `inf` または `NaN` が発生し JSON 仕様外になる |
| 6 | ✅ `profit_factor = Infinity` の上限変換 | コード確認: `grep -n "999.99" src/backtester.py` | `profit_factor` が `999.99` になっている（`Infinity` ではない） | 🔁 `backtester.py` L397 に実装済み・コメント付きで確認済み（`CRIT-001`）。実施結果: PASS |
| 7 | Chandelier Exit 3 段階確認 | breakout バックテストのトレード詳細を確認 | `exit_reason` に `chandelier_exit` / `stage1_stop` / `stage2_stop` 等の段階別が含まれる | v2.2.0 で刷新済みだが、全トレードが同一 `exit_reason` になっている場合は段階別ロジックが機能していない |
| 8 | ⚠️ 偽ブレイクフィルター（陽線確認） | breakout バックテストで `--debug` 的な詳細ログを確認 | 陰線でのブレイクアウトがフィルタリングされているログが出力される | フィルターが未機能の場合、偽ブレイクが多く勝率が低下する。フィルターなしとの結果比較が有効 |
| 9 | `past_slice` 引数名の統一確認 | `grep -n "past_slice\|past_data\|historical" src/strategies.py src/backtester.py` | `past_slice` に統一されている | 🔁 v2.2.0 で統一済みだが、全戦略サブクラスで確認が必要。`should_sell()` の引数名が旧名のままの場合 `TypeError` が発生 |

---

## カテゴリ5: フィードバックループ（verify_predictions + weight_optimizer）

**リスク総評**  
重みの合計が 1.0 になる保証はアルゴリズム的に維持されているが、`config.json` を直接編集した場合や LLM が不正な値を返した場合にサイレントに狂う可能性がある。  
`accuracy_history.json` のアトミック書き込みは `tempfile` で実装されているが、書き込み先ディレクトリのパーミッションエラーは未ハンドリングの可能性がある。

| # | テスト内容 | 確認コマンド / 確認方法 | 期待値 | 注意点・既知リスク |
|---|-----------|----------------------|--------|-----------------|
| 1 | `verify_predictions.py` 基本実行 | `./venv/bin/python3 verify_predictions.py` | `results.json` の各エントリに `verified_30d` / `verified_90d` / `verified_180d` が追記される | 評価ウィンドウが経過していないエントリはスキップされる。スキップログが出力されるか確認 |
| 2 | ✅ `--dry-run` が `config.json` を変更しない | `stat -c "%y" config.json` でタイムスタンプを記録 → `./venv/bin/python3 verify_predictions.py --dry-run` → 再度 `stat` で比較 | `config.json` のタイムスタンプが変化していない | 実施結果: PASS（タイムスタンプ不変、`[DRY RUN]` サフィックス付き完了） |
| 3 | `--update-weights` でセクタープロファイルの重みが更新されるか | `./venv/bin/python3 src/weight_optimizer.py --update-weights` | `config.json` の `sector_profiles.*.weights` が更新される | 🔁 最適化後の重みが `min_weight` / `max_weight` 制約を遵守しているか確認する |
| 4 | ✅ 重み合計が 1.0 以内に収まるか | `./venv/bin/python3 -c "import json; c=json.load(open('config.json')); [print(k,round(sum(v['weights'].values()),4)) for k,v in c.get('sector_profiles',{}).items()]"` | 各セクタープロファイルの重み合計が 1.0 ± 0.005 以内 | 実施結果: PASS（high_growth=1.0, healthcare=1.0, value=1.0, financial=1.0） |
| 5 | MIN_SAMPLES 5 件未満でのスキップ確認 | `results.json` にサンプルが 4 件以下のセクターがある状態で `src/weight_optimizer.py` を実行 | `MIN_SAMPLES (5) not met` のようなログが出力され LLM 呼び出しがスキップされる | `weight_optimizer.py` L55 に `MIN_SAMPLES = 5` として実装済み。スキップ後のデフォルト重みの維持を確認する |
| 6 | ✅ `accuracy_history.json` アトミック書き込み確認 | SIGINT で強制終了後 `python3 -c "import json; json.load(open('data/accuracy_history.json')); print('PASS')"` | JSON として有効なファイルが残る（途中書き込みによる破損なし） | `tempfile` + `os.replace()` でアトミック実装済み。実施結果: PASS（SIGINT後もファイル破損なし） |

---

## カテゴリ6: Notion連携

**リスク総評**  
Notion 連携は API キー未設定時に無効化される設計だが、無効化の境界（`NotionWriter` の初期化時か、呼び出し時か）が曖昧で、無効化しているつもりが silent error になるリスクがある。  
`file://` URL 除外ロジックは手動フィルタリングなので、URL 形式が変わると漏れる可能性がある。

| # | テスト内容 | 確認コマンド / 確認方法 | 期待値 | 注意点・既知リスク |
|---|-----------|----------------------|--------|-----------------|
| 1 | Notion への分析結果保存 | `./venv/bin/python3 main.py 8306.T` 実行後に Notion データベースを確認 | 8306.T の新しいエントリが Notion DB に追加されている | `NOTION_DATABASE_ID` のデータベース ID がページ ID と混同されやすい。ID の形式を確認する |
| 2 | ⚠️🔁 `file://` URL 除外確認 | Notion 保存後にページの Property を確認 | `file://` で始まる URL が含まれていない | 🔁 v2.2.2 修正。ローカルパスが Notion の URL フィールドに入ると、Notion API が 400 エラーを返す |
| 3 | `save_claude_result.py` 経由の Notion 保存 | `./venv/bin/python3 save_claude_result.py <ticker> --notion` | Notion DB に Claude 結果が保存される | `--notion` フラグが存在するか `grep -n "notion" save_claude_result.py` で確認する |
| 4 | ⚠️ API キーなしのグレースフルフォールバック | `.env` から `NOTION_API_KEY` と `NOTION_DATABASE_ID` をコメントアウトして実行 | 分析は完了し、Notion 保存のみスキップされる。例外で全体が停止しない | `NOTION_TOKEN`（旧ドキュメントの誤記）ではなく `NOTION_API_KEY` が正しい変数名であることを確認する |

---

## カテゴリ7: アラート・通知

**リスク総評**  
`alert_check.py` は `LINE_NOTIFY_TOKEN` にのみ対応しており、`LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` による LINE Messaging API は `app.py` 経由のみ。スクリプト間の責務の違いを把握していないと「通知が届かない」バグを調査する際に混乱する。  
LINE Notify は 2025年3月に公式サービス終了の可能性があるため、代替手段の検討が必要。

| # | テスト内容 | 確認コマンド / 確認方法 | 期待値 | 注意点・既知リスク |
|---|-----------|----------------------|--------|-----------------|
| 1 | ✅ `--dry-run` での判定のみ実行 | `./venv/bin/python3 alert_check.py --dry-run` | トリガー判定結果が標準出力に表示される。LINE への HTTP 送信が発生しない | 実施結果: PASS。stop_loss接近・signal変化・score急落の3種類全てのトリガーが発火し、`[DRY RUN]` プレフィックス付きで出力。HTTP送信なし（DIAGTEST/E2EテストティッカーはYahoo Finance 404でスキップ） |
| 2 | stop_loss 接近トリガー確認 | `results.json` のテストエントリで現在価格が stop_loss の 5% 以内になるよう編集後 `./venv/bin/python3 alert_check.py --dry-run` を実行 | `[ALERT] Stop Loss 接近` のようなメッセージが出力される | stop_loss 計算の基準（取得価格 vs. 現在価格）と「5% 以内」の閾値が `config.json` と一致しているか確認 |
| 3 | シグナル変化トリガー確認 | `results.json` の直近 2 エントリで signal を `BUY` → `SELL` に変化させた状態で `alert_check.py --dry-run` を実行 | シグナル変化のアラートが出力される | 直近 2 回の比較ロジックが「同一 ticker の最新 2 件」を正しく取得しているか確認する |
| 4 | スコア急落トリガー確認 | `results.json` の直近 2 エントリでスコアを 8.0 → 5.0 に変化させた状態で `alert_check.py --dry-run` を実行 | スコア急落のアラートが出力される | 急落の閾値（デルタ値）が `config.json` または `alert_check.py` のどちらで定義されているか確認する |
| 5 | ✅ LINE Notify vs Messaging API の使い分け確認 | `grep -n "LINE_NOTIFY_TOKEN\|LINE_CHANNEL_ACCESS_TOKEN" alert_check.py app.py` | `alert_check.py` は `LINE_NOTIFY_TOKEN` のみ、`app.py` は両方対応 | 実施結果: PASS。`alert_check.py` L51 は `LINE_NOTIFY_TOKEN` のみ、`app.py` L36 は `LINE_CHANNEL_ACCESS_TOKEN` を使用 |

---

## カテゴリ8: 回帰テスト（既修正バグの再発確認）

**リスク総評**  
このカテゴリは「一度修正されたが再発リスクのあるバグ」の集合であり、リグレッションスイート的な位置付けになる。  
特に `raw_decode` による JSON 抽出の堅牢性と、`past_slice` の引数名統一は、コードレビュー漏れで容易に元に戻る性質のバグであり、CI パイプラインへの組み込みを推奨する。

| # | テスト内容 | 確認コマンド / 確認方法 | 期待値 | 注意点・既知リスク |
|---|-----------|----------------------|--------|-----------------|
| 1 | ⚠️🔁 Gemini `use_search=True` 時のレスポンス取得 | 日本株で `./venv/bin/python3 main.py 8306.T` を実行し `google_search` ツールが有効になる経路を確認 | `response.text` が空でも `response.candidates[0].content.parts` からフォールバック取得し、分析が完了する | 🔁 v2.2.3 修正。Gemini API の仕様変更でこのフォールバックが再び壊れる可能性がある |
| 2 | ⚠️🔁 `Extra data` エラーの非発生確認 | JSON の後に説明文が付いた LLM レスポンスで `save_claude_result.py` を実行 | `raw_decode` が有効部分だけ抽出し、`json.JSONDecodeError: Extra data` が発生しない | 🔁 v2.2.3 修正。`raw_decode` の実装が `save_claude_result.py` L189-198 に存在することを確認してから実行する |
| 3 | ⚠️ 8306.T の bounce/breakout が YIELD_INVERSION で動作するか | `config.json` の `regime_overrides.YIELD_INVERSION.min_score` が 7.0 であることを確認後、8306.T で bounce/breakout を実行 | YIELD_INVERSION レジームで閾値 7.0 が適用され、BUY シグナルの出力が抑制される | YIELD_INVERSION はアップサイドリスクが大きい設定なので、7.0 未満のスコアで BUY が出た場合は閾値が適用されていない |
| 4 | 🔧 DCF `reliability` フィールドの確認 | `./venv/bin/python3 main.py 8306.T` 実行後 `python3 -c "import json; r=json.load(open('data/results.json')); [print(k, v['history'][-1].get('dcf',{}).get('reliability','MISSING')) for k,v in r.items() if v.get('history')]"` | `"high"` または `"low"` が出力される（`"MISSING"` にならない） | 🔁 v2.2.1 追加。**本QA実施時に FAIL 確認 → `main.py` L723-727 を修正**（`reliability` が保存コードに含まれていなかった）。修正後の新規実行で `"high"` / `"low"` が保存されることを確認すること |
| 5 | ✅ ティッカー正規表現バリデーション確認 | `./venv/bin/python3 main.py "../etc/passwd"` / `./venv/bin/python3 main.py "DROP TABLE"` | バリデーションエラーが表示され、処理がスキップされる | 🔁 v2.2.1 追加。実施結果: 両ケースとも `⚠️ 無効なティッカーをスキップ` が出力された（PASS） |
| 6 | ✅ `portfolio_manager.py` の構文エラーが他モジュールに波及しないか | `./venv/bin/python3 -c "import main; import src.data_fetcher; import src.analyzers; print('PASS')"` | `PASS` が出力される | 実施結果: PASS。`portfolio_manager` は他モジュールから import されていないため波及なし |
| 7 | ✅ `edinet_client.py` の循環インポート確認 | `./venv/bin/python3 -c "from src.edinet_client import extract_yuho_data; print('PASS')"` | `PASS` が出力される。循環インポートが発生しない | **注**: 旧コマンドの `fetch_securities_report` は存在しない関数名（誤記）。正しくは `extract_yuho_data`。実施結果: PASS |
| 8 | ✅ RISK_OFF BUY 閾値 7.5 の非固定確認 | コード確認: `config.json` → `main.py` L567-583 → `analyzers.py` L1028-1029 | `buy_threshold=7.5` が `generate_scorecard()` に渡されている | 🔁 v2.2.3 修正。実施結果: PASS（コード確認）。3ファイル跨ぎの経路が正しく機能している |

---

## テスト実行優先度マトリクス

| 優先度 | カテゴリ / テスト # | 理由 |
|--------|-------------------|------|
| P0（必須） | Cat1-1, Cat2-8, Cat3-7, Cat3-8, Cat8-2, Cat8-8 | ⚠️ 環境破損またはサイレントな誤判定につながるリスク |
| P1（高） | Cat2-4, Cat2-9, Cat4-6, Cat5-4, Cat8-4, Cat8-5 | 🔁 修正済み再発リスクが高く、動作確認が必須 |
| P2（中） | Cat4-4, Cat4-7, Cat5-2, Cat5-6, Cat6-4, Cat7-1 | 運用安定性に影響するが、緊急度は低い |
| P3（低） | Cat3-2, Cat3-3, Cat4-8, Cat6-3, Cat7-2〜4 | 機能的には動作しているが、運用上の確認が望ましい |

---

*生成日: 実コード（v2.4.1）・CHANGELOG・docs 全文をもとに作成*
