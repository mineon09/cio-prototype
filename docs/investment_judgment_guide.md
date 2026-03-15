# 投資判断エンジン 使用ガイド

**バージョン**: v2.4.0  
**作成日**: 2026-03-15

---

## 概要

本システムは 2 つの異なる投資判断エンジンを提供します：

1. **API ベースエンジン**: LLM（Gemini/Qwen）を使用した AI 投資判断
2. **ツールベースエンジン**: ルールベース・数値分析による投資判断

両者を比較・統合するデュアルエンジンも利用可能です。

---

## クイックスタート

### 基本的な使い方

```python
from src.investment_judgment import create_judgment_engine, DualJudgmentEngine

# 銘柄データ（既存の分析結果を使用）
ticker_data = {
    'ticker': '7203.T',
    'name': 'Toyota Motor',
    'sector': 'Consumer Cyclical',
    'metrics': {
        'roe': 10.5, 'per': 10.0, 'pbr': 1.2,
        'op_margin': 8.5, 'equity_ratio': 40.0,
    },
    'technical': {
        'current_price': 2850, 'rsi': 45,
        'ma25_deviation': -2.5, 'bb_position': 35,
    },
    'scores': {
        'fundamental': {'score': 7.5},
        'valuation': {'score': 6.0},
        'technical': {'score': 5.5},
        'qualitative': {'score': 7.0},
        'total_score': 6.5,
    },
}

# 方法 1: API ベース判断
api_engine = create_judgment_engine('api', model='gemini')
api_result = api_engine.judge(ticker_data)
print(f"API 判断：{api_result.signal}")

# 方法 2: ツールベース判断
tool_engine = create_judgment_engine('tool')
tool_result = tool_engine.judge(ticker_data)
print(f"ツール判断：{tool_result.signal}")

# 方法 3: 両方比較（推奨）
dual_engine = DualJudgmentEngine(api_engine, tool_engine)
results = dual_engine.judge(ticker_data)
print(f"合意シグナル：{results['consensus']}")
print(f"最終推奨：{results['final_recommendation'].signal}")
```

---

## API ベースエンジン

### 特徴
- **モデル**: Gemini 2.5 Flash または Qwen
- **長所**: 文脈理解・推論能力に優れる
- **短所**: API コスト・レイテンシ

### 使用方法

#### Gemini 使用
```python
from src.investment_judgment import APIJudgmentEngine

engine = APIJudgmentEngine(model='gemini')
result = engine.judge(ticker_data)
```

#### Qwen 使用
```python
engine = APIJudgmentEngine(model='qwen', api_key='your_dashscope_key')
result = engine.judge(ticker_data)
```

### 必要な環境変数

```bash
# Gemini
GEMINI_API_KEY=your_gemini_api_key

# Qwen (DashScope)
DASHSCOPE_API_KEY=your_qwen_api_key
```

---

## ツールベースエンジン

### 特徴
- **手法**: ルールベース・数値分析
- **長所**: 高速・低コスト・再現性あり
- **短所**: 文脈理解は限定的

### 使用方法

```python
from src.investment_judgment import ToolJudgmentEngine

engine = ToolJudgmentEngine()
result = engine.judge(ticker_data)
```

### 判断ロジック

#### シグナル判定
```
総合スコア >= 6.5 → BUY
総合スコア <= 3.5 → SELL
それ以外 → WATCH
```

#### 信頼度計算
4 軸スコアの分散から計算（一致度が高いほど信頼度高）

#### ポジションサイズ
```
ポジション = 基準サイズ (10%) × スコア係数 × 信頼度係数
範囲：2-20%
```

---

## デュアルエンジン（推奨）

### 特徴
- API とツールの両方で判断
- 合意判定・信頼度統合
- 不一致時は保守的なシグナルを採用

### 使用方法

```python
from src.investment_judgment import DualJudgmentEngine

api_engine = APIJudgmentEngine(model='gemini')
tool_engine = ToolJudgmentEngine()
dual_engine = DualJudgmentEngine(api_engine, tool_engine)

# 判断実行
results = dual_engine.judge(ticker_data)

# 結果の詳細
print(f"API 判断：{results['api_judgment'].signal}")
print(f"ツール判断：{results['tool_judgment'].signal}")
print(f"合意：{results['consensus']}")
print(f"不一致：{results['disagreement']}")
print(f"統合信頼度：{results['confidence']:.0%}")

# 最終推奨
final = results['final_recommendation']
print(f"シグナル：{final.signal}")
print(f"エントリー：{final.entry_price}")
print(f"損切り：{final.stop_loss}")
print(f"利確：{final.take_profit}")
print(f"ポジション：{final.position_size:.1%}")
```

### 比較レポート

```python
report = dual_engine.compare_and_report(ticker_data)
print(report)
```

**出力例**:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 投資判断比較レポート
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【対象】Toyota Motor (7203.T)

┌─────────────────────────────────────┐
│ API 判断 (API-gemini)                │
├─────────────────────────────────────┤
│ シグナル：BUY                  │
│ スコア：7.5/10              │
│ 信頼度：80%                  │
│ 理由：ファンダメンタルズが良好...    │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ ツール判断 (Tool-RuleBased)          │
├─────────────────────────────────────┤
│ シグナル：BUY                  │
│ スコア：6.5/10              │
│ 信頼度：75%                  │
│ 理由：総合スコアが BUY 閾値を上回る... │
└─────────────────────────────────────┘

【合意判定】
- 合意シグナル：BUY
- 統合信頼度：78%
- 不一致フラグ：✅ なし

【最終推奨】
- シグナル：BUY
- スコア：7.0/10
- 信頼度：78%
- エントリー：2850
- 損切り：2700
- 利確：3100
- ポジション：12.5%
```

---

## 結果の解釈

### InvestmentJudgment オブジェクト

| フィールド | 型 | 説明 |
|------------|-----|------|
| `signal` | str | BUY/WATCH/SELL |
| `score` | float | 0-10 のスコア |
| `confidence` | float | 0-1 の信頼度 |
| `reasoning` | str | 判断理由 |
| `entry_price` | float | 推奨エントリー価格 |
| `stop_loss` | float | 損切り価格 |
| `take_profit` | float | 利確価格 |
| `position_size` | float | ポジションサイズ (0-1) |
| `holding_period` | str | 保有期間 (short/medium/long) |
| `risks` | list | リスク要因リスト |
| `catalysts` | list | カタリストリスト |
| `model_name` | str | 使用モデル名 |

### シグナルの意味

| シグナル | 意味 | アクション |
|----------|------|-----------|
| **BUY** | 買い推奨 | ポジション構築を検討 |
| **WATCH** | 様子見 | 追加材料を待つ |
| **SELL** | 売り推奨 | ポジション縮小・撤退を検討 |

### 信頼度の目安

| 信頼度 | 解釈 |
|--------|------|
| 0.8-1.0 | 非常に高い |
| 0.6-0.8 | 高い |
| 0.4-0.6 | 普通 |
| 0.2-0.4 | 低い |
| 0.0-0.2 | 非常に低い |

---

## 統合ガイド

### main.py での使用例

```python
from src.investment_judgment import DualJudgmentEngine, create_judgment_engine

# 既存の分析フローの後
target_data = fetch_stock_data(ticker)
scorecard = generate_scorecard(...)

# 投資判断を追加
api_engine = create_judgment_engine('api', model='gemini')
tool_engine = create_judgment_engine('tool')
dual_engine = DualJudgmentEngine(api_engine, tool_engine)

results = dual_engine.judge(
    ticker_data=target_data,
    competitors=competitors,
    yuho_data=yuho_data,
    macro_data=macro_data,
    dcf_data=dcf_data,
)

# 結果を保存
final = results['final_recommendation']
print(f"最終判断：{final.signal}")
```

### app.py (Streamlit) での使用例

```python
import streamlit as st
from src.investment_judgment import DualJudgmentEngine

if st.button('🔮 AI 投資判断'):
    with st.spinner('投資判断を実行中...'):
        api_engine = create_judgment_engine('api', model='gemini')
        tool_engine = create_judgment_engine('tool')
        dual_engine = DualJudgmentEngine(api_engine, tool_engine)
        
        results = dual_engine.judge(ticker_data)
        
        # 結果表示
        col1, col2 = st.columns(2)
        with col1:
            st.metric('API 判断', results['api_judgment'].signal)
            st.metric('信頼度', f"{results['api_judgment'].confidence:.0%}")
        with col2:
            st.metric('ツール判断', results['tool_judgment'].signal)
            st.metric('信頼度', f"{results['tool_judgment'].confidence:.0%}")
        
        # 合意判定
        st.subheader('合意判定')
        st.write(f"シグナル：**{results['consensus']}**")
        st.write(f"統合信頼度：{results['confidence']:.0%}")
        
        if results['disagreement']:
            st.warning('⚠️ API とツールで判断が不一致です')
```

---

## カスタマイズ

### 閾値の変更

```python
# ToolJudgmentEngine の内部閾値を変更
from src.investment_judgment import ToolJudgmentEngine

class CustomToolEngine(ToolJudgmentEngine):
    def _calculate_signal_from_scores(self, scores):
        # カスタム閾値
        buy_threshold = 7.0  # デフォルト 6.5
        sell_threshold = 3.0  # デフォルト 3.5
        
        total_score = scores.get('total_score', 5.0)
        
        if total_score >= buy_threshold:
            signal = 'BUY'
        elif total_score <= sell_threshold:
            signal = 'SELL'
        else:
            signal = 'WATCH'
        
        # ... 以下同様
        return signal, confidence, total_score
```

### カスタムモデルの追加

```python
from src.investment_judgment import BaseJudgmentEngine, InvestmentJudgment

class CustomJudgmentEngine(BaseJudgmentEngine):
    def __init__(self, custom_param):
        self.custom_param = custom_param
    
    def judge(self, ticker_data, **kwargs):
        # カスタムロジック
        return InvestmentJudgment(
            signal='BUY',
            score=7.5,
            confidence=0.8,
            reasoning='カスタム判断',
            model_name='Custom',
        )
    
    def get_model_name(self):
        return 'Custom'
```

---

## 注意事項

### ⚠️ 免責事項

本システムは投資助言を提供するものではありません。投資判断は自己責任で行ってください。

### 🔒 API キーの管理

API キーは環境変数で管理し、Git にはコミットしないでください。

```bash
# .env ファイル
GEMINI_API_KEY=your_key_here
DASHSCOPE_API_KEY=your_key_here
```

### 📊 結果の解釈

- API とツールで不一致がある場合は、より保守的な判断を採用
- 信頼度が低い（0.5 未満）場合は、追加の分析を検討
- 単一の判断を盲信せず、複数の情報源を参照

---

## パフォーマンス

### 処理時間（目安）

| エンジン | 処理時間 |
|----------|----------|
| API (Gemini) | 2-5 秒 |
| API (Qwen) | 1-3 秒 |
| ツール | <0.1 秒 |
| デュアル | 2-5 秒（API に依存） |

### コスト（目安）

| エンジン | コスト/回 |
|----------|-----------|
| API (Gemini) | $0.0001-0.001 |
| API (Qwen) | $0.0001-0.001 |
| ツール | $0 (ローカル実行) |

---

## 参考

- [src/investment_judgment.py](../src/investment_judgment.py) - 実装コード
- [tests/test_investment_judgment.py](../tests/test_investment_judgment.py) - 単体テスト
- [CHANGELOG.md](../docs/CHANGELOG.md) - 変更履歴
