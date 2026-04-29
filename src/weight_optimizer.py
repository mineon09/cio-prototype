#!/usr/bin/env python3
"""
src/weight_optimizer.py — 予測精度フィードバックループ：重み自動最適化
======================================================================
verify_predictions.py が蓄積した verified_*d データを読み込み、
セクター×レジーム別に各スコアリング軸（fundamental/valuation/technical/qualitative）の
予測寄与度を分析して LLM に重み更新提案を求め、config.json の
sector_profiles[X].weights と macro.regime_weights に書き戻す。

使い方:
    # 全セクターを dry-run で確認
    ./venv/bin/python3 src/weight_optimizer.py --dry-run

    # 本番実行（config.json を更新）
    ./venv/bin/python3 src/weight_optimizer.py

    # 特定セクタープロファイルのみ
    ./venv/bin/python3 src/weight_optimizer.py --sector high_growth

    # 特定ウィンドウのみ (30/90/180)
    ./venv/bin/python3 src/weight_optimizer.py --window 90
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# プロジェクトルートの .env を読み込む（GEMINI_API_KEY / ANTHROPIC_API_KEY 等）
# override=True: シェルに空の環境変数がある場合でも .env の値で上書きする
load_dotenv(override=True)

logger = logging.getLogger("WeightOptimizer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
CONFIG_PATH  = PROJECT_ROOT / "config.json"
RESULTS_FILE = DATA_DIR / "results.json"
HISTORY_FILE = DATA_DIR / "accuracy_history.json"

AXES = ("fundamental", "valuation", "technical", "qualitative")
WINDOWS = (30, 90, 180)

# 重みの上下限ガードレール
WEIGHT_BOUNDS = {
    "fundamental":  (0.10, 0.50),
    "valuation":    (0.10, 0.45),
    "technical":    (0.10, 0.40),
    "qualitative":  (0.05, 0.40),
}
MIN_SAMPLES = 5   # 統計的に意味のある最小サンプル数

SYSTEM_PROMPT = (
    "You are a quantitative portfolio analyst expert in multi-factor scoring models. "
    "You analyze which scoring axes most accurately predict future price movements, "
    "then recommend weight adjustments that improve prediction accuracy while "
    "maintaining portfolio diversification. Always respond with valid JSON only."
)

# ======================================================================
# Config I/O
# ======================================================================

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    """Atomic write to config.json."""
    target = CONFIG_PATH
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False,
        dir=str(target.parent), suffix=".tmp",
    )
    json.dump(cfg, tmp, indent=2, ensure_ascii=False)
    tmp.close()
    if target.exists():
        os.remove(str(target))
    os.rename(tmp.name, str(target))


def load_results() -> dict:
    if not RESULTS_FILE.exists():
        return {}
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


# ======================================================================
# Accuracy History I/O
# ======================================================================

def load_accuracy_history() -> dict:
    if not HISTORY_FILE.exists():
        return {"snapshots": [], "current_weights": {}}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"snapshots": [], "current_weights": {}}


def save_accuracy_history(history: dict) -> None:
    target = HISTORY_FILE
    target.parent.mkdir(exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False,
        dir=str(target.parent), suffix=".tmp",
    )
    json.dump(history, tmp, indent=2, ensure_ascii=False)
    tmp.close()
    if target.exists():
        os.remove(str(target))
    os.rename(tmp.name, str(target))


# ======================================================================
# Sector profile resolution
# ======================================================================

def resolve_sector_profile(sector: str, config: dict) -> str | None:
    """yfinance の sector 文字列を config.json の sector_profile キーに変換する。"""
    sector_profiles = config.get("sector_profiles", {})
    sector_lower = (sector or "").lower().strip()
    if not sector_lower:
        return None
    for profile_name, profile in sector_profiles.items():
        for s in profile.get("sectors", []):
            if s.lower() in sector_lower or sector_lower in s.lower():
                return profile_name
    return None


# ======================================================================
# Statistical analysis
# ======================================================================

def compute_axis_correlations(
    entries: list[dict],
    window: int,
) -> dict | None:
    """
    verified_{window}d があるエントリから、各スコアリング軸と命中率の相関を計算。

    Returns:
        {
            "total": int,
            "hits": int,
            "win_rate": float,
            "avg_return": float | None,
            "axis_correlations": {"fundamental": float, ...},
            "axis_avg_scores": {
                "hit":  {"fundamental": float, ...},
                "miss": {"fundamental": float, ...},
            }
        }
        None if insufficient data (< MIN_SAMPLES)
    """
    key = f"verified_{window}d"
    valid = [
        e for e in entries
        if key in e and e[key].get("signal_hit") is not None
        and _get_axis_scores(e) is not None
    ]

    if len(valid) < MIN_SAMPLES:
        return None

    hit_entries  = [e for e in valid if e[key]["signal_hit"] is True]
    miss_entries = [e for e in valid if e[key]["signal_hit"] is False]
    returns = [e[key]["price_change_pct"] for e in valid
               if e[key].get("price_change_pct") is not None]

    def axis_means(group: list[dict]) -> dict | None:
        if not group:
            return None
        out = {}
        for ax in AXES:
            scores = [_get_axis_scores(e)[ax] for e in group
                      if _get_axis_scores(e).get(ax) is not None]
            out[ax] = round(sum(scores) / len(scores), 3) if scores else None
        return out

    hit_means  = axis_means(hit_entries)  or {ax: 5.0 for ax in AXES}
    miss_means = axis_means(miss_entries) or {ax: 5.0 for ax in AXES}

    correlations = {
        ax: round((hit_means.get(ax, 5.0) or 5.0) - (miss_means.get(ax, 5.0) or 5.0), 3)
        for ax in AXES
    }

    return {
        "total": len(valid),
        "hits": len(hit_entries),
        "win_rate": round(len(hit_entries) / len(valid), 3),
        "avg_return": round(sum(returns) / len(returns), 2) if returns else None,
        "axis_correlations": correlations,
        "axis_avg_scores": {"hit": hit_means, "miss": miss_means},
    }


def _get_axis_scores(entry: dict) -> dict | None:
    """history entry から 4 軸スコアを dict で返す。"""
    scores = entry.get("scores", {})
    if not scores:
        return None
    out = {}
    for ax in AXES:
        v = scores.get(ax)
        if isinstance(v, dict):
            v = v.get("score")
        if v is not None:
            out[ax] = float(v)
    return out if out else None


# ======================================================================
# LLM caller (llm_strategy_optimizer.py パターンを流用)
# ======================================================================

def _get_llm_caller(model: str = "claude"):
    """Claude / Gemini の LLM 呼び出し関数を返す。

    利用可能モデル:
      - "claude"  : anthropic パッケージ + ANTHROPIC_API_KEY 必須
      - "gemini"  : google-genai パッケージ (google.genai) + GEMINI_API_KEY 必須
    """
    if model in ("claude", "anthropic"):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic パッケージが未インストールです。\n"
                "  ./venv/bin/pip install anthropic\n"
                "または --model gemini を使用してください。"
            )
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY が .env に設定されていません。")
        client = anthropic.Anthropic(api_key=api_key)

        def call_claude(prompt: str) -> str:
            msg = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text

        return call_claude

    elif model in ("gemini", "google"):
        # google-genai (新SDK) を使用。google.generativeai (旧SDK) ではない。
        try:
            from google import genai as google_genai
            from google.genai import types as genai_types
        except ImportError:
            raise ImportError(
                "google-genai パッケージが未インストールです。\n"
                "  ./venv/bin/pip install google-genai"
            )
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY が .env に設定されていません。")
        client = google_genai.Client(api_key=api_key)

        def call_gemini(prompt: str) -> str:
            full_prompt = SYSTEM_PROMPT + "\n\n" + prompt
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=full_prompt,
            )
            return response.text

        return call_gemini

    else:
        raise ValueError(f"Unsupported model: {model}. Use 'claude' or 'gemini'.")


# ======================================================================
# LLM-based weight proposal
# ======================================================================

def build_weight_proposal_prompt(
    sector_profile: str,
    current_weights: dict,
    analysis_data: dict,  # window → stats
    regime: str | None = None,
) -> str:
    context = f"Sector profile: {sector_profile}"
    if regime:
        context += f"  |  Macro regime: {regime}"

    lines = [
        f"## Weight Optimization Request: {context}",
        "",
        "### Current weights",
        json.dumps(current_weights, indent=2),
        "",
        "### Prediction accuracy analysis (per verification window)",
    ]

    for window, stats in analysis_data.items():
        if stats is None:
            lines.append(f"\n**{window}d window:** Insufficient data (< {MIN_SAMPLES} verified entries)")
            continue
        lines += [
            f"\n**{window}d window** — {stats['total']} verified entries",
            f"  win_rate: {stats['win_rate']:.1%}  |  avg_return: "
            + (f"{stats['avg_return']:+.2f}%" if stats['avg_return'] is not None else "N/A"),
            f"  axis correlations (hit_mean - miss_mean score difference):",
        ]
        for ax, corr in sorted(
            stats["axis_correlations"].items(), key=lambda x: -x[1]
        ):
            direction = "↑ high predictive power" if corr > 0.5 else (
                "↓ low predictive power" if corr < 0 else ""
            )
            lines.append(f"    {ax}: {corr:+.3f}  {direction}")
        lines += [
            f"  avg scores — HIT: {json.dumps(stats['axis_avg_scores']['hit'])}",
            f"              MISS: {json.dumps(stats['axis_avg_scores']['miss'])}",
        ]

    lines += [
        "",
        "### Weight bounds (must stay within)",
        json.dumps(WEIGHT_BOUNDS, indent=2),
        "",
        "### Instructions",
        "1. Analyze which axes have the highest correlation with correct predictions.",
        "2. Propose new weights that: (a) increase weight for high-correlation axes, "
           "(b) decrease weight for low-correlation axes, (c) sum exactly to 1.0.",
        "3. Changes should be incremental (max ±0.10 per axis per update).",
        "4. Explain briefly why each weight changed.",
        "",
        "### Required JSON response format (ONLY output this JSON, no other text):",
        '{"proposed_weights": {"fundamental": 0.0, "valuation": 0.0, "technical": 0.0, "qualitative": 0.0},'
        ' "reasoning": "...short explanation..."}',
    ]
    return "\n".join(lines)


def parse_weight_proposal(response_text: str) -> dict | None:
    """LLM レスポンスから JSON を抽出してバリデーション。"""
    import re

    # 1) ```json ... ``` fenced block
    m = re.search(r"```json\s*(\{.*?})\s*```", response_text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if "proposed_weights" in obj:
                return obj
        except Exception:
            pass

    # 2) raw_decode: 文字列先頭から {} を探してパース（ネスト対応）
    decoder = json.JSONDecoder()
    for i in range(len(response_text)):
        if response_text[i] != '{':
            continue
        try:
            obj, _ = decoder.raw_decode(response_text, i)
            if isinstance(obj, dict) and "proposed_weights" in obj:
                return obj
        except Exception:
            continue

    return None


def validate_weights(weights: dict) -> tuple[bool, str]:
    """提案された重みのバリデーション。"""
    if set(weights.keys()) != set(AXES):
        return False, f"Missing axes: expected {set(AXES)}, got {set(weights.keys())}"

    for ax, val in weights.items():
        lo, hi = WEIGHT_BOUNDS[ax]
        if not (lo <= val <= hi):
            return False, f"{ax}={val:.3f} out of bounds [{lo}, {hi}]"

    total = sum(weights.values())
    if abs(total - 1.0) > 0.005:
        return False, f"Weights sum to {total:.3f}, expected 1.0"

    return True, "OK"


# ======================================================================
# Main optimization logic
# ======================================================================

def optimize_sector_weights(
    sector_profile: str,
    entries: list[dict],
    current_weights: dict,
    model: str = "claude",
    window_preference: int | None = None,
    dry_run: bool = False,
) -> dict:
    """
    1 セクタープロファイルの重みを最適化する。

    Returns:
        {
            "sector_profile": str,
            "current_weights": dict,
            "proposed_weights": dict | None,
            "reasoning": str,
            "analysis": dict,   # window → stats
            "applied": bool,
            "skip_reason": str | None,
        }
    """
    windows = [window_preference] if window_preference else list(WINDOWS)
    analysis: dict[int, Any] = {}
    for w in windows:
        analysis[w] = compute_axis_correlations(entries, w)

    total_verified = sum(
        (s["total"] for s in analysis.values() if s is not None), 0
    )

    result: dict = {
        "sector_profile": sector_profile,
        "current_weights": copy.deepcopy(current_weights),
        "proposed_weights": None,
        "reasoning": "",
        "analysis": analysis,
        "applied": False,
        "skip_reason": None,
    }

    if total_verified == 0:
        result["skip_reason"] = f"No verified entries for sector_profile={sector_profile}"
        logger.warning(f"  ⚠️  スキップ: {result['skip_reason']}")
        return result

    # 統計がある場合でも LLM 呼び出しはサンプル不足の場合はスキップ
    has_sufficient = any(s is not None for s in analysis.values())
    if not has_sufficient:
        result["skip_reason"] = (
            f"All windows have < {MIN_SAMPLES} verified entries "
            f"(total={total_verified}). "
            "Run verify_predictions.py after 30+ days to accumulate data."
        )
        logger.warning(f"  ⚠️  スキップ: {result['skip_reason']}")
        return result

    prompt = build_weight_proposal_prompt(
        sector_profile=sector_profile,
        current_weights=current_weights,
        analysis_data=analysis,
    )

    logger.info(f"  🤖 LLM ({model}) に重み提案を依頼中...")
    try:
        llm_caller = _get_llm_caller(model)
        response = llm_caller(prompt)
    except Exception as e:
        result["skip_reason"] = f"LLM call failed: {e}"
        logger.error(f"  ❌ LLM 呼び出し失敗: {e}")
        return result

    proposal = parse_weight_proposal(response)
    if proposal is None:
        result["skip_reason"] = f"LLM response could not be parsed: {response[:200]}"
        logger.error(f"  ❌ レスポンスのパース失敗")
        return result

    proposed = proposal["proposed_weights"]
    ok, msg = validate_weights(proposed)
    if not ok:
        result["skip_reason"] = f"Weight validation failed: {msg}"
        logger.error(f"  ❌ バリデーション失敗: {msg}")
        return result

    result["proposed_weights"] = proposed
    result["reasoning"] = proposal.get("reasoning", "")

    if dry_run:
        logger.info(f"  [DRY-RUN] 変更前: {current_weights}")
        logger.info(f"  [DRY-RUN] 変更後: {proposed}")
        logger.info(f"  [DRY-RUN] 理由: {result['reasoning'][:120]}")
    else:
        result["applied"] = True
        logger.info(f"  ✅ 重み更新: {current_weights} → {proposed}")
        logger.info(f"  💬 理由: {result['reasoning'][:120]}")

    return result


def run_weight_optimization(
    sector_filter: str | None = None,
    window_preference: int | None = None,
    model: str = "claude",
    dry_run: bool = False,
) -> list[dict]:
    """
    全セクタープロファイル（またはフィルタ指定）の重みを最適化して
    config.json を更新する。

    Returns: 各セクタープロファイルの最適化結果リスト
    """
    config  = load_config()
    results = load_results()

    sector_profiles = config.get("sector_profiles", {})
    if not sector_profiles:
        logger.error("config.json に sector_profiles が見つかりません")
        return []

    # 銘柄エントリを sector_profile にグルーピング
    grouped: dict[str, list[dict]] = {name: [] for name in sector_profiles}
    for ticker, tdata in results.items():
        sector = tdata.get("sector", "")
        profile_name = resolve_sector_profile(sector, config)
        if profile_name and profile_name in grouped:
            for entry in tdata.get("history", []):
                grouped[profile_name].append(entry)

    optimization_results = []
    updated_config = copy.deepcopy(config)

    for profile_name, profile in sector_profiles.items():
        if sector_filter and profile_name != sector_filter:
            continue

        logger.info(f"\n🔍 セクタープロファイル: {profile_name} "
                    f"({len(grouped[profile_name])} エントリ)")

        current_weights = profile.get("weights", {})
        entries = grouped[profile_name]

        opt_result = optimize_sector_weights(
            sector_profile=profile_name,
            entries=entries,
            current_weights=current_weights,
            model=model,
            window_preference=window_preference,
            dry_run=dry_run,
        )
        optimization_results.append(opt_result)

        if opt_result["applied"] and not dry_run:
            updated_config["sector_profiles"][profile_name]["weights"] = (
                opt_result["proposed_weights"]
            )

    if not dry_run:
        applied = [r for r in optimization_results if r["applied"]]
        if applied:
            save_config(updated_config)
            logger.info(f"\n✅ config.json を更新しました ({len(applied)} セクター)")
        else:
            logger.info("\nℹ️  更新なし（スキップまたは変更なし）")

    _append_accuracy_history(optimization_results, updated_config)

    return optimization_results


def _append_accuracy_history(opt_results: list[dict], config: dict) -> None:
    """精度統計スナップショットを data/accuracy_history.json に追記する。"""
    history = load_accuracy_history()

    now = datetime.now().isoformat()
    for r in opt_results:
        for window, stats in r["analysis"].items():
            if stats is None:
                continue
            snapshot = {
                "timestamp": now,
                "sector_profile": r["sector_profile"],
                "regime": None,  # 現状はレジーム分解なし（将来拡張）
                "window": window,
                "total": stats["total"],
                "hits": stats["hits"],
                "win_rate": stats["win_rate"],
                "avg_return": stats["avg_return"],
                "axis_correlations": stats["axis_correlations"],
                "weights_before": r["current_weights"],
                "weights_after": r["proposed_weights"],
            }
            history["snapshots"].append(snapshot)

    # current_weights を最新 config から更新
    for name, profile in config.get("sector_profiles", {}).items():
        history["current_weights"][name] = profile.get("weights", {})

    save_accuracy_history(history)
    logger.info(f"📊 accuracy_history.json を更新しました "
                f"({len(history['snapshots'])} スナップショット)")


# ======================================================================
# CLI
# ======================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="予測精度フィードバック: sector_profiles の重みを自動最適化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  ./venv/bin/python3 src/weight_optimizer.py --dry-run
  ./venv/bin/python3 src/weight_optimizer.py --sector high_growth
  ./venv/bin/python3 src/weight_optimizer.py --window 30 --model gemini
        """,
    )
    parser.add_argument("--sector", metavar="PROFILE",
                        help="対象セクタープロファイル (high_growth / value / healthcare / financial)")
    parser.add_argument("--window", type=int, choices=[30, 90, 180],
                        help="使用する検証ウィンドウ (デフォルト: 全て)")
    parser.add_argument("--model", default="claude", choices=["claude", "gemini"],
                        help="LLM モデル (デフォルト: claude)")
    parser.add_argument("--dry-run", action="store_true",
                        help="提案を表示するが config.json を変更しない")
    args = parser.parse_args()

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}予測精度フィードバックループ 開始")
    print(f"  モデル: {args.model}  |  セクター: {args.sector or '全て'}  "
          f"|  ウィンドウ: {args.window or '全て'}")

    results = run_weight_optimization(
        sector_filter=args.sector,
        window_preference=args.window,
        model=args.model,
        dry_run=args.dry_run,
    )

    print("\n" + "=" * 60)
    print("最適化サマリー")
    print("=" * 60)
    for r in results:
        status = "✅ 適用" if r["applied"] else (
            "👁️  DRY-RUN" if r["proposed_weights"] and args.dry_run
            else f"⏭️  スキップ: {r.get('skip_reason', '')[:60]}"
        )
        print(f"\n{r['sector_profile']}: {status}")
        if r["proposed_weights"]:
            prev = r["current_weights"]
            prop = r["proposed_weights"]
            for ax in AXES:
                diff = prop.get(ax, 0) - prev.get(ax, 0)
                arrow = "↑" if diff > 0.001 else ("↓" if diff < -0.001 else "→")
                print(f"  {ax:15s}: {prev.get(ax, 0):.2f} → {prop.get(ax, 0):.2f}  {arrow}")
        elif r.get("skip_reason"):
            print(f"  理由: {r['skip_reason']}")


if __name__ == "__main__":
    main()
