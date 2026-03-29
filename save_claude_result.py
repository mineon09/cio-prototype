#!/usr/bin/env python3
"""
save_claude_result.py - Claude Sonnet の分析結果をダッシュボードに保存
=====================================================
generate_prompt.py で生成したプロンプトを Claude に貼り付けた後、
Claude の回答をこのスクリプトでダッシュボードに取り込みます。

使い方:
    # Claude の回答をコピーしてからクリップボード読み込み（デフォルト）
    ./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard

    # ファイルから読み込み
    ./venv/bin/python3 save_claude_result.py 7203.T --from-file response.txt

    # 標準入力から（パイプ）
    cat response.txt | ./venv/bin/python3 save_claude_result.py 7203.T

    # モデル名を指定
    ./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard --model claude-sonnet-4-5
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"
DATA_DIR    = Path(__file__).parent / "data"


def load_context(ticker: str) -> dict:
    """generate_prompt.py 実行時に保存したコンテキストを読み込む"""
    safe_ticker = ticker.replace('.', '_')
    context_path = PROMPTS_DIR / f"{safe_ticker}_context.json"
    if not context_path.exists():
        print(f"⚠️ コンテキストファイルが見つかりません: {context_path}")
        print(f"   先に以下を実行してください:")
        print(f"   ./venv/bin/python3 generate_prompt.py {ticker} --copy")
        return {}
    with open(context_path, encoding='utf-8') as f:
        return json.load(f)


def read_response(args) -> str:
    """Claude の回答テキストを取得"""
    if args.from_file:
        with open(args.from_file, encoding='utf-8') as f:
            return f.read()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    # デフォルト: クリップボード
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            print("⚠️ クリップボードが空です")
            sys.exit(1)
        return text
    except ImportError:
        print("⚠️ pyperclip が必要です: pip install pyperclip")
        sys.exit(1)


VALID_SIGNALS = {"BUY", "WATCH", "SELL"}


def extract_json_from_response(text: str) -> dict:
    """Claude の回答テキストから JSON ブロックを抽出。

    入力プロンプト内にサンプル JSON が含まれる場合でも、
    Claude の出力 JSON（signal + score + entry_price を持つ最後のブロック）
    を確実に採用する。
    """
    # ─────────────────────────────────────────────────────────
    # 優先1: ```json ... ``` フェンスブロックを全て収集し、
    #        signal + score + entry_price を持つ最後のものを採用
    #        （入力プロンプトのサンプルより後に Claude の出力が来るため）
    # ─────────────────────────────────────────────────────────
    fenced_candidates = []
    for m in re.finditer(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "signal" in obj:
                fenced_candidates.append(obj)
        except Exception:
            continue

    if fenced_candidates:
        # signal + score + entry_price を全て持つものを優先、なければ signal だけでも OK
        full = [o for o in fenced_candidates
                if "score" in o and "entry_price" in o]
        return full[-1] if full else fenced_candidates[-1]

    # 優先2: ``` ... ``` (言語指定なし)
    fenced_plain = []
    for m in re.finditer(r'```\s*(\{.*?\})\s*```', text, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "signal" in obj:
                fenced_plain.append(obj)
        except Exception:
            continue

    if fenced_plain:
        full = [o for o in fenced_plain if "score" in o and "entry_price" in o]
        return full[-1] if full else fenced_plain[-1]

    # 優先3: raw_decode で { から始まる最初の有効 JSON を探す
    #        （フェンスなし・signal キーを含むもの限定）
    decoder = json.JSONDecoder()
    raw_candidates = []
    pos = 0
    while True:
        start = text.find('{', pos)
        if start == -1:
            break
        try:
            obj, end_pos = decoder.raw_decode(text[start:])
            if isinstance(obj, dict) and "signal" in obj:
                raw_candidates.append(obj)
            pos = start + max(end_pos, 1)
        except Exception:
            pos = start + 1

    if raw_candidates:
        full = [o for o in raw_candidates if "score" in o and "entry_price" in o]
        return full[-1] if full else raw_candidates[-1]

    # 優先4: "signal" キーを含む { ... } ブロックを正規表現で探す
    re_candidates = list(re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL))
    signal_objs = []
    for c in re_candidates:
        if '"signal"' in c.group():
            try:
                obj = json.loads(c.group())
                signal_objs.append(obj)
            except Exception:
                continue

    if signal_objs:
        full = [o for o in signal_objs if "score" in o and "entry_price" in o]
        return full[-1] if full else signal_objs[-1]

    return {}


def normalize_signal(data: dict) -> dict:
    """非標準シグナル (HOLD 等) を正規化する。"""
    signal = (data.get("signal") or "WATCH").upper()
    if signal == "HOLD":
        print(f"  ⚠️  signal='HOLD' を 'WATCH' に正規化しました")
        signal = "WATCH"
    if signal not in VALID_SIGNALS:
        print(f"  ⚠️  不正なsignal '{signal}' → 'WATCH' にフォールバック")
        signal = "WATCH"
    data["signal"] = signal
    return data


def save_to_dashboard(ticker: str, context: dict, report: str,
                      claude_json: dict, model_name: str):
    """ダッシュボード用 results.json に保存"""
    scorecard = context.get('scorecard', {})

    # signal: Claude の判断を優先、なければスコアカードの signal
    if claude_json and isinstance(claude_json, dict):
        claude_json = normalize_signal(claude_json)
    else:
        claude_json = {}
    signal_raw = claude_json.get('signal', scorecard.get('signal', 'WATCH'))
    signal = (signal_raw or 'WATCH').upper()
    if signal not in VALID_SIGNALS:
        signal = 'WATCH'

    position_size = float(claude_json.get('position_size', 0.10))

    # total_score: Claude の score を優先し、なければローカルスコアカードの値を使用
    # ローカルスコアカードは加重平均で算出（例: 5.7）、Claude の判断スコア（例: 7.0）と
    # 異なる場合は Claude 側が最終判断として正しいため上書きする
    claude_score = claude_json.get("score")
    total_score = float(claude_score) if claude_score is not None else scorecard.get("total_score", 0)

    new_entry = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scores": {
            "fundamental": scorecard.get("fundamental", {}).get("score", 0),
            "valuation":   scorecard.get("valuation",   {}).get("score", 0),
            "technical":   scorecard.get("technical",   {}).get("score", 0),
            "qualitative": scorecard.get("qualitative", {}).get("score", 0),
        },
        "weights":      scorecard.get("weights", context.get("regime_weights", {})),
        "signal":       signal,
        "holding":      signal == "BUY",
        "position_size": position_size,
        "total_score":  total_score,
        "algo_score":   scorecard.get("total_score", 0),  # ローカルアルゴスコアを参照用に保存
        "metrics":      context.get("metrics", {}),
        "technical_data": context.get("technical", {}),
        "report":       report,
        "ai_model":     model_name,
    }

    # Claude 固有フィールド（あれば追加）—— 旧形式・新形式の両方に対応
    for field in ("entry_price", "stop_loss", "take_profit",
                  "confidence", "holding_period", "risks", "catalysts",
                  "reasoning", "exit_strategy", "watch_points", "peer_comparison",
                  "macro_sensitivity", "risk_quantification",
                  # 旧形式（build_enhanced_prompt_with_data）のフィールド
                  "industry_outlook", "competitive_position", "time_horizon",
                  "key_catalysts", "key_risks", "scenario_analysis", "esg_factors"):
        if field in claude_json:
            new_entry[field] = claude_json[field]

    # マクロ情報
    regime = context.get("regime")
    if regime:
        new_entry["macro"] = {"regime": regime, "detail": ""}

    DATA_DIR.mkdir(exist_ok=True)
    file_path = DATA_DIR / "results.json"

    try:
        from filelock import FileLock
        lock = FileLock(str(file_path) + ".lock", timeout=10)
    except ImportError:
        from contextlib import nullcontext
        lock = nullcontext()

    try:
        with lock:
            all_results = {}
            if file_path.exists():
                try:
                    all_results = json.loads(file_path.read_text(encoding='utf-8'))
                except Exception:
                    all_results = {}

            if ticker in all_results:
                existing = all_results[ticker]
                # 旧フォーマット（history キーなし）→ マイグレーション
                if "history" not in existing:
                    old = {k: existing[k] for k in
                           ("date", "scores", "weights", "signal",
                            "total_score", "metrics", "technical_data", "report")
                           if k in existing}
                    existing = {
                        "name": existing.get("name", ticker),
                        "sector": existing.get("sector", "不明"),
                        "currency": existing.get("currency", "JPY"),
                        "history": [old],
                    }
                existing["history"].append(new_entry)
                existing["history"] = existing["history"][-20:]
                existing["name"]     = context.get("name", ticker)
                existing["sector"]   = context.get("sector", "不明")
                existing["currency"] = context.get("currency", "JPY" if ticker.endswith('.T') else "USD")
                all_results[ticker] = existing
            else:
                all_results[ticker] = {
                    "name":     context.get("name", ticker),
                    "sector":   context.get("sector", "不明"),
                    "currency": context.get("currency", "JPY" if ticker.endswith('.T') else "USD"),
                    "history":  [new_entry],
                }

            tmp = tempfile.NamedTemporaryFile(
                "w", encoding='utf-8', delete=False,
                dir=str(DATA_DIR), suffix=".tmp"
            )
            json.dump(all_results, tmp, indent=2, ensure_ascii=False)
            tmp.close()

            if file_path.exists():
                os.remove(str(file_path))
            os.rename(tmp.name, str(file_path))

        count = len(all_results[ticker]["history"])
        print(f"✅ ダッシュボード保存完了：{ticker} (履歴 {count} 件)")
        print(f"   シグナル  : {signal}")
        print(f"   総合スコア: {total_score:.1f} (アルゴ: {scorecard.get('total_score', 'N/A')})")
        if "entry_price" in new_entry:
            print(f"   エントリー: {new_entry['entry_price']}  "
                  f"損切: {new_entry.get('stop_loss', '-')}  "
                  f"利確: {new_entry.get('take_profit', '-')}")
        print(f"   保存先    : {file_path}")

    except Exception as e:
        print(f"❌ 保存失敗: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description='Claude Sonnet の分析結果をダッシュボードに保存',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  # クリップボードから（Claude の回答をコピー後）
  ./venv/bin/python3 save_claude_result.py 7203.T --from-clipboard

  # ファイルから
  ./venv/bin/python3 save_claude_result.py AAPL --from-file response.txt

  # パイプ
  cat response.txt | ./venv/bin/python3 save_claude_result.py 7203.T
        """
    )
    parser.add_argument('ticker', help='銘柄コード（例：7203.T, AAPL）')
    parser.add_argument('--from-clipboard', action='store_true',
                        help='クリップボードから回答を読み込む（デフォルト）')
    parser.add_argument('--from-file', metavar='PATH',
                        help='ファイルから回答を読み込む')
    parser.add_argument('--model', default='claude-sonnet',
                        help='使用した AI モデル名（デフォルト: claude-sonnet）')
    args = parser.parse_args()

    print(f"📥 Claude 回答を取得中...")
    response_text = read_response(args)
    print(f"   {len(response_text):,} 文字取得")

    print(f"📋 コンテキスト読み込み: {args.ticker}")
    context = load_context(args.ticker)
    if not context:
        print("   ⚠️ コンテキストなしで続行（スコア等が空になります）")

    print(f"🔍 JSON 抽出中...")
    claude_json = extract_json_from_response(response_text)
    if claude_json:
        print(f"   ✅ JSON 抽出成功")
        print(f"   signal={claude_json.get('signal', 'N/A')}, "
              f"score={claude_json.get('score', 'N/A')}, "
              f"confidence={claude_json.get('confidence', 'N/A')}")
    else:
        print(f"   JSON が見つかりませんでした（シグナルはスコアカードから取得）")

    print(f"💾 ダッシュボードに保存中...")
    save_to_dashboard(args.ticker, context, response_text, claude_json, args.model)

    # Notion にも保存（NOTION_API_KEY が設定されていれば）
    try:
        from src.notion_writer import write_to_notion
        target_data = {
            "name":     context.get("name", args.ticker),
            "currency": context.get("currency", "JPY" if args.ticker.endswith('.T') else "USD"),
            "technical": context.get("technical", {}),
        }
        scorecard = context.get("scorecard", {}).copy()
        # Claude の判断を優先してシグナル・スコアを上書き
        if claude_json:
            if "signal" in claude_json:
                scorecard["signal"] = claude_json["signal"]
            if "score" in claude_json:
                scorecard["total_score"] = claude_json["score"]
        print(f"📤 Notion に保存中...")
        ok = write_to_notion(args.ticker, target_data, response_text, scorecard)
        if not ok:
            print(f"⚠️ Notion 保存スキップ: NOTION_API_KEY または NOTION_DATABASE_ID が未設定です")
    except Exception as e:
        print(f"⚠️ Notion 保存スキップ: {e}")


if __name__ == '__main__':
    main()
