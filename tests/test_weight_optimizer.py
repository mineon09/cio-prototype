"""
tests/test_weight_optimizer.py — weight_optimizer.py のユニットテスト
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.weight_optimizer import (
    AXES,
    WEIGHT_BOUNDS,
    _get_axis_scores,
    build_weight_proposal_prompt,
    compute_axis_correlations,
    parse_weight_proposal,
    resolve_sector_profile,
    validate_weights,
)


# ======================================================================
# テストデータ生成ヘルパー
# ======================================================================

def _make_entry(
    signal: str,
    scores: dict,
    signal_hit: bool | None,
    price_change_pct: float,
    window: int = 30,
    regime: str = "RISK_ON",
    sector: str = "Technology",
) -> dict:
    """verify_predictions.py が生成するエントリ構造のモック。"""
    return {
        "signal": signal,
        "scores": scores,
        "macro": {"regime": regime},
        "metrics": {"sector": sector},
        f"verified_{window}d": {
            "signal_hit": signal_hit,
            "price_change_pct": price_change_pct,
            "actual_price": 200.0,
        },
    }


def _make_hit_entry(window: int = 30) -> dict:
    return _make_entry(
        signal="BUY",
        scores={"fundamental": 7.0, "valuation": 6.5, "technical": 8.0, "qualitative": 5.5},
        signal_hit=True,
        price_change_pct=5.2,
        window=window,
    )


def _make_miss_entry(window: int = 30) -> dict:
    return _make_entry(
        signal="BUY",
        scores={"fundamental": 4.5, "valuation": 5.0, "technical": 4.0, "qualitative": 6.5},
        signal_hit=False,
        price_change_pct=-3.1,
        window=window,
    )


# ======================================================================
# _get_axis_scores
# ======================================================================

class TestGetAxisScores(unittest.TestCase):
    def test_flat_scores(self):
        """フラット形式 {"fundamental": 7.0} を正しくパース。"""
        entry = {"scores": {"fundamental": 7.0, "valuation": 6.0, "technical": 5.0, "qualitative": 4.0}}
        result = _get_axis_scores(entry)
        self.assertEqual(result["fundamental"], 7.0)
        self.assertEqual(result["qualitative"], 4.0)

    def test_nested_scores(self):
        """ネスト形式 {"fundamental": {"score": 7.0}} を正しくパース。"""
        entry = {"scores": {"fundamental": {"score": 7.0}, "valuation": {"score": 6.0},
                             "technical": {"score": 5.0}, "qualitative": {"score": 4.0}}}
        result = _get_axis_scores(entry)
        self.assertEqual(result["fundamental"], 7.0)

    def test_missing_scores(self):
        """scores キーなしは None を返す。"""
        self.assertIsNone(_get_axis_scores({}))

    def test_empty_scores(self):
        """空の scores dict は None を返す。"""
        self.assertIsNone(_get_axis_scores({"scores": {}}))


# ======================================================================
# compute_axis_correlations
# ======================================================================

class TestComputeAxisCorrelations(unittest.TestCase):
    def _make_entries(self, n_hits: int, n_misses: int, window: int = 30) -> list:
        return [_make_hit_entry(window) for _ in range(n_hits)] + \
               [_make_miss_entry(window) for _ in range(n_misses)]

    def test_insufficient_data_returns_none(self):
        """MIN_SAMPLES (5) 未満は None。"""
        entries = self._make_entries(2, 2)
        self.assertIsNone(compute_axis_correlations(entries, 30))

    def test_sufficient_data_returns_stats(self):
        """十分なデータでは統計が返る。"""
        entries = self._make_entries(4, 4)  # 8 entries >= MIN_SAMPLES=5
        stats = compute_axis_correlations(entries, 30)
        self.assertIsNotNone(stats)
        self.assertEqual(stats["total"], 8)
        self.assertEqual(stats["hits"], 4)
        self.assertAlmostEqual(stats["win_rate"], 0.5, places=2)

    def test_axis_correlations_direction(self):
        """
        hit エントリの technical スコアが高い → technical の correlation が正。
        hit エントリの qualitative スコアが低い → qualitative の correlation が負。
        """
        entries = self._make_entries(5, 5)
        stats = compute_axis_correlations(entries, 30)
        self.assertIsNotNone(stats)
        corr = stats["axis_correlations"]
        # hit_entry: technical=8.0, miss_entry: technical=4.0 → diff > 0
        self.assertGreater(corr["technical"], 0)
        # hit_entry: qualitative=5.5, miss_entry: qualitative=6.5 → diff < 0
        self.assertLess(corr["qualitative"], 0)

    def test_wrong_window_returns_none(self):
        """指定ウィンドウの verified_*d がないエントリは None。"""
        entries = [_make_hit_entry(30) for _ in range(6)]
        self.assertIsNone(compute_axis_correlations(entries, 90))

    def test_avg_return_calculated(self):
        """avg_return が正しく計算される。"""
        entries = self._make_entries(4, 4)
        stats = compute_axis_correlations(entries, 30)
        # hit: +5.2, miss: -3.1 → avg = (5.2*4 + -3.1*4) / 8 = 1.05
        self.assertAlmostEqual(stats["avg_return"], 1.05, places=2)


# ======================================================================
# resolve_sector_profile
# ======================================================================

class TestResolveSectorProfile(unittest.TestCase):
    MOCK_CONFIG = {
        "sector_profiles": {
            "high_growth": {"sectors": ["Technology", "Communication Services"], "weights": {}},
            "value": {"sectors": ["Industrials", "Consumer Defensive"], "weights": {}},
            "financial": {"sectors": ["Financial Services"], "weights": {}},
        }
    }

    def test_exact_match(self):
        self.assertEqual(
            resolve_sector_profile("Technology", self.MOCK_CONFIG), "high_growth"
        )

    def test_partial_match(self):
        self.assertEqual(
            resolve_sector_profile("Communication Services", self.MOCK_CONFIG), "high_growth"
        )

    def test_case_insensitive(self):
        self.assertEqual(
            resolve_sector_profile("technology", self.MOCK_CONFIG), "high_growth"
        )

    def test_unknown_sector_returns_none(self):
        self.assertIsNone(resolve_sector_profile("Unknown Sector", self.MOCK_CONFIG))

    def test_empty_sector_returns_none(self):
        self.assertIsNone(resolve_sector_profile("", self.MOCK_CONFIG))


# ======================================================================
# validate_weights
# ======================================================================

class TestValidateWeights(unittest.TestCase):
    VALID = {"fundamental": 0.25, "valuation": 0.25, "technical": 0.25, "qualitative": 0.25}

    def test_valid_weights(self):
        ok, msg = validate_weights(self.VALID)
        self.assertTrue(ok)

    def test_sum_not_one_fails(self):
        bad = {**self.VALID, "fundamental": 0.40}  # sum = 1.15
        ok, msg = validate_weights(bad)
        self.assertFalse(ok)
        self.assertIn("sum", msg)

    def test_out_of_bounds_fails(self):
        bad = {**self.VALID, "qualitative": 0.01}  # below min 0.05
        ok, msg = validate_weights(bad)
        self.assertFalse(ok)

    def test_missing_axis_fails(self):
        bad = {"fundamental": 0.33, "valuation": 0.33, "technical": 0.34}  # no qualitative
        ok, msg = validate_weights(bad)
        self.assertFalse(ok)
        self.assertIn("Missing", msg)

    def test_sum_tolerance(self):
        """浮動小数点誤差（±0.005）は許容。"""
        close = {**self.VALID, "fundamental": 0.2502}  # sum = 1.0002
        ok, _ = validate_weights(close)
        self.assertTrue(ok)


# ======================================================================
# parse_weight_proposal
# ======================================================================

class TestParseWeightProposal(unittest.TestCase):
    VALID_JSON = json.dumps({
        "proposed_weights": {
            "fundamental": 0.22, "valuation": 0.28,
            "technical": 0.28, "qualitative": 0.22,
        },
        "reasoning": "Technical shows high correlation",
    })

    def test_parse_fenced_json(self):
        text = f"Some analysis...\n```json\n{self.VALID_JSON}\n```\nEnd."
        result = parse_weight_proposal(text)
        self.assertIsNotNone(result)
        self.assertIn("proposed_weights", result)

    def test_parse_raw_json(self):
        result = parse_weight_proposal(self.VALID_JSON)
        self.assertIsNotNone(result)
        self.assertEqual(result["proposed_weights"]["technical"], 0.28)

    def test_no_proposed_weights_returns_none(self):
        result = parse_weight_proposal('{"other_key": 123}')
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self):
        result = parse_weight_proposal("not json at all")
        self.assertIsNone(result)


# ======================================================================
# build_weight_proposal_prompt
# ======================================================================

class TestBuildWeightProposalPrompt(unittest.TestCase):
    def test_prompt_contains_key_sections(self):
        current = {"fundamental": 0.2, "valuation": 0.25, "technical": 0.25, "qualitative": 0.3}
        stats_30 = {
            "total": 10, "hits": 7, "win_rate": 0.7, "avg_return": 3.5,
            "axis_correlations": {"fundamental": 0.8, "valuation": 0.3,
                                   "technical": 1.2, "qualitative": -0.1},
            "axis_avg_scores": {"hit": {"fundamental": 7.0, "valuation": 6.5,
                                         "technical": 8.0, "qualitative": 5.0},
                                 "miss": {"fundamental": 6.2, "valuation": 6.2,
                                          "technical": 6.8, "qualitative": 5.1}},
        }
        prompt = build_weight_proposal_prompt(
            sector_profile="high_growth",
            current_weights=current,
            analysis_data={30: stats_30, 90: None},
        )
        self.assertIn("high_growth", prompt)
        self.assertIn("proposed_weights", prompt)
        self.assertIn("win_rate", prompt)
        self.assertIn("axis correlations", prompt)
        self.assertIn("avg scores", prompt)


# ======================================================================
# Integration: run_weight_optimization with mocked LLM
# ======================================================================

class TestRunWeightOptimizationMocked(unittest.TestCase):
    """モック LLM と一時ファイルを使った結合テスト。"""

    MOCK_SECTOR_PROFILES = {
        "high_growth": {
            "sectors": ["Technology"],
            "weights": {"fundamental": 0.20, "valuation": 0.25, "technical": 0.25, "qualitative": 0.30},
        }
    }

    PROPOSED_WEIGHTS = {"fundamental": 0.22, "valuation": 0.23, "technical": 0.28, "qualitative": 0.27}

    def _make_sufficient_entries(self, n: int = 6, window: int = 30) -> list:
        entries = []
        for i in range(n):
            hit = i % 2 == 0
            entries.append(_make_entry(
                signal="BUY",
                scores={"fundamental": 7.0 if hit else 4.5,
                        "valuation": 6.5 if hit else 5.0,
                        "technical": 8.0 if hit else 4.0,
                        "qualitative": 5.5 if hit else 6.5},
                signal_hit=hit,
                price_change_pct=5.0 if hit else -3.0,
                window=window,
            ))
        return entries

    def test_dry_run_does_not_modify_config(self):
        """dry_run=True の場合は config.json を変更しない。"""
        from src.weight_optimizer import optimize_sector_weights

        entries = self._make_sufficient_entries()
        current = copy.deepcopy(self.MOCK_SECTOR_PROFILES["high_growth"]["weights"])

        LLM_RESPONSE = json.dumps({
            "proposed_weights": self.PROPOSED_WEIGHTS,
            "reasoning": "Technical shows highest correlation.",
        })

        with patch("src.weight_optimizer._get_llm_caller") as mock_llm:
            mock_llm.return_value = MagicMock(return_value=LLM_RESPONSE)
            result = optimize_sector_weights(
                sector_profile="high_growth",
                entries=entries,
                current_weights=current,
                dry_run=True,
            )

        self.assertFalse(result["applied"])
        self.assertEqual(result["proposed_weights"], self.PROPOSED_WEIGHTS)
        # current_weights は変更されていない
        self.assertEqual(result["current_weights"], current)

    def test_valid_proposal_applied_to_config(self):
        """有効な提案は applied=True になる（config への書き込みは別途テスト）。"""
        from src.weight_optimizer import optimize_sector_weights

        entries = self._make_sufficient_entries()
        current = copy.deepcopy(self.MOCK_SECTOR_PROFILES["high_growth"]["weights"])

        LLM_RESPONSE = json.dumps({
            "proposed_weights": self.PROPOSED_WEIGHTS,
            "reasoning": "Technical shows highest correlation.",
        })

        with patch("src.weight_optimizer._get_llm_caller") as mock_llm:
            mock_llm.return_value = MagicMock(return_value=LLM_RESPONSE)
            result = optimize_sector_weights(
                sector_profile="high_growth",
                entries=entries,
                current_weights=current,
                dry_run=False,
            )

        self.assertTrue(result["applied"])
        self.assertEqual(result["proposed_weights"], self.PROPOSED_WEIGHTS)

    def test_invalid_weights_not_applied(self):
        """バリデーション失敗（sum != 1.0）の場合は applied=False。"""
        from src.weight_optimizer import optimize_sector_weights

        entries = self._make_sufficient_entries()
        current = copy.deepcopy(self.MOCK_SECTOR_PROFILES["high_growth"]["weights"])

        BAD_RESPONSE = json.dumps({
            "proposed_weights": {"fundamental": 0.40, "valuation": 0.40,
                                  "technical": 0.40, "qualitative": 0.40},
            "reasoning": "Wrong weights (sum = 1.6)",
        })

        with patch("src.weight_optimizer._get_llm_caller") as mock_llm:
            mock_llm.return_value = MagicMock(return_value=BAD_RESPONSE)
            result = optimize_sector_weights(
                sector_profile="high_growth",
                entries=entries,
                current_weights=current,
                dry_run=False,
            )

        self.assertFalse(result["applied"])
        self.assertIn("skip_reason", result)

    def test_insufficient_data_skipped(self):
        """MIN_SAMPLES 未満のデータはスキップされる。"""
        from src.weight_optimizer import optimize_sector_weights

        entries = self._make_sufficient_entries(n=2)  # too few
        current = copy.deepcopy(self.MOCK_SECTOR_PROFILES["high_growth"]["weights"])

        with patch("src.weight_optimizer._get_llm_caller") as mock_llm:
            result = optimize_sector_weights(
                sector_profile="high_growth",
                entries=entries,
                current_weights=current,
                dry_run=False,
            )

        self.assertFalse(result["applied"])
        mock_llm.assert_not_called()

    def test_config_json_written_on_apply(self):
        """applied=True の結果が出た場合、config.json が正しく更新される。"""
        from src.weight_optimizer import run_weight_optimization

        mock_config = {
            "sector_profiles": copy.deepcopy(self.MOCK_SECTOR_PROFILES),
            "macro": {},
        }
        mock_results = {
            "AAPL": {
                "sector": "Technology",
                "history": self._make_sufficient_entries(n=6),
            }
        }

        LLM_RESPONSE = json.dumps({
            "proposed_weights": self.PROPOSED_WEIGHTS,
            "reasoning": "Technical improved accuracy.",
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_config = Path(tmpdir) / "config.json"
            tmp_results = Path(tmpdir) / "results.json"
            tmp_history = Path(tmpdir) / "accuracy_history.json"
            tmp_config.write_text(json.dumps(mock_config), encoding="utf-8")
            tmp_results.write_text(json.dumps(mock_results), encoding="utf-8")

            with patch("src.weight_optimizer.CONFIG_PATH", tmp_config), \
                 patch("src.weight_optimizer.RESULTS_FILE", tmp_results), \
                 patch("src.weight_optimizer.HISTORY_FILE", tmp_history), \
                 patch("src.weight_optimizer._get_llm_caller") as mock_llm:

                mock_llm.return_value = MagicMock(return_value=LLM_RESPONSE)
                results = run_weight_optimization(dry_run=False)

            applied = [r for r in results if r["applied"]]
            self.assertEqual(len(applied), 1)

            updated = json.loads(tmp_config.read_text())
            new_weights = updated["sector_profiles"]["high_growth"]["weights"]
            self.assertEqual(new_weights, self.PROPOSED_WEIGHTS)

            # accuracy_history が書き込まれている
            self.assertTrue(tmp_history.exists())
            hist = json.loads(tmp_history.read_text())
            self.assertIn("snapshots", hist)


if __name__ == "__main__":
    unittest.main(verbosity=2)
