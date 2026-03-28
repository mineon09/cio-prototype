#!/usr/bin/env python3
"""
generate_prompt.py - 投資判断用プロンプト生成ツール（強化版）
=====================================================
銘柄コードを指定するだけで、LLM 用の投資判断プロンプトを生成します。

定性情報（ニュース、アナリスト評価、業界動向）を自動取得して
プロンプトに埋め込むことで、より精度の高い分析が可能になります。

使い方:
    ./venv/bin/python3 generate_prompt.py 7203.T
    ./venv/bin/python3 generate_prompt.py AAPL -o custom_prompt.txt
    ./venv/bin/python3 generate_prompt.py 7203.T --copy  # クリップボードにコピー
    ./venv/bin/python3 generate_prompt.py AMAT --enhanced  # 定性情報あり（デフォルト）
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# デフォルト出力ディレクトリ
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "prompts"
DEFAULT_OUTPUT_DIR.mkdir(exist_ok=True)

# SEC EDGAR（利用可能な場合のみ）
try:
    from src.sec_client import extract_sec_data, is_us_stock
    HAS_SEC = True
except ImportError:
    HAS_SEC = False
    def is_us_stock(ticker): return not str(ticker).endswith('.T')
    def extract_sec_data(ticker): return {}


def fmt_pct(v, d: int = 2, zero_as_na: bool = False) -> str:
    """float を "X.XX%" 形式の文字列に変換（None / N/A / 変換不可 は '-'）。"""
    if v is None or v == 'N/A':
        return "-"
    try:
        fv = float(v)
        if zero_as_na and fv == 0.0:
            return "-"
        return f"{round(fv, d)}%"
    except (TypeError, ValueError):
        return "-"


def fmt_num(v, d: int = 2, zero_as_na: bool = False):
    """float を丸めた値を返す（None / N/A は '-'）。"""
    if v is None or v == 'N/A':
        return "-"
    try:
        fv = round(float(v), d)
        if zero_as_na and fv == 0.0:
            return "-"
        return fv
    except (TypeError, ValueError):
        return "-"


def format_scorecard_text(scorecard: dict) -> str:
    """スコアカードをテキスト形式に整形"""
    fund = scorecard.get("fundamental", {})
    val = scorecard.get("valuation", {})
    tech = scorecard.get("technical", {})
    qual = scorecard.get("qualitative", {})

    lines = [
        f"  Fundamental  (地力)  : {fund.get('score', 'N/A'):>4} / 10",
        f"  Valuation  (割安度)  : {val.get('score', 'N/A'):>4} / 10",
        f"  Technical  (タイミング): {tech.get('score', 'N/A'):>4} / 10",
        f"  Qualitative (定性)   : {qual.get('score', 'N/A'):>4} / 10",
        f"  ─────────────────────────────",
        f"  総合スコア            : {scorecard.get('total_score', 'N/A'):>4} / 10",
        f"  シグナル              : 【{scorecard.get('signal', '---')}】",
    ]

    # サブ指標があれば補足
    for axis_name, axis_dict in [("Fundamental", fund), ("Valuation", val),
                                  ("Technical", tech), ("Qualitative", qual)]:
        details = axis_dict.get("details", [])
        if details:
            lines.append(f"\n  [{axis_name} 詳細]")
            if isinstance(details, list):
                for v in details:
                    lines.append(f"    {v}")
            elif isinstance(details, dict):
                for k, v in details.items():
                    lines.append(f"    {k}: {v}")

    return "\n".join(lines)


def _extract_yuho_sections(raw_text: str, max_chars: int = 15000) -> str:
    """
    有報生テキストから投資判断に有用なセクションのみを抽出する。

    優先セクション（この順で最大 max_chars 文字）:
    1. 経営方針、経営環境及び対処すべき課題等
    2. 事業等のリスク
    3. 経営者による財政状態、経営成績及びキャッシュ・フローの状況の分析
    """
    import re as _re

    target_keywords = [
        "経営方針、経営環境及び対処すべき課題等",
        "事業等のリスク",
        "経営者による財政状態",
    ]

    # 次のセクション境界を示す見出しパターン
    boundary_re = _re.compile(
        r"(?m)^(?:第[１２３４５一二三四五]\s|"
        r"経営方針|事業等のリスク|経営者による財政|"
        r"設備の状況|提出会社の状況|経理の状況|"
        r"株式の状況|配当政策|コーポレート・ガバナンス|監査報告|"
        r"関係会社の状況|従業員の状況|沿革)"
    )

    extracted_parts: list = []
    total_chars = 0

    for keyword in target_keywords:
        if total_chars >= max_chars:
            break

        idx = raw_text.find(keyword)
        if idx == -1:
            continue

        # セクション開始（キーワード行の先頭）
        line_start = raw_text.rfind('\n', 0, idx)
        start = line_start + 1 if line_start != -1 else idx

        # 次のセクション境界を探す（キーワード後50文字以降）
        search_from = idx + len(keyword) + 50
        end = len(raw_text)
        for m in boundary_re.finditer(raw_text, search_from):
            if m.start() > search_from:
                end = m.start()
                break

        section_text = raw_text[start:end].strip()
        if not section_text:
            continue

        remaining = max_chars - total_chars
        part = section_text[:remaining]
        extracted_parts.append(f"【{keyword}】\n{part}")
        total_chars += len(part)

    if not extracted_parts:
        # フォールバック: 表紙・沿革を飛ばして「事業の状況」以降を返す
        best_start = 0
        for marker in ["経営方針", "事業等のリスク", "事業の状況"]:
            idx = raw_text.find(marker)
            if idx > 0:
                best_start = max(0, idx - 100)
                break
        return raw_text[best_start: best_start + max_chars]

    return "\n\n".join(extracted_parts)


def _sector_context(sector: str) -> str:
    """セクター別の評価注意事項を返す（LLMへのコンテキスト補足）"""
    s = (sector or "").lower()
    if any(k in s for k in ["financial", "bank", "insurance"]):
        return (
            "【金融セクター評価注意】\n"
            "  - 自己資本比率 4〜6% は銀行の Basel III Tier1 基準内で正常（一般事業会社と異なる）\n"
            "  - 営業 CF/純利益 は金融業では意味が薄い（貸出・運用キャッシュフローが主）\n"
            "  - NIM（純利ざや）・信用コスト比率・CET1 比率が本質的指標\n"
            "  - 金利上昇局面は NIM 拡大でプラス、信用コスト増加リスクとのバランスを評価せよ\n"
            "  - PBR 1.0 倍前後が銀行の妥当圏（ROE と資本コストの関係で判断）"
        )
    if any(k in s for k in ["technology", "software", "semiconductor"]):
        return (
            "【テクノロジーセクター評価注意】\n"
            "  - R&D 比率 10〜20% が典型的な成長投資水準\n"
            "  - PER 30〜50 倍でも成長率次第で割高とは言えない（PEG 比率で補完せよ）\n"
            "  - フリーキャッシュフローマージンが利益の質を示す最重要指標\n"
            "  - 受注残・ARR・NRR などの SaaS 指標があれば優先評価せよ"
        )
    if any(k in s for k in ["energy", "oil", "gas"]):
        return (
            "【エネルギーセクター評価注意】\n"
            "  - 原油・天然ガス価格サイクルに業績が強く連動する\n"
            "  - 設備投資（CAPEX）サイクルと FCF 利回りが重要\n"
            "  - 環境規制・エネルギー転換リスクを中長期シナリオに必ず織り込め"
        )
    if any(k in s for k in ["consumer", "retail", "auto"]):
        return (
            "【消費財・自動車セクター評価注意】\n"
            "  - 景気後退時の需要弾力性（必需品 vs 耐久財）を区別せよ\n"
            "  - 在庫サイクル・供給網（半導体・原材料）の状況を確認\n"
            "  - EV 移行・脱炭素コストは長期ダウンサイドシナリオに含めよ"
        )
    return ""


def _regime_context(regime: str, sector: str) -> str:
    """市場レジーム別の分析フォーカスを返す"""
    s = (sector or "").lower()
    is_financial = any(k in s for k in ["financial", "bank", "insurance"])

    if regime == "RISK_OFF":
        base = (
            "【RISK_OFF レジーム — 分析フォーカス】\n"
            "  ✓ バランスシート強度（自己資本比率・純負債/EBITDA）を最優先評価\n"
            "  ✓ 配当維持能力・自社株買い余力の確認\n"
            "  ✓ ディフェンシブな収益源（サブスクリプション・必需品需要）があるか\n"
            "  ✗ 高 PER 成長株・高レバレッジ銘柄は割引率上昇でバリュエーション毀損リスク\n"
            "  ✗ 景気敏感セクターは業績下方修正リスクに注意"
        )
        if is_financial:
            base += (
                "\n  ★ 金融株特記: 信用スプレッド拡大→貸倒引当金増加リスク、"
                "一方で長期金利高止まりなら NIM はプラス。両面を定量評価せよ"
            )
        return base
    if regime == "RISK_ON":
        return (
            "【RISK_ON レジーム — 分析フォーカス】\n"
            "  ✓ 成長率・モメンタム・アップサイドカタリストを重視\n"
            "  ✓ テクニカルトレンド（MA アライメント・出来高確認）が追い風になりやすい\n"
            "  ✓ 市場 Beta の高い銘柄は超過リターンが期待できる\n"
            "  ✗ 過熱シグナル（RSI>70, BB上抜け）には利確タイミングに注意"
        )
    if regime in ("RATE_HIKE", "YIELD_INVERSION"):
        base = (
            f"【{regime} レジーム — 分析フォーカス】\n"
            "  ✓ 高金利環境で恩恵を受けるセクター（金融・エネルギー）を優位に評価\n"
            "  ✓ 短期債務比率・借り換えリスクを確認\n"
            "  ✗ 高バリュエーション・長デュレーション資産の割引率感応度に注意\n"
            "  ✗ 逆イールドが続く場合は景気後退先行指標として織り込め"
        )
        if is_financial:
            base += "\n  ★ 金融株特記: NIM 拡大がプラス。ただし信用コスト増加と相殺される可能性に注意"
        return base
    if regime == "RATE_CUT":
        return (
            "【RATE_CUT レジーム — 分析フォーカス】\n"
            "  ✓ 利下げ恩恵銘柄（不動産・公益・成長株）の再評価余地\n"
            "  ✓ 長期デュレーション資産のバリュエーション改善\n"
            "  ✗ 金融株は NIM 縮小懸念。収益の質（手数料収入比率）を確認せよ"
        )
    # NEUTRAL
    return (
        "【NEUTRAL レジーム — 分析フォーカス】\n"
        "  ✓ ファンダメンタルズ重視のボトムアップ分析が有効\n"
        "  ✓ 個別カタリスト（決算・新製品・M&A）が株価を動かす主因\n"
        "  ✓ セクターローテーション動向を確認し、資金流入方向と整合性を取れ"
    )


def _peer_set(sector: str, ticker: str) -> str:
    """セクター別の代表ピア銘柄セットを返す"""
    s = (sector or "").lower()
    is_jp = ticker.upper().endswith('.T')
    if any(k in s for k in ["financial", "bank", "insurance"]):
        return "8316.T（三井住友FG）, 8411.T（みずほFG）, 8309.T（三菱UFJ信託）" if is_jp else "JPM, BAC, WFC"
    if any(k in s for k in ["technology", "software", "semiconductor"]):
        return "6861.T（キーエンス）, 8035.T（東京エレク）, 6857.T（アドバンテスト）" if is_jp else "MSFT, AAPL, NVDA"
    if any(k in s for k in ["energy", "oil", "gas"]):
        return "5019.T（出光興産）, 5020.T（ENEOS）, 1605.T（INPEX）" if is_jp else "XOM, CVX, COP"
    if any(k in s for k in ["consumer", "retail", "auto"]):
        return "7203.T（トヨタ）, 7267.T（ホンダ）, 7201.T（日産）" if is_jp else "GM, F, TSLA"
    if any(k in s for k in ["health", "pharma", "medical", "biotech"]):
        return "4502.T（武田薬品）, 4568.T（第一三共）, 4519.T（中外製薬）" if is_jp else "JNJ, UNH, PFE"
    return "（公開情報からセクター同業3〜5社を特定せよ）"


def build_high_quality_prompt(
    ticker: str,
    company_name: str,
    sector: str,
    as_of_date: str,
    regime: str,
    regime_weights: dict,
    scorecard: dict,
    financial_metrics: dict,
    technical_data: dict,
    yuho_summary: str = None,
) -> str:
    """
    高品質な投資分析プロンプトを生成。
    セクター別注意事項・レジーム別フォーカス・MA75 乖離を追加し、
    JSON 出力のスキーマ制約と出口戦略・監視ポイントを強化。
    """
    # ウェイト取得
    w_fund = regime_weights.get("fundamental", 0.30)
    w_val  = regime_weights.get("valuation", 0.25)
    w_tech = regime_weights.get("technical", 0.25)
    w_qual = regime_weights.get("qualitative", 0.20)

    scorecard_text = format_scorecard_text(scorecard)

    metrics = financial_metrics
    fundamentals_detail = f"""
  ROE            : {fmt_pct(metrics.get('roe'), zero_as_na=True)}
  PER            : {fmt_num(metrics.get('per'), zero_as_na=True)}倍
  PBR            : {fmt_num(metrics.get('pbr'), zero_as_na=True)}倍
  営業利益率     : {fmt_pct(metrics.get('op_margin'))}
  自己資本比率   : {fmt_pct(metrics.get('equity_ratio'))}
  配当利回り     : {fmt_pct(metrics.get('dividend_yield'))}
  営業 CF/純利益 : {fmt_num(metrics.get('cf_quality'))}
  R&D 比率       : {fmt_pct(metrics.get('rd_ratio'))}
"""

    ma75_dev = technical_data.get('ma75_deviation')
    ma75_str = fmt_pct(ma75_dev) if ma75_dev is not None and ma75_dev != 'N/A' else 'N/A'

    # 流動性データ（ポジションサイズ判断に使用）
    mkt_cap_raw = technical_data.get('market_cap')
    avg_vol_raw = technical_data.get('avg_daily_volume')
    mkt_cap_str = f"{mkt_cap_raw / 1e8:.0f}億円" if isinstance(mkt_cap_raw, (int, float)) else str(mkt_cap_raw or 'N/A')
    avg_vol_str = f"{avg_vol_raw:,.0f}株" if isinstance(avg_vol_raw, (int, float)) else str(avg_vol_raw or 'N/A')

    tech_detail = f"""
  現在価格       : {technical_data.get('current_price', 'N/A')}
  RSI(14)        : {technical_data.get('rsi', 'N/A')}
  MA25 乖離率    : {technical_data.get('ma25_deviation', 'N/A')}%
  MA75 乖離率    : {ma75_str}
  BB 位置        : {technical_data.get('bb_position', 'N/A')}%
  出来高比率     : {technical_data.get('volume_ratio', 'N/A')}
  Perfect Order  : {technical_data.get('perfect_order', 'N/A')}
    （定義: MA5 > MA25 > MA75 > MA200 = 強気アライメント／逆順 = 弱気アライメント）
  時価総額       : {mkt_cap_str}
  平均出来高(20日): {avg_vol_str}
"""

    yuho_section = yuho_summary if yuho_summary else "（有報データ未取得）"
    sector_ctx   = _sector_context(sector)
    regime_ctx   = _regime_context(regime, sector)
    peer_set     = _peer_set(sector, ticker)

    # ピア比較テーブル用メトリクス
    roe       = fmt_pct(metrics.get('roe'), zero_as_na=True)
    pbr       = fmt_num(metrics.get('pbr'), zero_as_na=True)
    op_margin = fmt_pct(metrics.get('op_margin'))
    div_yield = fmt_pct(metrics.get('dividend_yield'))

    # 有報なし時の補足注記
    yuho_missing_note = ""
    if not yuho_summary or "未取得" in (yuho_summary or "") or "データなし" in (yuho_summary or ""):
        yuho_missing_note = (
            "\n⚠️ 【定性データ未取得の影響】\n"
            "  有報が取得できていないため Qualitative スコアは中立値（5.0）で固定されています。\n"
            "  定性面（経営リスク・競争優位性・経営陣の質）については以下の代替情報源を参照し\n"
            "  合理的な推定を行ってください：\n"
            "    - IR資料・決算説明会スライド（直近2期分）\n"
            "    - アナリストコンセンサスレポート（カバレッジ3名以上の場合は信頼度向上）\n"
            "    - 直近のプレスリリース・経営者インタビュー\n"
            "  アナリストカバレッジが3名以上ある場合は confidence を最大 0.7 まで許容します。\n"
            "  それ以外の場合は confidence を 0.6 以下に設定してください。\n"
        )

    prompt = f"""あなたはシニア・エクイティ・アナリストです。
以下の個別銘柄データセットに基づき、Investment Thesis を策定してください。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 基本情報・マクロ環境
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
銘柄名 / コード  : {company_name} ({ticker})
セクター         : {sector}
分析基準日       : {as_of_date}
市場レジーム     : {regime}
適用ウェイト     :
  Fundamental  : {w_fund:.0%}
  Valuation    : {w_val:.0%}
  Technical    : {w_tech:.0%}
  Qualitative  : {w_qual:.0%}

{regime_ctx}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. 財務指標詳細
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{fundamentals_detail}
{sector_ctx}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. テクニカル指標
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tech_detail}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. スコアカード概要 (10 点満点)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{scorecard_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. 定性データ・有価証券報告書要約
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{yuho_section}
{yuho_missing_note}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. 分析タスク
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
以下の 6 点について詳細に論じてください。

(1) スコアの背後にある定性・定量の整合性判定
    - 財務指標（ROE・PBR・営業利益率）と総合スコアの間に矛盾はないか。
    - セクター固有の評価基準（上記注意事項）を踏まえ、スコアが過大 / 過小評価でないか判断せよ。
    - 有報データがある場合は「経営リスク」「競争優位性」との整合性を検証。
      ない場合は業界知識から定性面を補完し、その不確実性を明示せよ。

(2) 市場レジーム ({regime}) に対する脆弱性と機会
    - 上記レジームコンテキストに沿って、このビジネスモデルへの影響を定量的に推定せよ。
    - MA25/MA75 乖離・RSI・BB 位置から「売られ過ぎ」「買われ過ぎ」の根拠を示せ。
    - テクニカルとファンダメンタルが乖離している場合、その要因（一時的 / 構造的）を判断せよ。

(3) 主要なアップサイド・ダウンサイドシナリオ（向こう 12 ヶ月）
    - アップサイド: 株価を動かす最大カタリスト 2〜3 件（具体的イベント・時期・株価インパクト）。
    - ダウンサイド: 投資を回避すべき最優先リスク 2〜3 件（トリガー条件・影響度を明示）。
    - ベースケース株価レンジ（現在価格比±%）を示せ。

(4) ピア比較テーブル（同業比較）
    ピアセット: {peer_set}
    上記ピア銘柄と以下の指標を比較し、対象銘柄の相対的な優劣を判定せよ。
    データが入手不能な場合は「比較不能」と明記し、自社の過去5年トレンドで代替せよ。

    | 指標     | {ticker} | 業界中央値 | 判定       |
    |---------|---------|-----------|-----------|
    | ROE     | {roe}  | ?%        | 上位/下位  |
    | PBR     | {pbr}倍 | ?倍        | 割高/割安  |
    | 営業利益率 | {op_margin} | ?% | 優位/劣位 |
    | 配当利回り | {div_yield} | ?% | 高/低    |

    さらに、以下の方法でファンダメンタルズに基づく目標株価を算出し、
    entry_price・take_profit・stop_loss の設定根拠として使用すること：
    ① PER目標法: セクター中央値PER × 今期EPS予想 = 目標株価（ベースケース）
    ② PBR目標法: セクター中央値PBR × BPS（1株純資産） = 目標株価（バリュー下限）
    時価総額が小型株（1,000億円未満）の場合は position_size を最大 0.05 に制限すること。

(5) マクロ感応度テーブル
    以下の各マクロ変数が±1標準偏差変化したとき、この銘柄の業績・株価への影響を推定せよ。
    推定困難な項目は「感応度不明」と記載し、理由を述べよ。

    | マクロ変数   | 現状 | +1σ変化時の影響            | 感応度     |
    |-----------|-----|--------------------------|----------|
    | 日/米10年金利 | -   | 業績±X% → 株価±X%予想      | 高/中/低  |
    | USD/JPY   | -   | 海外収益・輸出コスト±X%      | 高/中/低  |
    | VIX指数    | -   | センチメント変化 → 株価±X%   | 高/中/低  |
    | 原油価格    | -   | コスト・収益への影響±X%      | 高/中/低  |

(6) リスク定量化
    「経営リスク」または「ダウンサイドシナリオ」から主要リスク2〜3件を選び、以下の形式で定量化せよ。
    推定困難な場合も「推定不能（理由）」と必ず記載すること。

    リスクX: [リスク名]
      トリガー条件 : （例：信用スプレッド+50bp超、円急騰 ¥130割れ）
      EPS 影響推定  : -X〜-X%（根拠: 貸倒引当金+X億円想定 等）
      株価影響推定 : -X〜-X%
      発生確率推定 : X%（現レジーム・マクロ環境下）

━━━━━━━━━━━━━━━━━━━━━━━━━
7. 出力形式
━━━━━━━━━━━━━━━━━━━━━━━━━
■ コア・ピッチ（150 文字以内）
  投資すべきか否かの結論と核心的理由を 1 段落で。

■ 深掘り分析（各項目 300〜500 文字程度）
  上記タスク (1)〜(6) の論述。データ数値を引用して根拠を示すこと。

■ 出口戦略・監視ポイント
  - 損切り条件（価格・指標トリガー）
  - 利確条件（価格・イベントトリガー）
  - 継続保有を再評価すべき KPI（決算・マクロ指標）

■ 最終レーティング
  [強く推奨 / 推奨 / 中立 / 回避] と 12 ヶ月目標株価レンジ（ベース / ブル / ベア）。

━━━━━━━━━━━━━━━━━━━━━━━━━
8. 出力前セルフチェック【必須 — JSON 出力前に必ず確認】
━━━━━━━━━━━━━━━━━━━━━━━━━
JSON を出力する前に以下をすべて確認し、矛盾があれば該当箇所を修正してから出力せよ。

□ signal と最終レーティングは一致しているか
    BUY   ↔ [強く推奨 / 推奨]
    WATCH ↔ [中立]
    SELL  ↔ [回避]

□ score と confidence の整合性
    score < 5.0 かつ confidence > 0.7 → 矛盾（confidence を引き下げよ）
    有報なし かつ アナリストカバレッジ < 3名 かつ confidence > 0.6 → 矛盾（confidence を 0.6 以下にせよ）
    有報なし かつ アナリストカバレッジ ≥ 3名 → confidence は最大 0.7 まで許容

□ 価格設定の整合性
    stop_loss  < entry_price であること（stop_loss ≥ entry_price は設定ミス）
    take_profit > entry_price であること（take_profit ≤ entry_price は設定ミス）

□ position_size の整合性
    SELL シグナル → position_size = 0.0 であること
    WATCH かつ score < 5.0 → position_size ≤ 0.05 であること
    合計ポートフォリオ配分（既存保有 + 本銘柄）が 100% を超えないよう配慮すること

□ コア・ピッチの結論と signal は一致しているか
    「回避」「慎重」等の表現が本文にある → signal が BUY では矛盾

矛盾が1件でも検出された場合は、JSON 出力前に当該フィールドを修正すること。

━━━━━━━━━━━━━━━━━━━━━━━━━
9. JSON 出力（必須）
━━━━━━━━━━━━━━━━━━━━━━━━━
分析の最後に、以下の JSON を **コードブロック内** に出力してください。
フィールドの説明に従い、数値・文字列の型を厳守してください。

```json
{{
    "signal": "WATCH",
    "score": 5.9,
    "confidence": 0.65,
    "reasoning": "200 文字以内で投資判断の核心理由を記載",
    "entry_price": 2686.0,
    "stop_loss": 2500.0,
    "take_profit": 3100.0,
    "position_size": 0.05,
    "holding_period": "medium",
    "risks": ["リスク要因（具体的に）", "リスク要因 2"],
    "catalysts": ["カタリスト（具体的に）", "カタリスト 2"],
    "exit_strategy": "損切り条件と利確条件を 1 行で",
    "watch_points": ["次回決算 EPS 動向", "マクロ指標変化"]
}}
```

【JSON フィールド制約】
- signal    : "BUY" / "WATCH" / "SELL" の 3 値のみ。"HOLD" は使用禁止。
- score     : 0.0〜10.0（スコアカードの総合スコアと整合させること）
- confidence: 0.0〜1.0（有報なし・アナリスト3名未満の場合は 0.6 以下推奨。有報なしでもアナリスト3名以上なら最大 0.7 まで許容）
- entry_price / stop_loss / take_profit: 現在の市場価格を基準に現実的な数値で設定
- stop_loss : entry_price の -5〜-15% が目安（ボラティリティに応じて調整）
- take_profit: entry_price の +10〜+30% が目安（スコアと holding_period に応じて調整）
- position_size: BUY かつ score≥7.0 → 0.10〜0.20、WATCH → 0.03〜0.08、SELL → 0.0
    小型株（時価総額1,000億円未満）の場合は上記から-0.05し最大 0.05 とする
- holding_period: "short"（〜4週）/ "medium"（1〜6ヶ月）/ "long"（6ヶ月〜）
- risks / catalysts: 各 2〜4 件、具体的なイベント名・数値を含めること
"""
    return prompt


def build_simple_prompt(ticker: str, name: str = None):
    """
    簡易プロンプトを生成（データ取得なし）
    """
    if name is None:
        name = ticker

    prompt = f"""あなたは優秀な金融アナリストです。
以下の銘柄のデータを収集・分析し、投資判断を JSON 形式で出力してください。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【対象銘柄】{name} ({ticker})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【タスク】
1. 上記銘柄の最新財務データを収集（ROE, PER, PBR, 営業利益率など）
2. テクニカル指標を確認（RSI, 移動平均乖離率など）
3. 競合他社と比較分析
4. 投資判断（BUY/WATCH/SELL）を導出

【出力形式】
以下の JSON 形式で**必ず**出力してください。

```json
{{
    "signal": "BUY",
    "score": 7.5,
    "confidence": 0.8,
    "reasoning": "判断理由を 200 文字以内で記載",
    "entry_price": 2850,
    "stop_loss": 2700,
    "take_profit": 3100,
    "position_size": 0.12,
    "holding_period": "medium",
    "risks": ["リスク要因 1", "リスク要因 2"],
    "catalysts": ["カタリスト 1", "カタリスト 2"]
}}
```

【各フィールドの説明】
- signal: 必ず "BUY"（推奨）, "WATCH"（様子見）, "SELL"（売却）の3値のみ。"HOLD" は使用禁止。中立判断は "WATCH" を使うこと。
- score: 0-10 のスコア（10 が最強）
- confidence: 0-1 の信頼度（1 が最高）
- reasoning: 判断理由（200 文字以内）
- entry_price: 推奨エントリー価格
- stop_loss: 損切り価格
- take_profit: 利確価格
- position_size: ポジションサイズ（0.0-1.0）
- holding_period: "short" (数日), "medium" (数週間), "long" (数ヶ月〜)
- risks: リスク要因リスト（最大 5 件）
- catalysts: 株価上昇のカタリスト（最大 5 件）
"""
    return prompt


def build_enhanced_prompt_with_data(
    ticker: str,
    company_name: str = None,
    sector: str = None,
    financial_data: Dict = None,
    technical_data: Dict = None,
    news_data: Dict = None,
    analyst_data: Dict = None,
    industry_data: Dict = None,
    edinetdb_data: Dict = None,
    jquants_data: list = None,
    jquants_source: str = "jquants",
    web_news_data: list = None,
    yuho_summary: str = None,
) -> str:
    """
    全ての定性情報を含む完全版プロンプトを生成
    """
    name = company_name or ticker
    current_date = datetime.now().strftime("%Y年%m月%d日")
    current_year = datetime.now().year
    current_quarter_num = (datetime.now().month - 1) // 3 + 1
    next_q_num = current_quarter_num + 1 if current_quarter_num < 4 else 1
    next_q_year = current_year if current_quarter_num < 4 else current_year + 1

    sections = []

    # 1. 基本情報
    sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【基本情報】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
銘柄名          : {name} ({ticker})
セクター        : {sector or 'Unknown'}
分析基準日      : {current_date}
""")

    # 2. 財務指標
    if financial_data and financial_data.get('metrics'):
        m = financial_data['metrics']
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【財務指標】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ROE            : {fmt_pct(m.get('roe'), zero_as_na=True)}
  PER            : {fmt_num(m.get('per'), zero_as_na=True)}倍
  PBR            : {fmt_num(m.get('pbr'), zero_as_na=True)}倍
  営業利益率     : {fmt_pct(m.get('op_margin'))}
  自己資本比率   : {fmt_pct(m.get('equity_ratio'))}
  配当利回り     : {fmt_pct(m.get('dividend_yield'))}
  営業 CF/純利益 : {fmt_num(m.get('cf_quality'))}
  R&D 比率       : {fmt_pct(m.get('rd_ratio'))}
""")

    # 3. テクニカル指標
    if technical_data:
        t = technical_data
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【テクニカル指標】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  現在価格       : {t.get('current_price', 'N/A')}
  RSI(14)        : {t.get('rsi', 'N/A')}
  MA25 乖離率    : {t.get('ma25_deviation', 'N/A')}%
  BB 位置        : {t.get('bb_position', 'N/A')}%
  出来高比率     : {t.get('volume_ratio', 'N/A')}
  Perfect Order  : {t.get('perfect_order', 'N/A')}
""")

    # 4. ニュース（生データ）
    if news_data and news_data.get('available'):
        from src.news_fetcher import format_news_for_prompt
        news_section = format_news_for_prompt(news_data)

        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【ニュース（生データ）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{news_section}
""")

    # 4.5 高機能ウェブ検索ニュース（Exa / Perplexity 等）
    if web_news_data:
        lines = []
        # ナビゲーションや空コンテンツを含む低品質アイテムを除外
        _nav_noise = re.compile(
            r"(ポートフォリオに追加|リアルタイム株価|関連ニュース|適時開示|株つぶやき|"
            r"ヘルプ|朝刊・夕刊|Myニュース|ご購読|Market Closed|Add to a list)"
        )
        for n in web_news_data:
            title = n.get('title', '').strip()
            # data_source を source 優先で取得
            source = n.get('data_source', n.get('source', 'Web')).upper()
            content = n.get('content', n.get('snippet', '')).strip()
            # 実質的な内容がないアイテムはスキップ
            if not title or not content or len(content) < 30:
                continue
            if _nav_noise.search(content[:80]):
                continue
            # 150 字に切り詰め、末尾を整える
            snippet = content[:160].rsplit("。", 1)[0] if "。" in content[:160] else content[:160]
            lines.append(f"- 【{source}】 {title}\n  {snippet}")
        if lines:
            news_str = "\n".join(lines)
            sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【AI高機能ウェブ検索ニュース (ディープサーチ)】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{news_str}
""")

    # 5. アナリスト評価
    if analyst_data and analyst_data.get('available'):
        from src.analyst_ratings import format_analyst_for_prompt
        consensus = analyst_data.get('consensus', {})
        price_target = analyst_data.get('price_target', {})

        analyst_section = format_analyst_for_prompt(analyst_data)

        upside = price_target.get('upside_pct', 0) if price_target else 0
        target_mean = price_target.get('target_mean') if price_target else None

        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【アナリスト評価・コンセンサス】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{analyst_section}
""")

    # 6. 業界・競合分析タスク（Groq生成を廃止→Claudeに直接依頼）
    if sector:
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【業界・競合分析タスク】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  セクター: {sector}
  ※{sector}セクターにおける競合比較と業界展望を、上記データを元にあなた自身が分析してください。
  （主要競合との財務比較・競争優位性・成長ドライバー・構造的リスクを含めること）
""")

    # 6.5 EDINET DB と J-Quants (日本株限定の高精度データ)
    if edinetdb_data and edinetdb_data.get('available'):
        score = edinetdb_data.get('health_score', 'N/A')
        analysis = edinetdb_data.get('analysis', {})
        # get_analysis() は 'summary' キーで要約を返す
        ai_summary = analysis.get('summary', '') or analysis.get('overall_summary', '')
        # strengths/weaknesses は raw データから取得を試みる
        raw = analysis.get('raw', {})
        s_list = analysis.get('strengths', []) or raw.get('strengths', [])
        w_list = analysis.get('weaknesses', []) or raw.get('weaknesses', [])
        strengths = "\n    - ".join(s_list) if s_list else "なし"
        weaknesses = "\n    - ".join(w_list) if w_list else "なし"

        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【EDINET DB 財務健全性＆AI分析（日本株公式データ）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  財務健全性スコア : {score} / 100
  AIサマリー       : {ai_summary}
  強み             :
    - {strengths}
  弱み             :
    - {weaknesses}
""")
    elif yuho_summary and not any(x in (yuho_summary or "") for x in ["未取得", "データなし", "エラー"]):
        # EDINET DB 未設定時は有報生テキスト抜粋を直接埋め込む
        sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【有価証券報告書 抜粋（生テキスト）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
※以下の有報テキストを分析し、リスク・競争優位性・経営課題を抽出してください。

{yuho_summary}
""")

    if jquants_data:
        try:
            # get_price_history() は小文字キー date/close/volume を返す
            recent_prices = [
                f"  {row.get('date', '')[5:]}: {row.get('close', 0):.1f}円 (Vol: {int(row.get('volume', 0)):,})"
                for row in jquants_data[-10:]
            ]
            price_str = "\n".join(recent_prices)
            if jquants_source == "yfinance":
                section_title = "【直近株価推移 (OHLC)】"
            else:
                section_title = "【J-Quants 直近株価推移 (東証公式OHLC)】"
            sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{section_title}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{price_str}
""")
        except Exception:
            pass

    # 7. 分析タスク
    sections.append(f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【分析タスク】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
以下の 3 点について詳細に分析し、投資判断を導出してください：

1. 総合評価（定量×定性のクロスチェック）
   - 財務指標（ROE, PER, PBR, 営業利益率）の業界平均との比較
   - テクニカル指標（RSI, 移動平均乖離率）からのエントリータイミング
   - ニュースセンチメントと株価のモメンタムの整合性
   - アナリスト評価とコンセンサスの方向性
   - 業界動向に対する会社の競争ポジショニング

2. 投資判断の根拠（具体的な数値で示す）
   - BUY/WATCH/SELL の推奨と、その確信度（0-1）
   - 向こう 12 ヶ月の主要カタリスト（具体的なイベント名と時期）
   - 主要リスク要因と発生確率、影響度
   - エントリー・利確・損切りの具体的な価格水準（根拠も記載）
   - 適正ポジションサイズ（ポートフォリオの何%か）

3. シナリオ分析（確率付きで具体性を持って）
   - ベースケース（確率 50-60%）：コンセンサス通りの場合
   - ブルケース（確率 20-30%）：好材料が実現した場合
   - ベアケース（確率 20-30%）：悪材料が実現した場合
   - 各シナリオでの目標株価と期間、トリガー

【重要】
- 個別銘柄のアルファ（固有要因）と、ベータ（市場要因）を区別して分析
- 直近の株価材料（決算、発表等）を必ず考慮
- リスク要因は「発生確率」と「影響度」を明記
- 数値は具体的な根拠（例：「PER 12 倍は業界平均 15 倍より 20% 割安」）を示す

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【出力形式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
以下の JSON 形式で**必ず**出力してください。

```json
{{
    "signal": "BUY",
    "score": 7.5,
    "confidence": 0.85,
    "reasoning": "現在の市場環境、業界展望、企業業績を踏まえた判断理由を 300 文字以内で記載",
    "industry_outlook": "業界の将来性についての見解を 100 文字以内",
    "competitive_position": "競争地位の評価を 100 文字以内",
    "entry_price": 340.0,
    "stop_loss": 300.0,
    "take_profit": 400.0,
    "position_size": 0.12,
    "holding_period": "medium",
    "time_horizon": "12-18 months",
    "key_catalysts": [
        {{
            "event": "次四半期決算発表",
            "expected_timing": "{current_year}Q{next_q_num}",
            "impact": "high",
            "probability": 0.8
        }},
        {{
            "event": "新製品発表",
            "expected_timing": "{next_q_year}Q{(next_q_num % 4) + 1}",
            "impact": "medium",
            "probability": 0.6
        }}
    ],
    "key_risks": [
        {{
            "risk": "半導体サイクルの下落局面入り",
            "impact": "high",
            "mitigation": "ポートフォリオの分散とヘッジ"
        }},
        {{
            "risk": "中国規制強化",
            "impact": "medium",
            "mitigation": "地域別売上のモニタリング"
        }}
    ],
    "scenario_analysis": {{
        "bull_case": {{
            "target": 450.0,
            "probability": 0.25,
            "scenario": "AI 需要の継続とシェア拡大で EPS がコンセンサス 15% 上振れ"
        }},
        "base_case": {{
            "target": 380.0,
            "probability": 0.50,
            "scenario": "コンセンサス通りの成長、バリュエーションは現状維持"
        }},
        "bear_case": {{
            "target": 280.0,
            "probability": 0.25,
            "scenario": "景気後退で半導体投資が減少、マージン圧迫"
        }}
    }},
    "esg_factors": {{
        "environmental": "環境面の評価と課題",
        "social": "社会面の評価と課題",
        "governance": "ガバナンス面の評価と課題"
    }}
}}
```

【各フィールドの説明】
- signal: "BUY"（推奨）, "WATCH"（様子見）, "SELL"（売却）のいずれか
- score: 0-10 の総合スコア（10 が最強）
- confidence: 0-1 の信頼度（1 が最高）
- reasoning: 判断理由（300 文字以内）
- industry_outlook: 業界展望（100 文字以内）
- competitive_position: 競争地位（100 文字以内）
- entry_price: 推奨エントリー価格
- stop_loss: 損切り価格
- take_profit: 利確価格
- position_size: ポジションサイズ（0.0-1.0）
- holding_period: "short" (数日), "medium" (数週間), "long" (数ヶ月〜)
- time_horizon: 投資期間の見通し
- key_catalysts: 株価上昇のカタリスト（最大 5 件）
- key_risks: リスク要因と緩和策（最大 5 件）
- scenario_analysis: シナリオ別目標株価と確率
- esg_factors: ESG 評価
""")

    return "\n".join(sections)


def build_full_prompt(ticker: str, include_qualitative: bool = True):
    """
    完全版プロンプトを生成（データ取得あり）

    Parameters
    ----------
    ticker             : 銘柄コード
    include_qualitative: ニュース・アナリスト・業界データを含むか
    """
    print(f"📈 株価データ取得中...")
    try:
        from src.data_fetcher import fetch_stock_data
        data = fetch_stock_data(ticker)
    except Exception as e:
        print(f"⚠️ データ取得失敗：{e}")
        return build_simple_prompt(ticker)

    if not data or not data.get('metrics'):
        return build_simple_prompt(ticker)

    news_data = None
    analyst_data = None
    industry_data = None

    if include_qualitative:
        try:
            from src.news_fetcher import fetch_all_news
            news_data = fetch_all_news(ticker, company_name=data.get('name'), include_google=True)
        except Exception as e:
            print(f"  ⚠️ ニュース取得エラー：{e}")

        try:
            from src.analyst_ratings import fetch_all_analyst_data
            analyst_data = fetch_all_analyst_data(ticker)
        except Exception as e:
            print(f"  ⚠️ アナリスト評価取得エラー：{e}")

        # 業界動向取得は廃止（Groq呼び出し排除）→ Claudeが直接分析
        # industry_data は None のまま（build_enhanced_prompt_with_data に sector のみ渡す）

    # 日本株専用：新規統合API群の取得
    edinetdb_data = None
    jquants_data = None
    jquants_source = "jquants"
    web_news_data = None
    yuho_summary = None
    if ticker.endswith('.T'):
        try:
            from src.edinetdb_client import get_full_company_data
            edinetdb_data = get_full_company_data(ticker)
        except Exception as e:
            print(f"  ⚠️ EDINET DB取得エラー：{e}")

        # EDINET DB 未設定時のフォールバック: 有報生テキスト抜粋を取得（AI解析なし）
        if not (edinetdb_data and edinetdb_data.get('available')):
            try:
                from src.edinet_client import extract_yuho_data
                yuho_data = extract_yuho_data(ticker, skip_ai=True)
                raw_text = yuho_data.get("raw_text", "")
                if raw_text:
                    yuho_summary = _extract_yuho_sections(raw_text)
                    print(f"  ✓ EDINET 有報生テキスト取得（{len(raw_text)}文字 → 有効セクション抽出）")
            except Exception as e:
                print(f"  ⚠️ EDINET 有報取得エラー：{e}")
            
        try:
            from src.jquants_client import get_price_history
            jquants_data = get_price_history(ticker, days=20)
        except Exception as e:
            print(f"  ⚠️ J-Quants取得エラー：{e}")

        # J-Quants が空（プラン制限等）の場合 yfinance OHLC でフォールバック
        jquants_source = "jquants"
        if not jquants_data:
            try:
                import yfinance as yf
                hist = yf.Ticker(ticker).history(period="20d")
                if not hist.empty:
                    if hist.index.tz is not None:
                        hist.index = hist.index.tz_localize(None)
                    jquants_data = [
                        {
                            "date":   row.Index.strftime("%Y-%m-%d"),
                            "open":   float(row.Open),
                            "high":   float(row.High),
                            "low":    float(row.Low),
                            "close":  float(row.Close),
                            "volume": float(row.Volume),
                        }
                        for row in hist.itertuples()
                    ]
                    jquants_source = "yfinance"
                    print(f"  ✓ J-Quants フォールバック: yfinance から {len(jquants_data)} 件の OHLC を取得")
            except Exception as e:
                print(f"  ⚠️ yfinance OHLC フォールバック失敗：{e}")
            
        if include_qualitative:
            try:
                from src.news_fetcher import fetch_web_search_news
                query = f"{data.get('name', ticker)} 株価 業績 ニュース"
                web_news_data = fetch_web_search_news(query, max_results=5)
            except Exception as e:
                print(f"  ⚠️ Web News取得エラー：{e}")

            # Exa/Web検索結果を本文ニュースセクション（all_news）にもマージ
            if web_news_data and news_data and news_data.get("available"):
                existing_titles = {
                    n.get("title", "").lower() for n in news_data.get("all_news", [])
                }
                web_merged = 0
                for item in web_news_data:
                    title = item.get("title", "")
                    if not title or title.lower() in existing_titles:
                        continue
                    news_data["all_news"].append({
                        "title": title,
                        "publisher": item.get("data_source", "exa").upper(),
                        "link": item.get("url", ""),
                        "published_at": item.get("published_at") or "",
                        "type": "STORY",
                        "thumbnail": "",
                        "data_source": item.get("data_source", "exa"),
                    })
                    existing_titles.add(title.lower())
                    web_merged += 1
                if web_merged > 0:
                    print(f"  ✓ Web検索結果 {web_merged} 件を本文ニュースにマージ")
                    news_data["all_news"].sort(
                        key=lambda n: (n.get("published_at") or "")[:10] or "0000-00-00",
                        reverse=True,
                    )

    prompt = build_enhanced_prompt_with_data(
        ticker=ticker,
        company_name=data.get('name'),
        sector=data.get('sector'),
        financial_data=data,
        technical_data=data.get('technical', {}),
        news_data=news_data,
        analyst_data=analyst_data,
        industry_data=industry_data,
        edinetdb_data=edinetdb_data,
        jquants_data=jquants_data,
        jquants_source=jquants_source,
        web_news_data=web_news_data,
        yuho_summary=yuho_summary,
    )

    return prompt


def collect_data_minimal(ticker: str, use_cache: bool = True) -> tuple:
    """
    最小限の API 呼び出しで必要なデータを収集
    キャッシュ優先で効率的に取得

    Returns
    -------
    (data_dict, api_calls_count, yuho_summary)
    """
    api_calls = 0
    cache = None
    yuho_summary = "（有報データ未取得）"

    if use_cache:
        from src.data_cache import get_cache
        cache = get_cache()

    # 株価データ取得（キャッシュ優先）
    cache_result = None
    if cache:
        cache_result = cache.get(ticker, "stock_data", ttl_hours=1.0)

    # キャッシュ構造のアンラップ（cache.get() はラッパーオブジェクトを返す場合がある）
    if cache_result:
        if isinstance(cache_result, dict) and 'data' in cache_result:
            data = cache_result.get('data')
        else:
            data = cache_result
    else:
        data = None

    if data is None:
        try:
            from src.data_fetcher import fetch_stock_data
            data = fetch_stock_data(ticker)
            api_calls = 1
            if cache and data:
                cache.set(ticker, "stock_data", data, ttl_hours=1.0)
        except Exception as e:
            print(f"⚠️ データ取得失敗：{e}")
            return None, api_calls, yuho_summary

    if not data or not data.get('metrics'):
        print(f"⚠️ 財務データが取得できませんでした")
        return None, api_calls, yuho_summary

    # スコアカード生成
    try:
        from src.analyzers import generate_scorecard
        from src.macro_regime import get_macro_regime
        from src.utils import load_config_with_overrides

        # マクロレジーム取得（軽量）
        config = load_config_with_overrides(ticker)
        regime = get_macro_regime(datetime.now(), config, ticker=ticker)

        # 財務指標
        metrics = data.get('metrics', {})
        tech_data = data.get('technical', {})
        sector = data.get('sector', '')

        # 有報データ（日本株: EDINET, 米国株: SEC）
        yuho_data = {}
        sec_chunking_meta = None
        if ticker.endswith('.T'):
            try:
                from src.edinet_client import extract_yuho_data
                yuho_data = extract_yuho_data(ticker, skip_ai=True)
                raw_text = yuho_data.get("raw_text", "")
                yuho_summary = _extract_yuho_sections(raw_text) if raw_text else "（有報テキスト未取得）"
            except Exception as e:
                yuho_summary = f"（有報データ取得エラー: {e}）"
        elif HAS_SEC and is_us_stock(ticker):
            try:
                from src.analyzers import format_yuho_for_prompt
                yuho_data = extract_sec_data(ticker, no_cache=not use_cache)
                yuho_summary = format_yuho_for_prompt(yuho_data)
                if not yuho_data or not yuho_data.get('available'):
                    yuho_summary = "（SEC 10-K/10-Q データなし）"
                sec_chunking_meta = yuho_data.get('chunking_meta') if isinstance(yuho_data, dict) else None
            except Exception as e:
                yuho_summary = f"（SEC 取得エラー: {e}）"
                sec_chunking_meta = None

        # スコアカード生成
        buy_threshold = (
            config.get("signals", {})
                  .get("BUY", {})
                  .get("regime_overrides", {})
                  .get(regime, {})
                  .get("min_score", config.get("signals", {}).get("BUY", {}).get("min_score", 6.5))
        )

        scorecard = generate_scorecard(
            metrics,
            tech_data,
            yuho_data,  # 抽出した定性データを反映
            sector=sector,
            macro_data={"regime": regime},
            buy_threshold=buy_threshold,
        )

        # レジームウェイト取得
        regime_weights = (
            config.get("macro", {})
                  .get("regime_weights", {})
                  .get(regime, {})
        )
        if not regime_weights:
            regime_weights = {"fundamental": 0.30, "valuation": 0.25, "technical": 0.25, "qualitative": 0.20}

        # 結果を統合
        result = {
            'name': data.get('name', ticker),
            'sector': sector,
            'metrics': metrics,
            'technical': tech_data,
            'scorecard': scorecard,
            'regime': regime,
            'regime_weights': regime_weights,
            'sec_chunking_meta': sec_chunking_meta,
        }

        return result, api_calls, yuho_summary

    except Exception as e:
        print(f"⚠️ 分析エラー：{e}")
        # エラー時は基本データのみ使用
        return None, api_calls, yuho_summary


def copy_to_clipboard(text: str) -> bool:
    """テキストをクリップボードにコピー"""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def generate_output_filename(ticker: str) -> str:
    """自動生成される出力ファイル名"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ticker = ticker.replace('.', '_')
    return f"{safe_ticker}_{timestamp}.txt"


def main():
    parser = argparse.ArgumentParser(description='LLM 用投資判断プロンプトを生成')
    parser.add_argument('ticker', help='銘柄コード（例：7203.T, AAPL, XOM）')
    parser.add_argument('-o', '--output', help=f'出力ファイルパス（指定がない場合は prompts/ 配下に自動保存）')
    parser.add_argument('--copy', action='store_true', help='クリップボードにコピー')
    parser.add_argument('--simple', action='store_true', help='簡易モード（データ取得なし）')
    parser.add_argument('--no-qualitative', action='store_true', help='定性情報（ニュース・アナリスト・業界動向）をスキップ')
    parser.add_argument('--no-cache', action='store_true', help='キャッシュを使用しない')
    parser.add_argument('--model', choices=['gemini', 'qwen', 'chatgpt', 'claude', 'groq'],
                       default='groq', help='対象モデル')

    args = parser.parse_args()
    args.ticker = args.ticker.upper()  # 大文字正規化: 8306.t → 8306.T (endswith('.T') は大文字小文字を区別するため必須)

    print(f"🔍 プロンプト生成中：{args.ticker}")

    # プロンプト生成
    data = None  # context JSON 用（best-effort）
    api_calls = 0
    if args.simple:
        prompt = build_simple_prompt(args.ticker)
    else:
        # 強化モード（デフォルト）：ニュース・アナリスト・業界動向を含む完全版
        print(f"📊 データ収集中（定性情報含む）...")
        prompt = build_full_prompt(args.ticker, include_qualitative=not args.no_qualitative)
        api_calls = 1

        # context JSON 保存用にスコアカードデータを別途収集（best-effort）
        try:
            data, _, _ = collect_data_minimal(args.ticker, use_cache=True)
        except Exception:
            data = None

    # 出力先決定
    output_path = args.output
    if output_path is None:
        # デフォルト：prompts/ ディレクトリに自動保存
        filename = generate_output_filename(args.ticker)
        output_path = str(DEFAULT_OUTPUT_DIR / filename)

    # ファイルに保存
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(prompt)
    print(f"✅ 保存先：{output_path}")

    # コンテキスト JSON を保存（save_claude_result.py が利用）
    if data is not None and not args.simple:
        safe_ticker = args.ticker.replace('.', '_')
        context_path = DEFAULT_OUTPUT_DIR / f"{safe_ticker}_context.json"
        context = {
            "ticker": args.ticker,
            "name": data.get('name', args.ticker),
            "sector": data.get('sector', 'Unknown'),
            "currency": "JPY" if args.ticker.endswith('.T') else "USD",
            "metrics":   data.get('metrics', {}),
            "technical": data.get('technical', {}),
            "scorecard": data.get('scorecard', {}),
            "regime": data.get('regime', 'NEUTRAL'),
            "regime_weights": data.get('regime_weights', {}),
            "generated_at": datetime.now().isoformat(),
        }
        try:
            import numpy as np

            class _NpEncoder(json.JSONEncoder):
                def default(self, obj):
                    if isinstance(obj, (np.integer,)):  return int(obj)
                    if isinstance(obj, (np.floating,)): return float(obj)
                    if isinstance(obj, np.ndarray):     return obj.tolist()
                    if isinstance(obj, (np.bool_,)):    return bool(obj)
                    return super().default(obj)

            context_path.write_text(
                json.dumps(context, indent=2, ensure_ascii=False, cls=_NpEncoder),
                encoding='utf-8'
            )
        except Exception:
            context_path.write_text(
                json.dumps(context, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
        print(f"📋 コンテキスト保存: {context_path}")

    # クリップボードコピー
    if args.copy:
        if copy_to_clipboard(prompt):
            print(f"✅ クリップボードにコピーしました")
        else:
            print(f"⚠️ クリップボードコピー失敗（pyperclip をインストール：pip install pyperclip）")

    # 画面表示
    print(f"\n{'='*60}")
    print(prompt)
    print(f"{'='*60}")

    print(f"\n💡 次のステップ:")
    print(f"   1. 上記プロンプトを Claude Sonnet 等に貼り付け")
    print(f"   2. 回答全体をコピー")
    print(f"   3. 回答をダッシュボードに保存:")
    print(f"      ./venv/bin/python3 save_claude_result.py {args.ticker} --from-clipboard")

    # API 呼び出し状況
    if api_calls > 0:
        print(f"\n📊 API 呼び出し：{api_calls}回（株価データ）")
    else:
        print(f"\n✅ API 呼び出しなし（キャッシュまたは簡易モード）")

    print(f"\n💡 ヒント:")
    print(f"   --simple         : データ取得なし（最速）")
    print(f"   --no-qualitative : ニュース・アナリスト・業界動向をスキップ")
    print(f"   --no-cache       : 最新データ取得（API 呼び出しあり）")
    print(f"   -o <path>        : 出力先を指定")


if __name__ == '__main__':
    main()
