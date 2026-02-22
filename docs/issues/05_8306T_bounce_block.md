# Issue #05: 8306.T Bounce / Breakout 戦略 エントリーブロック問題

- **発見日**: 2026-02-22
- **ステータス**: ✅ 暫定修正済（根本解決は案C待ち）
- **影響**: 2024年 +57% の上昇中、bounce / breakout 両戦略で0トレード

---

## 症状

8306.T (三菱UFJ) に対して bounce / breakout 両戦略でバックテストを実行すると、2024年1月〜12月の期間でトレード数が0になる。同期間に株価は +57% 上昇しており、明らかな機会損失。

## 原因分析

### Bounce 戦略: 2段階のフィルターブロック

### ブロック1: レジームフィルター

```python
# BounceStrategy.analyze_entry()
regime = row.get('regime')
enabled_regimes = self.s_cfg.get("enabled_regimes", [])
if regime not in enabled_regimes:
    return {"is_entry": False}
```

- 8306.T の `ticker_overrides` に `enabled_regimes` の記述なし
- デフォルト `["RISK_ON", "NEUTRAL", "RATE_CUT", "YIELD_INVERSION"]` が適用**されない**（override でストラテジー単位の merge が部分的）
- 2024年の大半が `YIELD_INVERSION` レジーム → 全日ブロック

**比較**: 7203.T は `ticker_overrides` で明示的に `YIELD_INVERSION` を含む `enabled_regimes` を設定済み → 1トレード成立

### Breakout 戦略: 3段階のブロック

1. **`enabled: false`**: `ticker_overrides` で breakout が無効化されていた（理由: "Low volatility bank sector unsuitable for momentum breakout"）
2. **`fundamental_min: 5.0`**: bounce と同様、デフォルト閾値が8306.T のスコア 4.2 を上回る
3. **`enabled_regimes` なし**: YIELD_INVERSION が含まれていない

`BaseStrategy.should_buy()` が `self.s_cfg.get("enabled", True)` をチェックするため、`enabled: false` の時点で全エントリーが即座にブロックされていた。

### ブロック2: ファンダメンタル閾値

```python
# BounceStrategy.analyze_entry() 最初のチェック
fund_score = row.get('fundamental', 0)   # 8306.T = 4.2
fund_min = entry_cfg.get("fundamental_min", 5.0)  # 閾値 5.0
if fund_score < fund_min:
    return {"is_entry": False}  # 即NG
```

- 8306.T のファンダメンタルスコア = 4.2（ROE 2.44% の銀行株）
- bounce のデフォルト `fundamental_min` = 5.0
- スコアとしては正しく反映されているが、銀行セクターには過大な要件

## 修正内容

`config.json` の `ticker_overrides.8306.T.strategies.bounce` に以下を追加：

```json
{
  "enabled_regimes": ["RISK_ON", "NEUTRAL", "RATE_CUT", "YIELD_INVERSION"],
  "entry": {
    "fundamental_min": 4.0,
    "volume_multiplier": 1.0,
    "rsi_threshold": 32
  }
}
```

## 根本解決の方向性（案C）

この問題の本質は**米国の逆イールドで日本株を全停止する**というマクロ判定ロジックにある。

- 現行: `macro_regime.py` が米国債利回り（^TNX, ^IRX）で逆イールドを検出 → 全銘柄に `YIELD_INVERSION` 適用
- 問題: 2024年の米国逆イールド期間中、日本株（特に銀行セクター）は金利上昇の恩恵で大幅上昇
- 解決案: 日本株 (.T) は日本のマクロ指標（日銀政策金利、JGB利回りカーブ）で独立判定

> [!IMPORTANT]
> 案Cの実装は `macro_regime.py` へのリージョン分離ロジック追加を伴う大きな変更のため、別Issue として管理する。
