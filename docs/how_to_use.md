# 📖 CIO Prototype ユーザー操作マニュアル

このドキュメントでは、AI投資司令塔「CIO Prototype」の使用方法について詳しく説明します。

---

## 1. 銘柄の通常分析（最新データ）

最新の株価、財務データ、有価証券報告書に基づいた総合レポートを生成します。

### CLIでの実行
最も詳細な分析を行う場合は、`main.py` を使用します。

```powershell
# 通常分析（長期戦略）
python main.py --ticker 7203.T

# 複数銘柄を一括分析
python main.py --ticker 7203.T 8306.T 9984.T

# スイング戦略（Bounce: 逆張り / Breakout: 順張り）で分析
python main.py --ticker 7203.T --strategy bounce
python main.py --ticker 7011.T --strategy breakout
```
- **実行内容**: データの取得、DCF算出、マクロ環境判定（自動）、競合比較、AIレポート生成、Googleスプレッドシートへの書き出し、ダッシュボード用JSON保存。

### Streamlitダッシュボード
視覚的に分析結果を閲覧したい場合に使用します。

```powershell
# サーバー起動
streamlit run app.py
```
- ブラウザが起動し、銘柄コード入力欄が表示されます。
- 左側のサイドバーから過去の分析履歴を素早く確認できます。

---

## 2. バックテストの実行

過去のデータを用いて、戦略の有効性をシミュレーションします。
**Point-in-Time フィルタリング**: 財務データは決算発表のラグ（基本45日）を考慮して「当時利用可能だったデータ」のみを使用し、ルックアヘッドバイアスを排除しています。

### 基本コマンド
`src.backtester` モジュールを使用します。

```powershell
# 例：トヨタ(7203.T)を2024年1月1日から12ヶ月間シミュレーション
python -m src.backtester --ticker 7203.T --start 2024-01-01 --months 12

# 戦略指定
python -m src.backtester --ticker 7203.T --start 2024-01-01 --months 12 --strategy bounce
```

### 高度なシミュレーション機能 (v2.0)


#### 🔄 ローリングバックテスト (Walk-Forward)
一定期間（ウィンドウ）ごとに期間をずらしながらテストを繰り返し、戦略の堅牢性を検証します。

```powershell
# 24ヶ月の総期間を、12ヶ月のウィンドウ、3ヶ月ステップでスライド検証
python -m src.backtester --ticker 7203.T --start 2023-01-01 --months 24 --rolling --window-months 12 --step-months 3
```

#### ⚙️ CLIパラメータ・オーバーライド
`config.json` を書き換えることなく、一時的に戦略パラメータを変更してテストできます。

```powershell
# RSI閾値を25に変更してBounce戦略を検証
python -m src.backtester --ticker 7203.T --strategy bounce --rsi-threshold 25

# 出来高急増判定を1.5倍に変更
python -m src.backtester --ticker 7203.T --strategy breakout --volume-multiplier 1.5
```

---

## 3. 設定のカスタマイズ

`config.json` を編集することで、システムの恒久的な挙動をコントロールできます。

- **`signals`**: BUY/SELL判定の閾値（Regimeごとの上書き設定も可能）。
- **`strategies`**: 各戦略のデフォルトパラメータ（RSI, 移動平均、出来高倍率など）。
- **`exit_strategy`**: 戦略ごとの損切り（Stop Loss）および利確（Take Profit）のATR倍率。
- **`sector_profiles`**: セクターごとのスコア配分（Tech銘柄ならテクニカル重視など）。
- **`position_sizing`**: 推奨ロットサイズおよびセクター集中度の最大許容範囲。

---

## 4. トラブルシューティング
- **財務データの欠損**: `yfinance` 等でデータが取得できない項目は、安全側のデフォルト値（NG判定）や通期データによる補完が自動で行われます。
- **文字化け・環境不整合**: Windows環境では、実行時に `chcp 65001` (CMD) や `$env:PYTHONUTF8=1` (PowerShell) を設定することを推奨します。
- **実行ログ**: 詳細は `System_Log` シート（スプレッドシート）には詳細なスタックトレースが最大5000文字まで記録されます。

---
*Last Updated: 2026-02-22 (v2.0.0対応)*
