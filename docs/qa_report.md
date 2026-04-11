# stockanalyze QAレポート

**バージョン**: v2.4.1  
**対象**: ドキュメント・CHANGELOG・実コード検証に基づく実行前レビュー  
**凡例**: ⚠️ = 重点確認箇所 ／ 🔁 = 修正済み再発リスク

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
| 8 | ⚠️🔁 RISK_OFF 時の BUY 閾値 7.5 の適用確認 | `config.json` の `regime_overrides.RISK_OFF.min_score` が 7.5 であることを確認後、テスト用に `macro_data["regime"]` を `RISK_OFF` に強制設定して `generate_scorecard()` を呼ぶ | `BUY` シグナルの閾値が 7.5 になっている | 🔁 v2.2.3 修正：`buy_threshold` が `analyze_all()` に渡されず 6.5 固定になっていたバグ。`main.py` L567-583 の経路が正しく機能しているか確認 |
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
| 5 | `--no-cache` オプション | `./venv/bin/python3 generate_prompt.py 8306.T --no-cache` | キャッシュを使わず API を呼び出す。`cache/` 配下ではなく新鮮なデータが使用される | API レート制限 (429) が発生した場合のエラーハンドリングが適切か確認 |
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
| 4 | ⚠️ ローリングバックテスト | `./venv/bin/python3 src/backtester.py AAPL --strategy long --rolling --window-months 12 --step-months 3` | 複数ウィンドウで分割実行され、各ウィンドウの統計が出力される | ウィンドウが重複する期間の処理が正しいか確認。データ取得期間が短いと一部ウィンドウがスキップされる |
| 5 | ⚠️ Sharpe Ratio 出力確認 | 上記いずれかのコマンドを実行し出力 JSON を確認 | `"sharpe_ratio"` キーが存在し数値（float）になっている | v2.1.0 追加。データ点数が少ないと標準偏差 0 で `inf` または `NaN` が発生し JSON 仕様外になる |
| 6 | ⚠️🔁 `profit_factor = Infinity` の上限変換 | 全勝ちトレードのみになるよう短期データで実行し、結果 JSON を確認 | `profit_factor` が `999.99` になっている（`Infinity` ではない） | 🔁 `backtester.py` L397 に実装済み。JSON パーサーが `Infinity` を拒否するため、この変換が欠けると結果ファイルが破損する |
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
| 2 | ⚠️ `--dry-run` が `config.json` を変更しない | `./venv/bin/python3 verify_predictions.py --dry-run` 後に `config.json` の更新日時を確認 | `config.json` のタイムスタンプが変化していない | `--dry-run` フラグが `verify_predictions.py` L141 のみで機能し、呼び出し先の `weight_optimizer.py` にも正しく伝播するか確認 |
| 3 | `--update-weights` でセクタープロファイルの重みが更新されるか | `./venv/bin/python3 src/weight_optimizer.py --update-weights` | `config.json` の `sector_profiles.*.weights` が更新される | 🔁 最適化後の重みが `min_weight` / `max_weight` 制約を遵守しているか確認する |
| 4 | ⚠️ 重み合計が 1.0 以内に収まるか | 上記実行後 `python3 -c "import json; c=json.load(open('config.json')); [print(k,sum(v['weights'].values())) for k,v in c.get('sector_profiles',{}).items()]"` | 各セクタープロファイルの重み合計が 1.0 ± 0.005 以内 | アルゴリズムは正規化を行っているはずだが、浮動小数点の丸め誤差が積み重なると外れる可能性がある |
| 5 | MIN_SAMPLES 5 件未満でのスキップ確認 | `results.json` にサンプルが 4 件以下のセクターがある状態で `src/weight_optimizer.py` を実行 | `MIN_SAMPLES (5) not met` のようなログが出力され LLM 呼び出しがスキップされる | `weight_optimizer.py` L55 に `MIN_SAMPLES = 5` として実装済み。スキップ後のデフォルト重みの維持を確認する |
| 6 | `accuracy_history.json` アトミック書き込み確認 | 実行中に Ctrl+C で強制終了し、`accuracy_history.json` が破損していないか確認 | JSON として有効なファイルが残る（途中書き込みによる破損なし） | `tempfile` + `os.replace()` でアトミック実装済み。ディレクトリ跨ぎの `os.replace()` は OS によって失敗する可能性あり |

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
| 1 | ⚠️ `--dry-run` での判定のみ実行 | `./venv/bin/python3 alert_check.py --dry-run` | トリガー判定結果が標準出力に表示される。LINE への HTTP 送信が発生しない | `send_line_notify()` の `dry_run=True` ブランチが実際に LINE API を呼ばないか確認する。`alert_check.py` L45-47 に実装済み |
| 2 | stop_loss 接近トリガー確認 | `results.json` のテストエントリで現在価格が stop_loss の 5% 以内になるよう編集後 `./venv/bin/python3 alert_check.py --dry-run` を実行 | `[ALERT] Stop Loss 接近` のようなメッセージが出力される | stop_loss 計算の基準（取得価格 vs. 現在価格）と「5% 以内」の閾値が `config.json` と一致しているか確認 |
| 3 | シグナル変化トリガー確認 | `results.json` の直近 2 エントリで signal を `BUY` → `SELL` に変化させた状態で `alert_check.py --dry-run` を実行 | シグナル変化のアラートが出力される | 直近 2 回の比較ロジックが「同一 ticker の最新 2 件」を正しく取得しているか確認する |
| 4 | スコア急落トリガー確認 | `results.json` の直近 2 エントリでスコアを 8.0 → 5.0 に変化させた状態で `alert_check.py --dry-run` を実行 | スコア急落のアラートが出力される | 急落の閾値（デルタ値）が `config.json` または `alert_check.py` のどちらで定義されているか確認する |
| 5 | LINE Notify vs Messaging API の使い分け確認 | `grep -n "LINE_NOTIFY_TOKEN\|LINE_CHANNEL_ACCESS_TOKEN" alert_check.py app.py` | `alert_check.py` は `LINE_NOTIFY_TOKEN` のみ、`app.py` は両方対応 | 2 つのスクリプトで使用する API が異なるため、`.env` に両方のトークンが揃っているか確認する |

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
| 4 | DCF `reliability` フィールドの確認 | `./venv/bin/python3 main.py 8306.T` 実行後 `python3 -c "import json; r=json.load(open('data/results.json')); [print(e.get('dcf',{}).get('reliability','MISSING')) for e in r if e.get('ticker')=='8306.T']"` | `"high"` または `"low"` が出力される（`"MISSING"` にならない） | 🔁 v2.2.1 追加。FCF が 4 期以上かつ全正の場合のみ `"high"`、それ以外は `"low"` になるか確認する |
| 5 | ティッカー正規表現バリデーション確認 | `./venv/bin/python3 main.py "../etc/passwd"` | バリデーションエラーが表示され、ファイルアクセスが発生しない | 🔁 v2.2.1 追加。正規表現が `^[A-Z0-9.^-]{1,12}$` 等で定義されているか確認する。数字のみのティッカーが誤拒否されないか確認する |
| 6 | `portfolio_manager.py` の構文エラーが他モジュールに波及しないか | `./venv/bin/python3 -c "import main; import src.data_fetcher; import src.analyzers; print('OK')"` | `OK` が出力される。`portfolio_manager` の構文エラーが他モジュールのインポートに影響しない | `portfolio_manager.py` は既知の構文エラーあり。他モジュールがこれを `import` していないことを確認済みだが、追加モジュール作成時に import しないよう注意 |
| 7 | `edinet_client.py` の循環インポート確認 | `./venv/bin/python3 -c "from src.edinet_client import fetch_securities_report; print('OK')"` | `OK` が出力される。循環インポートが発生しない | `edinet_client.py` はモジュールレベルでのインポートのみで、関数内インポートを使っていない設計。他モジュールから呼ばれる際の循環が発生していないか確認する |
| 8 | ⚠️🔁 RISK_OFF BUY 閾値 7.5 の非固定確認 | `config.json` の `signals.BUY.regime_overrides.RISK_OFF.min_score` を確認後、`main.py` L567-573 のコードを確認 | `buy_threshold` が `None` でなく `7.5` が `generate_scorecard()` に渡されている | 🔁 v2.2.3 修正。`buy_threshold` が `None` のまま渡ると `generate_scorecard()` 内でデフォルト 6.5 に戻る。`main.py` L567-583 と `analyzers.py` L1028-1029 の両方を確認する |

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
