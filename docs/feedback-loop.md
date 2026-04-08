# 予測フィードバックループ

## 概要

`verify_predictions.py` が蓄積した「シグナル vs 実績」データをもとに、`src/weight_optimizer.py` が LLM に重みの最適化を依頼し、`config.json > sector_profiles[X].weights` を自動更新するループ。

```
verify_predictions.py ─── results.json（verified_*d 追記）
        │
        └── store_accuracy_history() ─── data/accuracy_history.json
                │
                └── --update-weights ──▶ src/weight_optimizer.py
                                               │
                                               ├── compute_axis_correlations()
                                               ├── build_weight_proposal_prompt()
                                               ├── LLM（Claude / Gemini）
                                               ├── parse_weight_proposal()
                                               ├── validate_weights()
                                               └── save_config() ──▶ config.json
```

---

## 使い方

```bash
# 1. 検証のみ（results.json に verified_*d を追記）
./venv/bin/python3 verify_predictions.py

# 2. 検証 + 精度履歴蓄積 + 重み自動更新
./venv/bin/python3 verify_predictions.py --update-weights

# 3. 重み最適化のみ（dry-run：config.json は変更しない）
./venv/bin/python3 src/weight_optimizer.py --dry-run

# 4. 特定セクタープロファイルのみ更新
./venv/bin/python3 src/weight_optimizer.py --sector high_growth

# 5. 特定モデルを使用（デフォルト: claude）
./venv/bin/python3 verify_predictions.py --update-weights --model gemini
./venv/bin/python3 src/weight_optimizer.py --model gemini
```

---

## アーキテクチャ詳細

### セクタープロファイル解決

`results.json` の各銘柄に付与された `sector` 文字列（yfinance 形式）を、`config.json > sector_profiles` のプロファイルキー（`high_growth` / `healthcare` / `value` / `financial`）に変換する。

| yfinance sector | → sector_profile |
|---|---|
| Technology, Communication Services | high_growth |
| Healthcare | healthcare |
| Industrials, Consumer Defensive, Utilities | value |
| Financial Services | financial |

マッチングは大文字小文字を区別しない部分一致（`"tech" in "Technology"` は True）。

### 軸寄与度の計算

外部 ML ライブラリ不要のナイーブ相関：

```
axis_correlation[axis] =
  mean(score[axis] | signal_hit=True) −
  mean(score[axis] | signal_hit=False)
```

- 正の値 → ヒット時にスコアが高い軸 → 予測に有効 → 重みを上げる候補
- 負の値 → ミス時にスコアが高い軸 → 逆行 → 重みを下げる候補

### LLM プロンプト構造

1. 現在の重み
2. ウィンドウ別（30d / 90d / 180d）の精度統計と軸相関
3. 重みの許容範囲（WEIGHT_BOUNDS）
4. 指示：軸相関に基づいて重みを提案、合計 1.0、最大変化幅 ±0.10

### バリデーション（validate_weights）

| チェック項目 | 条件 |
|---|---|
| 軸の完全性 | fundamental, valuation, technical, qualitative の 4 軸が揃っている |
| 範囲 | fundamental [0.10, 0.50], valuation [0.10, 0.45], technical [0.10, 0.40], qualitative [0.05, 0.40] |
| 合計 | 1.0 ± 0.005 |

### アトミック書き込み

`save_config()` と `save_accuracy_history()` はともにアトミック書き込み（tempfile + rename）を使用。書き込み失敗時に元ファイルが破損するリスクを排除。

---

## データファイル

### `data/accuracy_history.json`

重み最適化の実行履歴。`weight_optimizer.py` が自動作成・追記する。

```json
{
  "snapshots": [
    {
      "timestamp": "2026-05-01T09:00:00",
      "sector_profile": "high_growth",
      "regime": null,
      "window": 30,
      "total": 12,
      "hits": 9,
      "win_rate": 0.75,
      "avg_return": 4.2,
      "axis_correlations": {
        "fundamental": 0.62,
        "valuation": 0.45,
        "technical": 1.21,
        "qualitative": -0.38
      },
      "weights_before": {"fundamental": 0.20, "valuation": 0.25, "technical": 0.25, "qualitative": 0.30},
      "weights_after": {"fundamental": 0.18, "valuation": 0.22, "technical": 0.35, "qualitative": 0.25}
    }
  ],
  "current_weights": {
    "high_growth": {"fundamental": 0.18, "valuation": 0.22, "technical": 0.35, "qualitative": 0.25}
  }
}
```

---

## テスト

```bash
./venv/bin/python3 -m pytest tests/test_weight_optimizer.py -v
```

29 テスト・カバー対象：

| クラス | テスト内容 |
|---|---|
| `TestGetAxisScores` | フラット/ネスト形式のスコアパース、欠損処理 |
| `TestComputeAxisCorrelations` | サンプル不足、相関方向、avg_return 計算 |
| `TestResolveSectorProfile` | 完全/部分マッチ、大文字小文字、空文字 |
| `TestValidateWeights` | 合計不一致、範囲外、欠損軸、浮動小数点許容 |
| `TestParseWeightProposal` | fenced JSON、raw JSON、不正入力 |
| `TestBuildWeightProposalPrompt` | プロンプト必須セクションの存在確認 |
| `TestRunWeightOptimizationMocked` | dry-run、正常適用、バリデーション失敗、サンプル不足、config.json 書き込み |

---

## 注意事項

- **MIN_SAMPLES = 5**：検証済みエントリが 5 件未満のセクタープロファイルは LLM 呼び出しをスキップ
- **本稼働は 30 日後以降**：`results.json` の全エントリが検証期間（30 日）を過ぎるまでフィードバックは蓄積されない
- **cron 推奨**：`verify_predictions.py --update-weights` を週 1 回程度 cron で実行すると精度が向上する
- **重みの変化幅制限**：1 回の更新で 1 軸あたり最大 ±0.10 の変化に制限（LLM プロンプトで指示）

---

## ロードマップとの関係

| Phase | 施策 | フィードバックループとの関係 |
|---|---|---|
| Phase 2 | ブローカー自動執行 | より精度の高い重みでシグナル生成 |
| Phase 3 | マルチエージェント・ディベート | confidence スコアの校正に精度データを活用 |
| Phase 5 | ベクトル DB RAG | 類似ケースの過去重みを参照可能に |
