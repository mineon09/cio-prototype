"""
tests/test_save_claude_result.py
入力プロンプト内のサンプルJSONとClaudeの出力JSONが混在するケースで
正しく抽出できることを検証する。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from save_claude_result import extract_json_from_response


# ─────────────────────────────────────────────────────────────────────────────
# ヘルパー
# ─────────────────────────────────────────────────────────────────────────────

def _sample_with_two_json_blocks(early_score, late_score):
    """入力プロンプト内にサンプルJSON、その後にClaudeの出力JSONが続くテキストを生成"""
    return f"""
【アナリストコンセンサス】
総合スコア：7.0/10

出力フォーマット例（必ずこの形式で）：
```json
{{
  "signal": "BUY",
  "score": {early_score},
  "entry_price": 340.0,
  "confidence": 0.70
}}
```

---
以下がClaudeの分析結果です。

```json
{{
  "signal": "BUY",
  "score": {late_score},
  "entry_price": 322.0,
  "confidence": 0.78,
  "stop_loss": 300.0,
  "take_profit": 380.0,
  "key_catalysts": ["AI需要拡大", "CoWoS供給回復"],
  "key_risks": ["米中規制", "ASML輸出制限"]
}}
```
"""


# ─────────────────────────────────────────────────────────────────────────────
# テスト
# ─────────────────────────────────────────────────────────────────────────────

def test_prefers_last_fenced_json_block():
    """複数の ```json ブロックがある場合、最後のブロックのscoreが採用されること"""
    text = _sample_with_two_json_blocks(early_score=7.5, late_score=8.5)
    result = extract_json_from_response(text)
    assert result.get("score") == 8.5, \
        f"Expected score=8.5 (Claude output), got {result.get('score')}"
    assert result.get("entry_price") == 322.0, \
        f"Expected entry_price=322.0, got {result.get('entry_price')}"
    assert result.get("signal") == "BUY", \
        f"Expected signal=BUY, got {result.get('signal')}"
    print("✅ test_prefers_last_fenced_json_block: PASS")


def test_early_score_not_stolen_by_analyst_consensus():
    """入力プロンプトのアナリストコンセンサス 7.0/10 がscoreとして誤採用されないこと"""
    text = _sample_with_two_json_blocks(early_score=7.5, late_score=8.5)
    result = extract_json_from_response(text)
    assert result.get("score") != 7.0, \
        "score=7.0 (アナリストコンセンサス) を誤採用している"
    assert result.get("score") != 7.5, \
        "score=7.5 (サンプルJSON) を誤採用している"
    print("✅ test_early_score_not_stolen_by_analyst_consensus: PASS")


def test_signal_is_extracted():
    """signal フィールドが正しく抽出されること"""
    text = _sample_with_two_json_blocks(early_score=6.0, late_score=8.5)
    result = extract_json_from_response(text)
    assert result.get("signal") == "BUY"
    print("✅ test_signal_is_extracted: PASS")


def test_all_claude_fields_present():
    """Claude出力JSONのすべてのフィールドが欠落なく抽出されること"""
    text = _sample_with_two_json_blocks(early_score=7.5, late_score=8.5)
    result = extract_json_from_response(text)
    for field in ("signal", "score", "entry_price", "confidence",
                  "stop_loss", "take_profit", "key_catalysts", "key_risks"):
        assert field in result, f"フィールド '{field}' が抽出結果に含まれていない"
    print("✅ test_all_claude_fields_present: PASS")


def test_single_json_block_still_works():
    """JSONブロックが1つだけの場合（通常ケース）も正しく動作すること"""
    text = """
分析結果：

```json
{
  "signal": "WATCH",
  "score": 5.5,
  "entry_price": 150.0,
  "confidence": 0.55
}
```
"""
    result = extract_json_from_response(text)
    assert result.get("score") == 5.5
    assert result.get("signal") == "WATCH"
    print("✅ test_single_json_block_still_works: PASS")


def test_no_json_returns_empty_dict():
    """JSONが全くない場合は空dictを返すこと"""
    text = "これはJSONを含まないテキストです。"
    result = extract_json_from_response(text)
    assert result == {}, f"Expected empty dict, got {result}"
    print("✅ test_no_json_returns_empty_dict: PASS")


def test_tsmlike_real_scenario():
    """TSMの実際のシナリオを再現: score=8.5が正しく抽出されること"""
    text = """
【アナリストコンセンサス】
総合スコア：7.0/10 (アナリスト27名)

出力JSON形式：
```json
{"signal": "BUY", "score": 7.0, "entry_price": 320.0}
```

## 分析

TSMCはAI半導体の中核サプライヤーとして...（省略）

```json
{
  "signal": "BUY",
  "score": 8.5,
  "confidence": 0.78,
  "entry_price": 322.0,
  "stop_loss": 295.0,
  "take_profit": 385.0,
  "position_size": 0.08,
  "key_catalysts": ["CoWoS需要拡大", "2nm量産開始"],
  "key_risks": ["地政学的リスク", "NVIDIA依存度"]
}
```
"""
    result = extract_json_from_response(text)
    assert result.get("score") == 8.5, \
        f"TSMシナリオ: Expected score=8.5, got {result.get('score')}"
    assert result.get("entry_price") == 322.0
    assert result.get("confidence") == 0.78
    assert isinstance(result.get("key_catalysts"), list)
    print("✅ test_tsmlike_real_scenario: PASS")


if __name__ == "__main__":
    test_prefers_last_fenced_json_block()
    test_early_score_not_stolen_by_analyst_consensus()
    test_signal_is_extracted()
    test_all_claude_fields_present()
    test_single_json_block_still_works()
    test_no_json_returns_empty_dict()
    test_tsmlike_real_scenario()
    print("\n🎉 全テスト PASS")
