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

# スイング戦略（Bounce: 逆張り / Breakout: 順張り）で分析
python main.py --ticker 7203.T --strategy bounce
python main.py --ticker 7011.T --strategy breakout
```
- **実行内容**: データの取得、DCF算出、マクロ判定、競合比較、AIレポート生成、Googleスプレッドシートへの書き出し。

### Streamlitダッシュボード
視覚的に分析結果を閲覧したい場合に使用します。

```powershell
streamlit run app.py
```
- ブラウザが起動し、銘柄コード入力欄が表示されます。
- 左側のサイドバーから過去の分析履歴を素早く確認できます。

---

## 2. バックテストの実行

過去の特定の時点から、このシステムの「4軸評価ロジック」に従って運用した場合のパフォーマンスをシミュレーションします。

### 実行コマンド
`backtest.py` を使用します。

# 例：トヨタ(7203.T)を2024年1月1日から12ヶ月間シミュレーション（長期戦略：デフォルト）
python backtest.py --ticker 7203.T --start 2024-01-01 --months 12

# 短期トレード戦略 (v1.2以前)
python backtest.py --ticker 7203.T --start 2024-01-01 --months 12 --strategy short

# スイング戦略 (v1.4)
python backtest.py --ticker 7203.T --start 2024-01-01 --months 12 --strategy bounce
python backtest.py --ticker 7011.T --start 2024-01-01 --months 12 --strategy breakout
```

### パラメータ
- `--ticker`: 分析対象の銘柄コード（例: `7203.T`, `NVDA`）
- `--start`: バックテスト開始日（`YYYY-MM-DD`）
- `--months`: シミュレーション期間（月数。デフォルトは12ヶ月）
- **--strategy**: 売買戦略を選択します。
    - `long` (デフォルト): 中長期投資。合算スコアベース。
    - `short`: 短期トレード。ATRブラケット（利確/損切り）ベース。
    - `bounce`: スイング逆張り。RSI/BB/出来高急増で判定。
    - `breakout`: スイング順張り。MAクロス/20日高値更新/出来高急増で判定。

### 結果の見方
- **地力（Fundamental）**: 財務力（ROE、自己資本比率など）
- **割安（Valuation）**: 今の株価の安さ（PER、PBR、DCFなど）
- **技術（Technical）**: エントリータイミング（RSI、移動平均乖離など）
- **シグナル**: スコア合計に基づき、BUY（購入）、WATCH（注視）、SELL（売却）を判定。
- **アルファ**: 市場平均（開始日〜終了日の株価騰落）をどれだけ上回ったかを示します。

---

## 3. 一括検証（バッチ・シミュレーション）

複数の銘柄に対して一括でバックテストを実行し、サマリーレポートを生成します。

```powershell
python batch_sim.py
```
- **出力**: `batch_sim_report.md` が生成されます。
- **用途**: 戦略の全体的な期待値や、現在の設定（パラメータ）が機能しているかを多銘柄で検証する場合に使用します。

---

## 4. 設定のカスタマイズ

`config.json` を編集することで、分析のしきい値やAIの重み付けを変更できます。

- **`signals`**: BUY/SELLと判定するスコアのしきい値。
- **`scoring`**: ROEが何%以上で「良好」とするかなどの基準。
- **`sector_profiles`**: セクターごとの「割安」や「技術」の重み付け定義。

---

## 4. トラブルシューティング
- **財務データが取得できない**: `yfinance` の制限や日本株の四半期データの欠損がある場合、システムが自動的に「通期決算データ」へ切り替えて補完します。
- **文字化け**: Windows環境では `PYTHONIOENCODING=utf-8` を設定するか、システムが組み込んだ自動エンコーディング修復機能により解消されます。
