"""
sec_parser.py - SEC 10-K セクション抽出モジュール
==================================================
SEC EDGAR の 10-K 全文テキストから投資分析に必要なセクション
（Item 1A: Risk Factors, Item 7: MD&A）のみを抽出する。

抽出結果は Groq の TPM 上限 (12,000 tokens ≈ 30,000文字) に収まるよう
合計文字数を制限する。これによりチャンク分割が不要になる。
"""

import re


# 10-K Item 見出しパターン（大文字小文字混在に対応）
_ITEM_PATTERNS = {
    "1a_start": re.compile(
        r"item\s+1a\.?\s*[\-–—:]?\s*risk\s+factors",
        re.IGNORECASE,
    ),
    "1a_end": re.compile(
        r"item\s+1b[\.\s:\-–—]|item\s+2[\.\s:\-–—]|item\s+2\s+properties",
        re.IGNORECASE,
    ),
    "7_start": re.compile(
        r"item\s+7\.?\s*[\-–—:]?\s*management.{0,30}discussion",
        re.IGNORECASE,
    ),
    "7_end": re.compile(
        r"item\s+7a[\.\s:\-–—]|item\s+8[\.\s:\-–—]",
        re.IGNORECASE,
    ),
}

# 目次エントリの最大長（これより短い候補は目次と判断してスキップ）
_MIN_SECTION_LENGTH = 1000

# セクションごとのデフォルト文字数上限
_DEFAULT_MAX_1A = 8_000
_DEFAULT_MAX_7 = 12_000


def extract_sections(
    full_text: str,
    max_total: int = 20_000,
    max_1a: int = _DEFAULT_MAX_1A,
    max_7: int = _DEFAULT_MAX_7,
) -> dict:
    """
    10-K 全文テキストから Item 1A (Risk Factors) と Item 7 (MD&A) を抽出する。

    Parameters
    ----------
    full_text : str
        SEC EDGAR から取得した 10-K のプレーンテキスト。
    max_total : int
        抽出テキストの合計文字数上限（デフォルト 20,000）。
    max_1a : int
        Item 1A の文字数上限（デフォルト 8,000）。
    max_7 : int
        Item 7 の文字数上限（デフォルト 12,000）。

    Returns
    -------
    dict
        {
            "1a": str,            # Item 1A のテキスト（抽出失敗時は空文字）
            "7": str,             # Item 7 のテキスト（抽出失敗時は空文字）
            "combined": str,      # 両セクション結合テキスト
            "total_chars": int,   # combined の文字数
            "extraction_success": bool,  # いずれかのセクション抽出に成功したか
            "sections_found": list[str], # 抽出できたセクション名 ["1a", "7"]
        }
    """
    text_lower = full_text.lower()
    result = {"1a": "", "7": "", "sections_found": []}

    # ── Item 1A 抽出 ────────────────────────────────
    result["1a"] = _extract_between(
        full_text, text_lower,
        _ITEM_PATTERNS["1a_start"],
        _ITEM_PATTERNS["1a_end"],
        max_chars=max_1a,
        fallback_max=30_000,
    )
    if result["1a"]:
        result["sections_found"].append("1a")

    # ── Item 7 抽出 ──────────────────────────────────
    result["7"] = _extract_between(
        full_text, text_lower,
        _ITEM_PATTERNS["7_start"],
        _ITEM_PATTERNS["7_end"],
        max_chars=max_7,
        fallback_max=30_000,
    )
    if result["7"]:
        result["sections_found"].append("7")

    # ── 結合 & 文字数制限 ───────────────────────────
    combined = "\n\n".join(filter(None, [result["1a"], result["7"]]))
    if len(combined) > max_total:
        combined = combined[:max_total]

    result["combined"] = combined
    result["total_chars"] = len(combined)
    result["extraction_success"] = bool(result["1a"] or result["7"])

    return result


def _extract_between(
    full_text: str,
    text_lower: str,
    start_pattern: re.Pattern,
    end_pattern: re.Pattern,
    max_chars: int,
    fallback_max: int = 30_000,
) -> str:
    """
    full_text から start_pattern 〜 end_pattern の間を抽出する。
    end_pattern が見つからない場合は start から fallback_max 文字分を取る。
    """
    # 目次の見出しを避けるため、全マッチから最も長い区間（かつ _MIN_SECTION_LENGTH 以上）を採用
    matches = list(start_pattern.finditer(text_lower))
    if not matches:
        return ""

    best_text = ""
    for m_start in matches:
        start_pos = m_start.start()
        search_region = text_lower[m_start.end():]
        m_end = end_pattern.search(search_region)

        if m_end:
            end_pos = m_start.end() + m_end.start()
        else:
            end_pos = min(start_pos + fallback_max, len(full_text))

        candidate = full_text[start_pos:end_pos].strip()
        # 目次エントリは通常短い（< 1000文字）ので最長マッチを採用
        if len(candidate) > len(best_text) and len(candidate) >= _MIN_SECTION_LENGTH:
            best_text = candidate

    # _MIN_SECTION_LENGTH 以上のマッチがない場合は最長のものを使用
    if not best_text:
        for m_start in matches:
            start_pos = m_start.start()
            search_region = text_lower[m_start.end():]
            m_end = end_pattern.search(search_region)
            if m_end:
                end_pos = m_start.end() + m_end.start()
            else:
                end_pos = min(start_pos + fallback_max, len(full_text))
            candidate = full_text[start_pos:end_pos].strip()
            if len(candidate) > len(best_text):
                best_text = candidate

    return best_text[:max_chars]
