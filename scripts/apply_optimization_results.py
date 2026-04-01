#!/usr/bin/env python3
"""
scripts/apply_optimization_results.py - 最適化結果の自動反映ツール
====================================================================
data/optimization/ に蓄積された最適化 JSON を読み込み、
config.json の ticker_overrides / sector_profiles を自動更新する。

【反映先マッピング】
  final_params（entry/exit） → ticker_overrides[ticker].strategies[strategy]
  disabled_regimes            → ticker_overrides[ticker].strategies[strategy].enabled_regimes
  sharpe > 1.0 の知見         → sector_profiles[sector].judgment_context

使い方:
    # 差分を確認するだけ（config.json は変更しない）
    ./venv/bin/python3 scripts/apply_optimization_results.py --dry-run

    # 全銘柄の最良結果を config.json に反映
    ./venv/bin/python3 scripts/apply_optimization_results.py

    # 特定銘柄のみ反映
    ./venv/bin/python3 scripts/apply_optimization_results.py --ticker 8035.T AMAT

    # 結果ディレクトリを指定
    ./venv/bin/python3 scripts/apply_optimization_results.py --result-dir data/optimization/ --dry-run
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PATH = PROJECT_ROOT / "config.json"
RESULT_DIR_DEFAULT = PROJECT_ROOT / "data" / "optimization"

# US レジーム全候補（config.json の us_regimes キーに対応）
US_REGIMES = ["FED_HIKE", "FED_PAUSE", "FED_CUT", "USD_STRONG", "RISK_ON", "RISK_OFF"]

# JP レジーム全候補
JP_REGIMES = [
    "RISK_ON", "RISK_OFF", "NEUTRAL", "RATE_HIKE", "RATE_CUT",
    "YIELD_INVERSION", "BOJ_HIKE", "YEN_WEAK", "YEN_STRONG", "NIKKEI_BULL",
]

# ticker → セクター名マッピング（config.json の sector_competitors を補完）
_TICKER_SECTOR_MAP: dict[str, str] = {
    "8035.T": "semiconductor",
    "6857.T": "semiconductor",
    "AMAT":   "semiconductor",
    "LRCX":   "semiconductor",
    "NVDA":   "semiconductor",
    "8306.T": "financial",
    "8316.T": "financial",
    "JPM":    "financial",
    "8053.T": "trading",
    "8058.T": "trading",
    "7203.T": "automotive",
    "XOM":    "energy",
    "CVX":    "energy",
    "TSLA":   "automotive",
}


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def _is_us_stock(ticker: str) -> bool:
    return not ticker.endswith(".T")


def get_sector(ticker: str, config: dict | None = None) -> str:
    """ticker からセクター名を返す。config.json の sector_competitors も参照。"""
    if ticker in _TICKER_SECTOR_MAP:
        return _TICKER_SECTOR_MAP[ticker]

    if config:
        for sector, tickers in config.get("sector_competitors", {}).items():
            if ticker in tickers:
                return sector

    return "unknown"


def _all_regimes(ticker: str) -> list[str]:
    """ticker に応じた全レジームリストを返す。"""
    return US_REGIMES if _is_us_stock(ticker) else JP_REGIMES


# ---------------------------------------------------------------------------
# 結果の読み込み
# ---------------------------------------------------------------------------

def load_optimization_results(
    results_dir: Path,
    ticker_filter: list[str] | None = None,
) -> dict[str, dict]:
    """
    results_dir 内の最適化 JSON を読み込み、ticker ごとに最良結果（Sharpe 最高）を返す。

    Returns:
        { ticker: best_result_dict, ... }
    """
    results_dir = Path(results_dir)
    if not results_dir.exists():
        print(f"⚠️ 結果ディレクトリが見つかりません: {results_dir}")
        return {}

    per_ticker: dict[str, list[dict]] = {}

    for json_file in sorted(results_dir.glob("*.json")):
        if json_file.name.startswith("baseline") or json_file.name.startswith("cross"):
            continue
        try:
            with open(json_file) as f:
                data = json.load(f)
        except Exception as e:
            print(f"  ⚠️ 読み込み失敗 ({json_file.name}): {e}")
            continue

        ticker = data.get("ticker")
        if not ticker:
            continue
        if ticker_filter and ticker not in ticker_filter:
            continue

        per_ticker.setdefault(ticker, []).append(data)

    # 各 ticker の最良結果（final_performance の sharpe_ratio が最高のもの）を選択
    best: dict[str, dict] = {}
    for ticker, runs in per_ticker.items():
        best_run = max(
            runs,
            key=lambda r: r.get("final_performance", {}).get("sharpe_ratio", -999),
        )
        best[ticker] = best_run
        fp = best_run.get("final_performance", {})
        print(
            f"  📊 {ticker:<10} strategy={best_run.get('strategy','?'):<10} "
            f"Sharpe={fp.get('sharpe_ratio', 0):.3f}  "
            f"Return={fp.get('total_return_pct', 0):+.2f}%  "
            f"Trades={fp.get('trade_count', 0)}  "
            f"Iter={best_run.get('iterations', 0)}"
        )

    return best


# ---------------------------------------------------------------------------
# config.json への反映
# ---------------------------------------------------------------------------

def _extract_final_params(result: dict) -> dict[str, Any]:
    """最適化結果から最終パラメータ（config_changes の最後の適用状態）を抽出する。"""
    config_changes = result.get("config_changes", [])
    if not config_changes:
        return {}

    # config_changes は累積適用済みなので最後の updates をマージ
    merged: dict[str, Any] = {}
    for change in config_changes:
        merged.update(change.get("updates", {}))
    return merged


def _extract_disabled_regimes(result: dict) -> list[str]:
    """
    最適化ノートや enabled_regimes から除外レジームを逆引きする。
    ticker_overrides に enabled_regimes が既に設定されていればそれを尊重する。
    """
    ticker = result.get("ticker", "")
    all_r = _all_regimes(ticker)

    # config_changes 内の enabled_regimes 変更を探す
    for change in reversed(result.get("config_changes", [])):
        updates = change.get("updates", {})
        for key, val in updates.items():
            if "enabled_regimes" in key and isinstance(val, list):
                return [r for r in all_r if r not in val]

    return []  # 変更なし = 全レジーム有効


def _build_override_entry(result: dict, existing_override: dict) -> dict:
    """
    ticker_overrides への書き込みエントリを構築する。
    既存の override と deep merge し、_optimization_note を更新する。
    """
    strategy = result.get("strategy", "bounce")
    ticker = result.get("ticker", "")
    fp = result.get("final_performance", {})
    sharpe = fp.get("sharpe_ratio", 0)
    total_return = fp.get("total_return_pct", 0)
    iters = result.get("iterations", 0)
    model = result.get("model", "?")
    start = result.get("start_date", "?")
    months = result.get("months", 0)

    # ベースとして既存の override をコピー
    new_override = copy.deepcopy(existing_override)
    strat_section = new_override.setdefault("strategies", {}).setdefault(strategy, {})

    # final_params を entry / exit に分割して適用
    final_params = _extract_final_params(result)
    for dotted_key, value in final_params.items():
        parts = dotted_key.split(".")
        # "entry.rsi_threshold" → strat_section["entry"]["rsi_threshold"]
        if len(parts) == 2:
            section, param = parts
            if section in ("entry", "exit"):
                strat_section.setdefault(section, {})[param] = value
        elif len(parts) == 3:
            section, sub, param = parts
            if section in ("entry", "exit"):
                strat_section.setdefault(section, {}).setdefault(sub, {})[param] = value

    # enabled_regimes の更新
    disabled = _extract_disabled_regimes(result)
    if disabled:
        all_r = _all_regimes(ticker)
        strat_section["enabled_regimes"] = [r for r in all_r if r not in disabled]

    # 最適化ノートを更新
    note = (
        f"LLM-optimized ({model} Iter{iters}): "
        f"{total_return:+.2f}%, Sharpe {sharpe:.2f}, "
        f"{months}M {start}"
    )
    strat_section["_optimization_note"] = note

    return new_override


def update_sector_profile(config: dict, sector: str, result: dict) -> None:
    """
    Sharpe > 1.0 の最適化知見をセクタープロファイルの judgment_context に反映する。
    既存の judgment_context があれば追記する。
    """
    fp = result.get("final_performance", {})
    sharpe = fp.get("sharpe_ratio", 0)
    if sharpe <= 1.0:
        return

    ticker = result.get("ticker", "")
    strategy = result.get("strategy", "")
    disabled = _extract_disabled_regimes(result)
    final_params = _extract_final_params(result)

    insight_parts = [f"[{ticker} {strategy}] Sharpe {sharpe:.2f}"]
    if disabled:
        insight_parts.append(f"除外レジーム: {', '.join(disabled)}")
    if final_params:
        key_params = {k: v for k, v in final_params.items() if "rsi" in k or "trailing" in k}
        if key_params:
            insight_parts.append(f"最適パラメータ: {key_params}")

    insight = " | ".join(insight_parts)

    profiles = config.setdefault("sector_profiles", {})
    prof = profiles.setdefault(sector, {})
    existing = prof.get("judgment_context", "")
    # 重複追記を避ける
    if ticker not in existing:
        prof["judgment_context"] = (existing + "\n" + insight).strip()


def extract_sector_insights(results: dict[str, dict]) -> dict[str, str]:
    """全結果からセクター別共通パターンを文章化する。"""
    sector_map: dict[str, list[str]] = {}

    for ticker, result in results.items():
        fp = result.get("final_performance", {})
        sharpe = fp.get("sharpe_ratio", 0)
        if sharpe <= 0.5:
            continue
        sector = get_sector(ticker)
        disabled = _extract_disabled_regimes(result)
        line = f"{ticker}: Sharpe {sharpe:.2f}"
        if disabled:
            line += f" (除外: {', '.join(disabled)})"
        sector_map.setdefault(sector, []).append(line)

    return {sector: "\n".join(lines) for sector, lines in sector_map.items()}


def update_judgment_prompts(config: dict, results: dict[str, dict]) -> None:
    """
    最適化で判明したセクター特性を sector_profiles[sector].judgment_context に反映。
    """
    insights = extract_sector_insights(results)
    for sector, text in insights.items():
        prof = config.setdefault("sector_profiles", {}).setdefault(sector, {})
        existing = prof.get("judgment_context", "")
        # 新しい知見のみ追記
        new_lines = [l for l in text.splitlines() if l and l not in existing]
        if new_lines:
            prof["judgment_context"] = (existing + "\n" + "\n".join(new_lines)).strip()


def apply_to_config(
    optimization_results: dict[str, dict],
    config_path: Path = CONFIG_PATH,
    dry_run: bool = False,
) -> None:
    """
    最適化結果を config.json に反映する。

    Args:
        optimization_results: load_optimization_results() の戻り値
        config_path:          config.json のパス
        dry_run:              True の場合、差分を表示するだけで書き込まない
    """
    with open(config_path) as f:
        config = json.load(f)

    new_config = copy.deepcopy(config)
    changed_tickers: list[str] = []

    for ticker, result in optimization_results.items():
        strategy = result.get("strategy", "bounce")
        sector = get_sector(ticker, config)

        existing_override = new_config.get("ticker_overrides", {}).get(ticker, {})
        new_override = _build_override_entry(result, existing_override)

        fp = result.get("final_performance", {})
        sharpe = fp.get("sharpe_ratio", 0)

        # ticker_overrides に書き込み
        new_config.setdefault("ticker_overrides", {})[ticker] = new_override
        changed_tickers.append(ticker)

        # セクタープロファイルを更新（Sharpe > 1.0 のみ）
        if sharpe > 1.0 and sector != "unknown":
            update_sector_profile(new_config, sector, result)

    # judgment_context の一括更新
    update_judgment_prompts(new_config, optimization_results)

    if dry_run:
        print("\n" + "=" * 60)
        print("🔍 [DRY RUN] 以下の変更が config.json に適用されます:")
        print("=" * 60)
        for ticker in changed_tickers:
            old = config.get("ticker_overrides", {}).get(ticker, {})
            new = new_config["ticker_overrides"][ticker]
            if old != new:
                print(f"\n  📝 {ticker}:")
                _print_diff(old, new, indent=4)
        # sector_profiles の差分
        for sector in new_config.get("sector_profiles", {}):
            old_ctx = config.get("sector_profiles", {}).get(sector, {}).get("judgment_context", "")
            new_ctx = new_config["sector_profiles"][sector].get("judgment_context", "")
            if old_ctx != new_ctx:
                print(f"\n  📚 sector_profiles[{sector}].judgment_context 更新")
        print("\n  [DRY RUN] config.json は変更されていません")
        return

    with open(config_path, "w") as f:
        json.dump(new_config, f, indent=2, ensure_ascii=False)

    print(f"\n✅ {len(changed_tickers)} 銘柄の最適化結果を config.json に反映: {changed_tickers}")


def _print_diff(old: dict, new: dict, indent: int = 0) -> None:
    """簡易 diff 表示（追加・変更されたキーのみ）。"""
    prefix = " " * indent
    all_keys = set(old.keys()) | set(new.keys())
    for k in sorted(all_keys):
        ov, nv = old.get(k), new.get(k)
        if ov == nv:
            continue
        if isinstance(ov, dict) and isinstance(nv, dict):
            print(f"{prefix}{k}:")
            _print_diff(ov, nv, indent + 2)
        elif ov is None:
            print(f"{prefix}+ {k}: {nv}")
        elif nv is None:
            print(f"{prefix}- {k}: {ov}")
        else:
            print(f"{prefix}~ {k}: {ov!r} → {nv!r}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="最適化結果を config.json に自動反映する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--result-dir",
        default=str(RESULT_DIR_DEFAULT),
        help=f"最適化結果 JSON のディレクトリ (デフォルト: {RESULT_DIR_DEFAULT})",
    )
    parser.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help=f"config.json のパス (デフォルト: {CONFIG_PATH})",
    )
    parser.add_argument(
        "--ticker",
        nargs="*",
        default=None,
        help="反映対象銘柄（省略時は全銘柄）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="差分を表示するだけで config.json を変更しない",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="詳細ログを表示",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(f"📂 結果ディレクトリ: {args.result_dir}")
    print(f"⚙️  config.json: {args.config}")
    if args.ticker:
        print(f"🎯 対象銘柄: {args.ticker}")
    if args.dry_run:
        print("🔍 DRY RUN モード（config.json は変更されません）")
    print("=" * 60 + "\n")

    results = load_optimization_results(
        Path(args.result_dir),
        ticker_filter=args.ticker,
    )

    if not results:
        print("⚠️ 反映対象の最適化結果が見つかりませんでした。")
        return

    print(f"\n📊 {len(results)} 銘柄の最良結果を取得しました\n")

    apply_to_config(
        results,
        config_path=Path(args.config),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
