"""
src/backtest_reporter.py - LLMフィードバック用バックテストレポートビルダー
==========================================================================
論文「大規模言語モデルを用いた株式投資戦略の自動生成におけるフィードバック設計」
(2026_193.pdf) に基づき、以下3レベルのフィードバックパッケージを構築する。

P1: 基本指標（Sharpe、MDD、勝率、レジーム別サマリー）
P2: P1 + エグジット理由別内訳 + レジーム重みとの差分（実績vs設定）
P3: P2 + equity curve の折れ線プロット（base64画像）

論文の知見:
- P1→P2/P3 の P&L 改善効果は平均的に限定的（±1%程度）
- ただし P3（プロット付き）はレジーム適応型実装を誘発する
- まず P1 で十分; P2/P3 は用途に応じて選択
"""

from __future__ import annotations

import base64
import io
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# P1: 基本指標フィードバック（テキスト）
# ---------------------------------------------------------------------------

def _format_regime_breakdown(regime_breakdown: dict) -> str:
    if not regime_breakdown:
        return "  (レジーム別データなし)"
    lines = []
    for regime, stats in sorted(regime_breakdown.items()):
        lines.append(
            f"  {regime:20s}: {stats['trades']:2d}回, "
            f"勝率 {stats['win_rate']:5.1f}%, "
            f"平均リターン {stats['avg_return']:+.2f}%"
        )
    return "\n".join(lines)


def _format_exit_reasons(exit_reason_breakdown: dict) -> str:
    if not exit_reason_breakdown:
        return "  (エグジットデータなし)"
    lines = []
    for reason, stats in sorted(exit_reason_breakdown.items(), key=lambda x: -x[1]["count"]):
        lines.append(
            f"  {reason:25s}: {stats['count']:2d}回, "
            f"勝率 {stats['win_rate']:5.1f}%, "
            f"平均リターン {stats['avg_return']:+.2f}%"
        )
    return "\n".join(lines)


def _format_available_params(strategy: str, current_config: dict | None = None) -> str:
    """PARAM_BOUNDS から利用可能なパラメータキーと安全範囲・現在値をフォーマットする。"""
    from src.llm_strategy_optimizer import PARAM_BOUNDS
    bounds = PARAM_BOUNDS.get(strategy, {})
    if not bounds:
        return "  (利用可能なパラメータなし)"

    s_cfg = {}
    if current_config:
        s_cfg = current_config.get("strategies", {}).get(strategy, {})

    lines = []
    for key, (lo, hi) in bounds.items():
        # 現在値を取得
        parts = key.split(".")
        cur_val = s_cfg
        for p in parts:
            cur_val = cur_val.get(p, {}) if isinstance(cur_val, dict) else "?"
        if isinstance(cur_val, dict):
            cur_val = "?"
        lines.append(f"  {key}: range [{lo}, {hi}], current={cur_val}")
    return "\n".join(lines)


def _build_param_json_template(strategy: str) -> str:
    """PARAM_BOUNDS のキーを使って param_updates の JSON テンプレートを生成する。"""
    from src.llm_strategy_optimizer import PARAM_BOUNDS
    bounds = PARAM_BOUNDS.get(strategy, {})
    if not bounds:
        return '    "entry.rsi_threshold": null'

    type_hint = {
        "exit.time_stop_bars": "integer", "entry.gc_lookback_days": "integer",
        "exit.time_stop_bars": "integer",
    }
    items = []
    for key, (lo, hi) in bounds.items():
        hint = "integer" if isinstance(lo, int) and isinstance(hi, int) else "number"
        items.append(f'    "{key}": <{hint} or null>')
    return ",\n".join(items)


def build_p1_prompt(backtest_result: dict, strategy: str, ticker: str, config: dict | None = None) -> str:
    """P1: 基本的なバックテスト指標のテキストフィードバック（論文 Prompt 1 相当）"""
    r = backtest_result
    regime_section = _format_regime_breakdown(r.get("regime_breakdown", {}))
    available_params = _format_available_params(strategy, config)
    param_template = _build_param_json_template(strategy)

    return f"""You are a quantitative investment strategy analyst.
Below are the backtest results of the {strategy} strategy for {ticker} ({r.get('period', 'N/A')}).
Based on the metrics, provide a comprehensive analysis and propose specific parameter improvements.
Do not rewrite strategy logic — only suggest parameter value changes from the Available Parameters list below.

If the strategy already meets production criteria (Sharpe > 1.0, Win Rate > 50%, Max Drawdown better than -20%),
ONLY output "APPROVED" and nothing else.

### Backtest Metrics
- Total Return:     {r.get('total_return_pct', 0):+.2f}%
- Benchmark Return: {r.get('benchmark_return_pct', 0):+.2f}%
- Alpha:            {r.get('alpha', 0):+.2f}%
- Win Rate:         {r.get('win_rate_pct', 0):.1f}%
- Sharpe Ratio:     {r.get('sharpe_ratio', 0):.2f}
- Max Drawdown:     {r.get('max_drawdown_pct', 0):.2f}%
- Profit Factor:    {r.get('profit_factor', 0):.2f}
- Trade Count:      {r.get('trade_count', 0)}

### Regime Breakdown
{regime_section}

### Available Parameters (only these keys may be changed)
{available_params}

### Required Output Format
Respond with a brief analysis (2-3 sentences) followed by parameter suggestions in this exact JSON block:
```json
{{
  "analysis": "Brief explanation of key issues",
  "param_updates": {{
{param_template}
  }}
}}
```
Set parameters you do not want to change to null.
"""


def build_p2_prompt(backtest_result: dict, strategy: str, ticker: str, config: dict | None = None) -> str:
    """P2: P1 + エグジット理由内訳 + レジーム重みとの実績差分（論文 Prompt 2 相当）"""
    r = backtest_result

    regime_section = _format_regime_breakdown(r.get("regime_breakdown", {}))
    exit_section = _format_exit_reasons(r.get("exit_reason_breakdown", {}))
    available_params = _format_available_params(strategy, config)
    param_template = _build_param_json_template(strategy)

    # レジーム重みの設定値をテキスト化（config がある場合）
    weight_section = ""
    if config:
        from src.macro_regime import REGIME_WEIGHT_TABLE, JP_REGIME_WEIGHT_TABLE
        is_jp = ticker.endswith(".T") if ticker else False
        table = JP_REGIME_WEIGHT_TABLE if is_jp else REGIME_WEIGHT_TABLE
        weight_lines = []
        for regime, stats in (r.get("regime_breakdown") or {}).items():
            weights = table.get(regime, {}).get("_default", {})
            if weights:
                weight_lines.append(
                    f"  {regime}: fundamental={weights.get('fundamental', 0):+.2f}, "
                    f"valuation={weights.get('valuation', 0):+.2f}, "
                    f"technical={weights.get('technical', 0):+.2f}"
                )
        if weight_lines:
            weight_section = "\n### Current Regime Weight Adjustments\n" + "\n".join(weight_lines)

    return f"""You are a quantitative investment strategy analyst.
Below are the backtest results of the {strategy} strategy for {ticker} ({r.get('period', 'N/A')}).
Analyze the regime breakdown and exit reason distribution to propose targeted parameter improvements.
Do not rewrite strategy logic — only suggest parameter value changes from the Available Parameters list below.

If the strategy already meets production criteria (Sharpe > 1.0, Win Rate > 50%, Max Drawdown better than -20%),
ONLY output "APPROVED" and nothing else.

### Backtest Metrics
- Total Return:     {r.get('total_return_pct', 0):+.2f}%
- Benchmark Return: {r.get('benchmark_return_pct', 0):+.2f}%
- Alpha:            {r.get('alpha', 0):+.2f}%
- Win Rate:         {r.get('win_rate_pct', 0):.1f}%
- Sharpe Ratio:     {r.get('sharpe_ratio', 0):.2f}
- Max Drawdown:     {r.get('max_drawdown_pct', 0):.2f}%
- Profit Factor:    {r.get('profit_factor', 0):.2f}
- Trade Count:      {r.get('trade_count', 0)}

### Regime Breakdown
{regime_section}

### Exit Reason Breakdown
{exit_section}
{weight_section}

### Available Parameters (only these keys may be changed)
{available_params}

### Required Output Format
```json
{{
  "analysis": "Brief explanation focusing on regime and exit patterns",
  "param_updates": {{
{param_template}
  }}
}}
```
"""


def build_p3_prompt(backtest_result: dict, strategy: str, ticker: str, config: dict | None = None) -> tuple[str, str | None]:
    """P3: P2 + equity curve プロット画像（マルチモーダル、論文 Prompt 3 相当）

    Returns:
        (text_prompt, base64_image_or_None)
    """
    text_prompt = build_p2_prompt(backtest_result, strategy, ticker, config)

    # プロット生成を試みる
    plot_b64 = _generate_equity_plot(backtest_result)

    if plot_b64:
        text_prompt = text_prompt.replace(
            "Below are the backtest results",
            "Below are the backtest results (including equity curve plot)"
        )

    return text_prompt, plot_b64


def _generate_equity_plot(backtest_result: dict) -> str | None:
    """equity curve を matplotlib で生成し、base64 エンコードした PNG を返す。失敗時は None。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime

        history = backtest_result.get("history", [])
        if not history:
            return None

        dates = [h["date"] if isinstance(h["date"], datetime) else datetime.fromisoformat(str(h["date"])) for h in history]
        values = [h["value"] for h in history]
        initial = backtest_result.get("initial_capital", 1_000_000)

        cumulative = [(v / initial - 1) * 100 for v in values]

        # ドローダウン計算
        peak = initial
        drawdowns = []
        for v in values:
            peak = max(peak, v)
            drawdowns.append((v / peak - 1) * 100)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

        ax1.plot(dates, cumulative, color="steelblue", linewidth=1.5, label="Strategy")
        ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
        ax1.set_ylabel("Cumulative Return (%)")
        ax1.set_title(f"Equity Curve – {backtest_result.get('period', '')}")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)

        ax2.fill_between(dates, drawdowns, 0, color="crimson", alpha=0.4, label="Drawdown")
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Date")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.autofmt_xdate()
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=80, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

    except Exception:
        return None


# ---------------------------------------------------------------------------
# プロンプトレベル別ディスパッチャ
# ---------------------------------------------------------------------------

def build_feedback_prompt(
    backtest_result: dict,
    strategy: str,
    ticker: str,
    level: str = "P1",
    config: dict | None = None,
) -> tuple[str, str | None]:
    """
    フィードバックプロンプトを構築する。

    Args:
        backtest_result: backtester.calculate_performance() の返り値
        strategy: 戦略名 ("bounce" / "breakout" / "long")
        ticker: 銘柄コード
        level: "P1" / "P2" / "P3"
        config: config.json の内容（全レベルで使用: 現在値表示・レジーム重み取得）

    Returns:
        (text_prompt, base64_image_or_None)
        P1/P2 の場合、base64_image は常に None
    """
    if level == "P3":
        return build_p3_prompt(backtest_result, strategy, ticker, config)
    elif level == "P2":
        return build_p2_prompt(backtest_result, strategy, ticker, config), None
    else:
        return build_p1_prompt(backtest_result, strategy, ticker, config), None


# ---------------------------------------------------------------------------
# LLMレスポンスのパース
# ---------------------------------------------------------------------------

def parse_param_suggestions(llm_response: str) -> dict | None:
    """
    LLM の返答から JSON パラメータ提案を抽出する。

    Returns:
        {"analysis": str, "param_updates": dict} または None（APPROVED / パース失敗時）
    """
    if not llm_response:
        return None

    # APPROVED 判定（前後の空白・改行を除去して確認）
    stripped = llm_response.strip()
    if stripped == "APPROVED" or stripped.startswith("APPROVED"):
        return {"approved": True, "analysis": "Strategy meets production criteria."}

    import re

    # 1. マークダウンコードブロック内の JSON を抽出（最優先）
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # 2. 最外周の {} を見つけてネストを追跡しながら抽出
        json_str = _extract_outermost_json(stripped)

    if not json_str:
        return None

    try:
        data = json.loads(json_str)
        if "param_updates" not in data:
            return None
        # null をフィルタリング
        updates = {k: v for k, v in data["param_updates"].items() if v is not None}
        return {
            "approved": False,
            "analysis": data.get("analysis", ""),
            "param_updates": updates,
        }
    except (json.JSONDecodeError, KeyError):
        return None


def _extract_outermost_json(text: str) -> str | None:
    """ブレースのネスト深度を追跡して最外周の JSON オブジェクトを抽出する。"""
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:i + 1]
    return None
