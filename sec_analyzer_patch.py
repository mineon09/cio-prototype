"""
sec_analyzer_patch.py - Groq チャンク分割解析ロジック（TPM 制限対応）
======================================================================
Groq の無料枠 TPM 制限（12,000 tokens ≈ 9,000文字）を超える 10-K テキストを
8,000文字チャンクに分割して順次解析し、結果をマージする。

チャンク間は CHUNK_WAIT_SECS 秒待機して TPM レートをリセットする。
"""

import re
import time

try:
    from src.data_fetcher import call_groq
except ImportError:
    def call_groq(prompt, parse_json=False):  # type: ignore[misc]
        print("⚠️ call_groq 未利用可能")
        return None, None


CHUNK_SIZE = 8_000
CHUNK_WAIT_SECS = 65  # Groq TPM リセット待機秒数

_CHUNK_PROMPT_TEMPLATE = """\
You are a financial analyst. Extract key qualitative information from this PARTIAL section \
of a SEC 10-K filing for {ticker}.

Return ONLY a JSON object with these fields (use null or empty list if not found in this section):
{{
  "risk_top3": ["risk1", "risk2", "risk3"],
  "moat": {{"type": "brand|network|cost|switching|regulatory", "description": "...", "durability": "high|medium|low"}},
  "management_tone": {{"overall": "bullish|neutral|cautious", "confidence_signals": ["..."], "risk_acknowledgment": "..."}},
  "rd_focus": ["focus1", "focus2"],
  "management_challenges": "brief summary in Japanese",
  "summary": "brief overall summary in Japanese (100 chars max)"
}}

Filing text (partial):
{text}"""


def _build_chunk_prompt(text: str, ticker: str) -> str:
    return _CHUNK_PROMPT_TEMPLATE.format(ticker=ticker, text=text)


def _merge_results(results: list) -> dict:
    """複数チャンクの解析結果をマージする。"""
    merged: dict = {
        "risk_top3": [],
        "moat": {},
        "management_tone": {},
        "rd_focus": [],
        "management_challenges": "",
        "summary": "",
    }

    for r in results:
        if not isinstance(r, dict):
            continue

        # リスト: 結合して重複除去
        for key in ("risk_top3", "rd_focus"):
            items = r.get(key) or []
            if isinstance(items, list):
                merged[key].extend(x for x in items if x and x not in merged[key])

        # 最初の有効値を採用
        for key in ("moat", "management_tone"):
            if not merged[key] and r.get(key):
                merged[key] = r[key]

        # 文字列: 最初の有効値を採用
        for key in ("management_challenges", "summary"):
            if not merged[key] and r.get(key):
                merged[key] = r[key]

    # リスト長を絞り込む
    merged["risk_top3"] = merged["risk_top3"][:3]
    merged["rd_focus"] = merged["rd_focus"][:5]

    return merged


def analyze_10k_with_groq_chunked(
    text: str,
    ticker: str,
    verbose: bool = False,
) -> tuple:
    """
    10-K テキストを Groq で分割解析する（TPM 制限対応）。

    テキストを CHUNK_SIZE 文字ずつ分割し、各チャンクを Groq で解析して
    結果をマージする。チャンク間は CHUNK_WAIT_SECS 秒待機する。

    Returns
    -------
    (analysis_dict, meta)
      meta: {"chunk_count": int, "total_chars": int, "truncated": bool}
    """
    clean = re.sub(r"\s+", " ", text).strip()
    total_chars = len(clean)

    chunks = [clean[i : i + CHUNK_SIZE] for i in range(0, total_chars, CHUNK_SIZE)]
    chunk_count = len(chunks)

    if verbose:
        print(f"  🔀 Groq チャンク解析開始: {total_chars:,}文字 → {chunk_count}チャンク")

    results = []
    for idx, chunk in enumerate(chunks):
        if verbose:
            print(f"  📤 チャンク {idx + 1}/{chunk_count} 送信中 ({len(chunk):,}文字)...")

        prompt = _build_chunk_prompt(chunk, ticker)
        response, _ = call_groq(prompt, parse_json=True)

        if isinstance(response, dict) and response:
            results.append(response)

        if idx < chunk_count - 1:
            if verbose:
                print(f"  ⏳ TPM リセット待機: {CHUNK_WAIT_SECS}秒...")
            time.sleep(CHUNK_WAIT_SECS)

    merged = _merge_results(results)
    meta = {
        "chunk_count": chunk_count,
        "total_chars": total_chars,
        "truncated": chunk_count > 1,
    }

    if verbose:
        print(f"  ✅ チャンク解析完了: {len(results)}/{chunk_count}チャンク成功")

    return merged, meta


def inject_warning_into_prompt(prompt: str, meta: dict | None) -> str:
    """
    チャンク分割解析が発生した場合、プロンプト冒頭に警告文を挿入する。
    meta が None または chunk_count <= 1 の場合は何もしない。
    """
    if not meta or meta.get("chunk_count", 1) <= 1:
        return prompt

    n = meta["chunk_count"]
    total = meta.get("total_chars", 0)
    warning = (
        f"⚠️ [注意] Groq TPM 制限のため 10-K テキスト（{total:,}文字）を"
        f"{n}チャンクに分割して解析しました。"
        f"情報の一部が欠損している可能性があります。\n\n"
    )
    return warning + prompt
