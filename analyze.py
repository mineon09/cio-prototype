#!/usr/bin/env python3
"""
analyze.py - GitHub Models API を使った一気通貫投資分析ツール
=============================================================
銘柄コードを指定するだけで、以下を自動実行する:
  1. データ収集（yfinance + SEC 10-K / EDINET 有報）
  2. 高品質プロンプト生成（generate_prompt.py のロジックを再利用）
  3. GitHub Models API (gpt-4o など) で投資分析
  4. data/reports/YYYYMM/TICKER_date.md にレポート保存

使い方:
    ./venv/bin/python3 analyze.py AMAT
    ./venv/bin/python3 analyze.py 7203.T --model gpt-4o-mini
    ./venv/bin/python3 analyze.py XOM --no-cache
    ./venv/bin/python3 analyze.py NVDA -o my_report.md

利用可能モデル（--model）:
    gpt-4o       : 高品質・推奨（デフォルト）
    gpt-4o-mini  : 高速・低コスト
    llama405b    : Meta-Llama-3.1-405B-Instruct
    llama70b     : Meta-Llama-3.1-70B-Instruct
    mistral      : Mistral-large-2407

前提条件:
    gh auth login 済み（GitHub Copilot サブスクリプション不要）
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────
# JSON シグナル抽出
# ──────────────────────────────────────────

def extract_json_signal(text: str) -> dict:
    """LLM レスポンスから ```json ... ``` ブロックを抽出・パースする"""
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # フォールバック: { ... } を直接探す
    m2 = re.search(r'\{\s*"signal"\s*:.*?\}', text, re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def print_signal_summary(signal_data: dict, ticker: str) -> None:
    """投資判断サマリーをコンソール表示する"""
    if not signal_data:
        return
    signal = signal_data.get("signal", "---")
    score  = signal_data.get("score", 0)
    entry  = signal_data.get("entry_price", "-")
    sl     = signal_data.get("stop_loss", "-")
    tp     = signal_data.get("take_profit", "-")
    emoji  = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡", "HOLD": "🟡"}.get(signal, "⚪")

    print(f"\n{'='*55}")
    print(f"  {emoji}  {ticker}  シグナル: {signal}   スコア: {score}/10")
    print(f"  エントリー: {entry}  |  損切り: {sl}  |  利確: {tp}")
    reasoning = signal_data.get("reasoning", "")
    if reasoning:
        print(f"  理由: {reasoning[:120]}")
    risks = signal_data.get("risks", [])
    if risks:
        print(f"  リスク: {', '.join(risks[:2])}")
    catalysts = signal_data.get("catalysts", [])
    if catalysts:
        print(f"  カタリスト: {', '.join(catalysts[:2])}")
    print(f"{'='*55}\n")


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="GitHub Models API を使った自動投資分析ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python analyze.py AMAT
  python analyze.py 7203.T --model gpt-4o-mini
  python analyze.py XOM --no-cache -o xom_report.md
""",
    )
    parser.add_argument("ticker", help="銘柄コード（例: AMAT, 7203.T, XOM）")
    parser.add_argument(
        "--model",
        default="gpt-4o",
        choices=["gpt-4o", "gpt-4o-mini", "llama405b", "llama70b", "mistral"],
        help="使用モデル（デフォルト: gpt-4o）",
    )
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを使用しない（最新データ取得）")
    parser.add_argument("-o", "--output", help="レポートの追加コピー先ファイルパス")
    parser.add_argument("--list-models", action="store_true", help="利用可能なモデル一覧を表示して終了")
    args = parser.parse_args()

    # モデル一覧表示
    if args.list_models:
        from src.copilot_client import list_available_models, SUPPORTED_MODELS
        print("【サポートモデル略称 → 正式名称】")
        for alias, name in SUPPORTED_MODELS.items():
            print(f"  {alias:<15} → {name}")
        print("\n【GitHub Models API 利用可能モデル（chat-completion）】")
        for m in list_available_models():
            print(f"  {m}")
        return 0

    ticker = args.ticker.upper()
    print(f"\n🚀  {ticker} の自動分析を開始")
    print(f"    モデル  : {args.model} (GitHub Models API)")
    print(f"    日時    : {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # ── Step 1: データ収集 & プロンプト生成 ──────────────────
    print(f"\n📊  Step 1/3  データ収集中（キャッシュ優先）...")
    from generate_prompt import (
        collect_data_minimal,
        build_high_quality_prompt,
        build_simple_prompt,
    )

    data, api_calls, yuho_summary = collect_data_minimal(
        ticker, use_cache=not args.no_cache
    )

    if data is None:
        print(f"  ⚠️  データ取得失敗 → 簡易プロンプトで続行")
        prompt = build_simple_prompt(ticker)
    else:
        prompt = build_high_quality_prompt(
            ticker=ticker,
            company_name=data.get("name", ticker),
            sector=data.get("sector", "Unknown"),
            as_of_date=datetime.now().strftime("%Y-%m-%d"),
            regime=data.get("regime", "NEUTRAL"),
            regime_weights=data.get("regime_weights", {}),
            scorecard=data.get("scorecard", {}),
            financial_metrics=data.get("metrics", {}),
            technical_data=data.get("technical", {}),
            yuho_summary=yuho_summary,
        )
    print(f"  ✅  プロンプト生成完了 ({len(prompt):,} 文字, API 呼び出し: {api_calls}回)")

    # ── Step 2: AI 分析 ──────────────────────────────────────
    print(f"\n🤖  Step 2/3  {args.model} で分析中...")
    from src.copilot_client import call_github_models

    try:
        report, model_used = call_github_models(prompt, model=args.model)
        print(f"  ✅  分析完了 ({model_used})")
    except RuntimeError as e:
        print(f"  ❌  GitHub Models API 失敗: {e}")
        sys.exit(1)

    # JSON シグナル抽出・表示
    signal_data = extract_json_signal(report)
    if signal_data:
        print_signal_summary(signal_data, ticker)
    else:
        print("  ⚠️  JSON シグナルが抽出できませんでした（テキスト全文は保存されます）")

    # ── Step 3: レポート保存 ─────────────────────────────────
    print(f"📝  Step 3/3  レポート保存中...")
    from src.md_writer import write_to_md

    scorecard = data.get("scorecard", {}) if data else {}
    target_data = data if data else {"name": ticker}

    output_path = write_to_md(ticker, target_data, report, scorecard=scorecard)

    if args.output and output_path:
        shutil.copy(output_path, args.output)
        print(f"  📁  追加コピー: {args.output}")

    print(f"\n✅  完了: {output_path or '(保存失敗)'}")
    print(f"\n💡  ヒント:")
    print(f"    --model gpt-4o-mini  : 高速・低コストモード")
    print(f"    --no-cache           : 最新データで再取得")
    print(f"    --list-models        : 利用可能モデル一覧")
    return 0


if __name__ == "__main__":
    sys.exit(main())
