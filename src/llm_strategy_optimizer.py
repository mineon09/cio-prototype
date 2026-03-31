"""
src/llm_strategy_optimizer.py - LLMによる戦略パラメータ最適化モジュール
==========================================================================
論文「大規模言語モデルを用いた株式投資戦略の自動生成におけるフィードバック設計」
に基づく反復的戦略改善ループ。

論文の知見に基づくモデル優先順位（P&L改善幅の実績）:
  1. Claude (Anthropic) - 平均 +14.1% (最良; 既存構造を保持した局所改善)
  2. Gemini              - 平均 +7.3%  (良; 探索的・高分散)
  3. GPT-4o (GitHub Models) - 平均 -0.3% (フォールバック; 保守的・低変更率)

使用例:
    from src.llm_strategy_optimizer import optimize_strategy
    result = optimize_strategy(
        ticker="8035.T",
        strategy="bounce",
        start_date="2023-01-01",
        months=12,
        model="claude",      # "claude" / "gemini" / "gpt-4o"
        level="P1",          # "P1" / "P2" / "P3"
        max_iter=5,
        dry_run=True,
    )
"""

from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# パラメータ境界定義（LLMが変更可能な値の安全範囲）
# ---------------------------------------------------------------------------

PARAM_BOUNDS: dict[str, dict[str, tuple]] = {
    "bounce": {
        "entry.rsi_threshold":     (20.0, 50.0),
        "entry.volume_multiplier": (1.1,  3.0),
        "entry.bb_std":            (1.5,  3.0),
        "entry.scoring_threshold": (1.0,  5.5),
        "entry.scoring_weights.rsi":  (0.0, 3.0),
        "entry.scoring_weights.bb":   (0.0, 3.0),
        "entry.scoring_weights.vol":  (0.0, 3.0),
        "entry.scoring_weights.ma75": (0.0, 4.0),
        "exit.hard_stop_pct":      (-10.0, -1.0),
        "exit.take_profit_pct":    (2.0,  20.0),
        "exit.time_stop_bars":     (3,    30),
        "exit.stop_loss_atr_multiplier":   (0.5, 3.0),
        "exit.take_profit_atr_multiplier": (1.0, 5.0),
        "exit.atr_trailing_multiplier":    (0.5, 4.0),
        "exit.atr_trailing_activation_pct": (0.5, 5.0),
    },
    "breakout": {
        "entry.volume_multiplier": (1.1,  3.0),
        "entry.gc_lookback_days":  (1,    10),
        "entry.scoring_threshold": (3.0,  9.0),
        "entry.scoring_weights.close_break": (0.0, 4.0),
        "entry.scoring_weights.bullish":     (0.0, 2.0),
        "entry.scoring_weights.ma75":        (0.0, 4.0),
        "entry.scoring_weights.atr_pct":     (0.0, 3.0),
        "entry.scoring_weights.adx":         (0.0, 3.0),
        "entry.scoring_weights.cmf":         (0.0, 3.0),
        "entry.scoring_weights.vol":         (0.0, 2.0),
        "entry.scoring_weights.gc":          (0.0, 2.0),
        "exit.take_profit_pct":    (5.0,  30.0),
        "exit.time_stop_bars":     (10,   60),
        "exit.stop_loss_atr_multiplier": (1.0, 5.0),
        "exit.chandelier_tight_mult":    (1.0, 3.0),
        "exit.chandelier_mid_mult":      (1.5, 4.0),
        "exit.chandelier_loose_mult":    (2.0, 5.0),
    },
    "long": {
        "signals.BUY.min_score":   (4.0, 9.0),
        "signals.SELL.max_score":  (2.0, 6.0),
    },
}

# ---------------------------------------------------------------------------
# 過学習防止ガードレール（全イテレーション共通）
# ---------------------------------------------------------------------------

GUARD_PROMPT = """
### Overfitting Prevention Constraints (MUST FOLLOW)
1. Change at most 2 parameters per iteration.
2. Keep each parameter change within ±50% of its current value.
3. Do not push entry conditions so strict that expected annual trade count falls below 3.
4. Always provide a specific reason for each parameter change (citing regime/exit data above).
5. If the latest iteration performed WORSE than the previous, prioritize diagnosing the cause
   and propose at most 1 parameter change to investigate.
6. Do not reverse a change made in the immediately prior iteration unless you explicitly state
   why the original direction was wrong.
"""



def _get_llm_caller(model: str):
    """
    モデル名に応じたLLM呼び出し関数を返す。
    戻り値: callable(prompt: str, image_b64: str | None) -> str

    優先順位（論文の結果に基づく）:
      claude  → Anthropic API (ANTHROPIC_API_KEY)
      gemini  → Google Gemini API (GEMINI_API_KEY)
      gpt-4o  → GitHub Models API (gh auth token)
    """
    model_lower = model.lower()

    if "claude" in model_lower:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key and "your_" not in api_key:
            try:
                import anthropic

                def call_claude(prompt: str, image_b64: str | None = None) -> str:
                    client = anthropic.Anthropic(api_key=api_key)
                    content: list[dict] = []
                    if image_b64:
                        content.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
                        })
                    content.append({"type": "text", "text": prompt})
                    message = client.messages.create(
                        model="claude-sonnet-4-5",
                        max_tokens=2048,
                        messages=[{"role": "user", "content": content}],
                    )
                    return message.content[0].text

                logger.info("LLM: Claude (Anthropic API) を使用")
                return call_claude
            except ImportError:
                logger.warning("anthropic パッケージ未インストール。Gemini にフォールバック。")
        else:
            logger.warning("ANTHROPIC_API_KEY 未設定。Gemini にフォールバック。")

    if "gemini" in model_lower or "claude" in model_lower:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key and "your_" not in gemini_key:
            try:
                from src.data_fetcher import call_gemini

                def call_gemini_wrapper(prompt: str, image_b64: str | None = None) -> str:
                    # Gemini はマルチモーダル対応だが、既存の call_gemini はテキストのみ
                    # 画像がある場合はプロンプトにその旨を付記する
                    full_prompt = prompt
                    if image_b64:
                        full_prompt += "\n\n[Note: An equity curve plot image was generated but cannot be attached in this API call. Please focus on the text metrics above.]"
                    result, _ = call_gemini(full_prompt, parse_json=False)
                    return result

                logger.info("LLM: Gemini API を使用")
                return call_gemini_wrapper
            except Exception as e:
                logger.warning(f"Gemini 初期化失敗: {e}。GitHub Models にフォールバック。")

    # フォールバック: GitHub Models (GPT-4o)
    try:
        from src.copilot_client import call_github_models

        def call_github(prompt: str, image_b64: str | None = None) -> str:
            result, _ = call_github_models(prompt, model="gpt-4o", temperature=1.0)
            return result

        logger.info("LLM: GitHub Models (GPT-4o) を使用")
        return call_github
    except Exception as e:
        raise RuntimeError(f"利用可能な LLM クライアントがありません: {e}") from e


# ---------------------------------------------------------------------------
# パラメータ検証・クリッピング
# ---------------------------------------------------------------------------

def merge_ticker_override(config: dict, ticker: str) -> dict:
    """
    ticker_overrides セクションを base strategies に手動マージする。

    `run_backtest(config_override=cfg)` 呼び出し時、ticker_overrides は自動適用されないため、
    手動バックテスト・テストコードでは `load_config_with_overrides` の代わりにこの関数を使う。

    Args:
        config: config.json を読み込んだ辞書
        ticker: 銘柄コード (例: "8035.T")

    Returns:
        ticker_override がマージされた新しい config 辞書
    """
    result = copy.deepcopy(config)
    override = result.get("ticker_overrides", {}).get(ticker, {})
    for strategy_name, strategy_override in override.get("strategies", {}).items():
        base_strategy = result.setdefault("strategies", {}).setdefault(strategy_name, {})
        for section_name, section_override in strategy_override.items():
            if section_name in ("enabled_regimes",):
                base_strategy[section_name] = section_override
            elif isinstance(section_override, dict):
                base_strategy.setdefault(section_name, {}).update(section_override)
            elif not section_name.startswith("_"):
                base_strategy[section_name] = section_override
    return result



    """
    LLMが提案したパラメータ更新を境界チェックし、安全な範囲にクリップする。

    Args:
        updates: {"entry.rsi_threshold": 28, ...}
        strategy: 戦略名

    Returns:
        検証済みのパラメータ辞書（無効なキーは除外）
    """
    bounds = PARAM_BOUNDS.get(strategy, {})
    validated = {}

    for key, value in updates.items():
        if value is None:
            continue
        if key not in bounds:
            logger.debug(f"  未知のパラメータキー '{key}' をスキップ")
            continue

        lo, hi = bounds[key]
        try:
            # 整数境界の場合は int にキャスト
            if isinstance(lo, int) and isinstance(hi, int):
                v = int(round(float(value)))
            else:
                v = float(value)

            clipped = max(lo, min(hi, v))
            if clipped != v:
                logger.warning(f"  パラメータ '{key}' = {v} → {clipped} にクリップ (境界: {lo}〜{hi})")
            validated[key] = clipped
        except (ValueError, TypeError) as e:
            logger.warning(f"  パラメータ '{key}' の値 '{value}' が無効: {e}")

    return validated


# ---------------------------------------------------------------------------
# 設定への適用
# ---------------------------------------------------------------------------

def apply_param_updates(config: dict, updates: dict, strategy: str) -> dict:
    """
    検証済みのパラメータ更新を config 辞書に適用する（元の config は変更しない）。

    パラメータキー形式:
      "entry.rsi_threshold"          → config["strategies"][strategy]["entry"]["rsi_threshold"]
      "entry.scoring_weights.rsi"    → config["strategies"][strategy]["entry"]["scoring_weights"]["rsi"]
      "signals.BUY.min_score"        → config["signals"]["BUY"]["min_score"]

    Returns:
        更新済みの新しい config 辞書（ディープコピー）
    """
    new_config = copy.deepcopy(config)

    for key, value in updates.items():
        parts = key.split(".")

        if parts[0] in ("entry", "exit"):
            # strategies.<strategy>.entry/exit.<param> [.<subparam>...]
            section = new_config.setdefault("strategies", {}).setdefault(strategy, {})
            subsection = section.setdefault(parts[0], {})
            # Navigate remaining parts, creating dicts as needed
            target = subsection
            for part in parts[1:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
            logger.info(f"  ✅ config.strategies.{strategy}.{key} = {value}")

        elif parts[0] == "signals":
            # signals.<BUY/SELL>.<param>
            sig_section = new_config.setdefault("signals", {})
            if len(parts) >= 3:
                sig_section.setdefault(parts[1], {})[parts[2]] = value
                logger.info(f"  ✅ config.signals.{parts[1]}.{parts[2]} = {value}")

        else:
            logger.warning(f"  未対応のキー形式: '{key}'")

    return new_config


# ---------------------------------------------------------------------------
# メイン最適化ループ
# ---------------------------------------------------------------------------

def optimize_strategy(
    ticker: str,
    strategy: str,
    start_date: str,
    months: int = 12,
    model: str = "claude",
    level: str = "P1",
    max_iter: int = 5,
    dry_run: bool = False,
    save_history: bool = True,
) -> dict:
    """
    LLMによる戦略パラメータ最適化ループを実行する。

    論文の実験設定に準拠:
    - 停止条件: LLMが "APPROVED" を出力 または max_iter 到達
    - temperature: 1.0 (デフォルト、論文と同じ)
    - 反復ごとにバックテスト → フィードバック生成 → LLM → パラメータ更新

    Args:
        ticker:      銘柄コード (例: "8035.T", "AAPL")
        strategy:    戦略名 ("bounce" / "breakout" / "long")
        start_date:  バックテスト開始日 (YYYY-MM-DD)
        months:      バックテスト期間（月数）
        model:       LLMモデル ("claude" / "gemini" / "gpt-4o")
        level:       フィードバックレベル ("P1" / "P2" / "P3")
        max_iter:    最大反復回数（デフォルト5、論文は10）
        dry_run:     True の場合、LLMの提案を表示するが設定を変更しない
        save_history: 最適化履歴をJSONファイルに保存するか

    Returns:
        {
            "ticker": str,
            "strategy": str,
            "model": str,
            "level": str,
            "iterations": int,
            "approved": bool,
            "initial_performance": dict,
            "final_performance": dict,
            "improvement_pct": float,  # 年率換算P&L改善幅（%）
            "config_changes": list[dict],
            "history": list[dict],
        }
    """
    from src.backtester import run_backtest
    from src.backtest_reporter import build_feedback_prompt, parse_param_suggestions
    from src.utils import load_config_with_overrides

    logger.info(f"🔬 最適化開始: {ticker} ({strategy}) | model={model} | level={level} | max_iter={max_iter}")

    # 初期設定の読み込み
    try:
        config = load_config_with_overrides(ticker)
    except Exception as e:
        logger.warning(f"設定読み込み失敗、デフォルト設定を使用: {e}")
        config = {}

    llm_caller = _get_llm_caller(model)

    optimization_history: list[dict] = []
    config_changes: list[dict] = []
    current_config = copy.deepcopy(config)
    approved = False
    initial_perf: dict | None = None

    for iteration in range(max_iter):
        logger.info(f"\n--- 反復 {iteration + 1}/{max_iter} ---")

        # バックテスト実行（更新済み current_config を使用）
        bt_result = run_backtest(
            ticker=ticker,
            start_date_str=start_date,
            duration_months=months,
            strategy=strategy,
            config_override=current_config,
        )

        if "error" in bt_result:
            logger.error(f"バックテストエラー: {bt_result['error']}")
            break

        if initial_perf is None:
            initial_perf = bt_result.copy()

        logger.info(
            f"  バックテスト: Total={bt_result.get('total_return_pct', 0):+.2f}% | "
            f"Sharpe={bt_result.get('sharpe_ratio', 0):.2f} | "
            f"WinRate={bt_result.get('win_rate_pct', 0):.1f}% | "
            f"MaxDD={bt_result.get('max_drawdown_pct', 0):.2f}%"
        )

        # フィードバックプロンプト構築（ガードレール付加）
        prompt_text, image_b64 = build_feedback_prompt(
            backtest_result=bt_result,
            strategy=strategy,
            ticker=ticker,
            level=level,
            config=current_config,
        )

        # 変更履歴をプロンプトに追記（過学習防止・コンテキスト維持）
        if config_changes:
            history_lines = ["### Parameter Change History (Do NOT reverse without justification)"]
            for ch in config_changes:
                history_lines.append(f"  Iter {ch['iteration']}: {ch['updates']}")
                if ch.get("analysis"):
                    history_lines.append(f"    Reason: {ch['analysis'][:120]}")
            prompt_text = prompt_text + "\n" + "\n".join(history_lines) + "\n"

        prompt_text = prompt_text + GUARD_PROMPT

        # LLM呼び出し
        try:
            logger.info(f"  LLM ({model}) に送信中...")
            llm_response = llm_caller(prompt_text, image_b64)
            logger.debug(f"  LLM応答 (先頭200文字): {llm_response[:200]}")
        except Exception as e:
            logger.error(f"  LLM呼び出し失敗: {e}")
            break

        # レスポンスのパース
        parsed = parse_param_suggestions(llm_response)

        iteration_record: dict[str, Any] = {
            "iteration": iteration + 1,
            "backtest": {
                "total_return_pct": bt_result.get("total_return_pct"),
                "sharpe_ratio": bt_result.get("sharpe_ratio"),
                "win_rate_pct": bt_result.get("win_rate_pct"),
                "max_drawdown_pct": bt_result.get("max_drawdown_pct"),
                "trade_count": bt_result.get("trade_count"),
            },
            "llm_response_preview": llm_response[:500],
            "parsed": parsed,
        }

        if parsed is None:
            logger.warning("  ⚠️ LLM応答のパースに失敗（有効な提案なし）")
            optimization_history.append(iteration_record)
            continue

        if parsed.get("approved"):
            logger.info("  ✅ LLMが 'APPROVED' を出力 — 最適化完了")
            approved = True
            optimization_history.append(iteration_record)
            break

        # パラメータ更新
        raw_updates = parsed.get("param_updates", {})
        if not raw_updates:
            logger.info("  提案なし（変更不要と判断）")
            optimization_history.append(iteration_record)
            continue

        validated_updates = _validate_param_updates(raw_updates, strategy)
        logger.info(f"  提案パラメータ ({len(validated_updates)}件): {validated_updates}")

        if dry_run:
            logger.info("  [DRY RUN] 実際の設定変更はスキップ")
            iteration_record["dry_run"] = True
        else:
            current_config = apply_param_updates(current_config, validated_updates, strategy)
            config_changes.append({
                "iteration": iteration + 1,
                "updates": validated_updates,
                "analysis": parsed.get("analysis", ""),
            })

        optimization_history.append(iteration_record)

    # 最終バックテスト（dry_run でも結果確認のため実行）
    final_bt = run_backtest(
        ticker=ticker,
        start_date_str=start_date,
        duration_months=months,
        strategy=strategy,
        config_override=current_config,
    )

    initial_return = (initial_perf or {}).get("total_return_pct", 0.0)
    final_return = final_bt.get("total_return_pct", 0.0) if "error" not in final_bt else initial_return
    # 年率換算の改善幅（月数で按分）
    annualized_improvement = (final_return - initial_return) * (12 / months) if months > 0 else 0.0

    result = {
        "ticker": ticker,
        "strategy": strategy,
        "model": model,
        "level": level,
        "start_date": start_date,
        "months": months,
        "iterations": len(optimization_history),
        "approved": approved,
        "dry_run": dry_run,
        "initial_performance": {
            k: v for k, v in (initial_perf or {}).items()
            if k not in ("trades", "history", "regime_breakdown", "exit_reason_breakdown")
        },
        "final_performance": {
            k: v for k, v in final_bt.items()
            if k not in ("trades", "history", "regime_breakdown", "exit_reason_breakdown")
        } if "error" not in final_bt else {"error": final_bt.get("error")},
        "improvement_pct": round(final_return - initial_return, 2),
        "annualized_improvement_pct": round(annualized_improvement, 2),
        "config_changes": config_changes,
        "history": optimization_history,
    }

    # 最適化履歴の保存
    if save_history and not dry_run:
        _save_optimization_result(result, ticker, strategy)

    logger.info(
        f"\n📊 最適化完了: {ticker} ({strategy})\n"
        f"  初期 P&L: {initial_return:+.2f}%\n"
        f"  最終 P&L: {final_return:+.2f}%\n"
        f"  改善幅:   {final_return - initial_return:+.2f}% "
        f"(年率換算: {annualized_improvement:+.2f}%)\n"
        f"  承認:     {'✅ APPROVED' if approved else '❌ 未承認'}"
    )

    return result


# ---------------------------------------------------------------------------
# 結果保存
# ---------------------------------------------------------------------------

def _save_optimization_result(result: dict, ticker: str, strategy: str) -> Path:
    """最適化結果を data/optimization/ に JSON 保存する。"""
    save_dir = Path("data") / "optimization"
    save_dir.mkdir(parents=True, exist_ok=True)

    safe_ticker = ticker.replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_ticker}_{strategy}_{timestamp}.json"
    filepath = save_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"💾 最適化結果を保存: {filepath}")
    return filepath
