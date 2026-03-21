#!/usr/bin/env python3
"""
generate_prompt.py - 投資判断用プロンプト生成ツール（高品質・最小 API 版）
=====================================================
銘柄コードを指定するだけで、LLM 用の投資判断プロンプトを生成します。

スコアカード（Fundamental, Valuation, Technical, Qualitative）と
マクロレジーム分析をベースにした高品質なプロンプトを生成します。

使い方:
    ./venv/bin/python3 generate_prompt.py 7203.T
    ./venv/bin/python3 generate_prompt.py AAPL -o custom_prompt.txt
    ./venv/bin/python3 generate_prompt.py XOM --copy  # クリップボードにコピー
"""

import argparse
import json
import os
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
  ROE            : {metrics.get('roe', 'N/A')}%
  PER            : {metrics.get('per', 'N/A')}倍
  PBR            : {metrics.get('pbr', 'N/A')}倍
  営業利益率     : {metrics.get('op_margin', 'N/A')}%
  自己資本比率   : {metrics.get('equity_ratio', 'N/A')}%
  配当利回り     : {metrics.get('dividend_yield', 'N/A')}%
  営業 CF/純利益 : {metrics.get('cf_quality', 'N/A')}
  R&D 比率       : {metrics.get('rd_ratio', 'N/A')}%
"""

    ma75_dev = technical_data.get('ma75_deviation', 'N/A')
    ma75_str = f"{ma75_dev}%" if ma75_dev != 'N/A' else 'N/A'
    tech_detail = f"""
  現在価格       : {technical_data.get('current_price', 'N/A')}
  RSI(14)        : {technical_data.get('rsi', 'N/A')}
  MA25 乖離率    : {technical_data.get('ma25_deviation', 'N/A')}%
  MA75 乖離率    : {ma75_str}
  BB 位置        : {technical_data.get('bb_position', 'N/A')}%
  出来高比率     : {technical_data.get('volume_ratio', 'N/A')}
  Perfect Order  : {technical_data.get('perfect_order', 'N/A')}
"""

    yuho_section = yuho_summary if yuho_summary else "（有報データ未取得）"
    sector_ctx   = _sector_context(sector)
    regime_ctx   = _regime_context(regime, sector)

    # 有報なし時の補足注記
    yuho_missing_note = ""
    if not yuho_summary or "未取得" in (yuho_summary or "") or "データなし" in (yuho_summary or ""):
        yuho_missing_note = (
            "\n⚠️ 【定性データ未取得の影響】\n"
            "  有報が取得できていないため Qualitative スコアは中立値（5.0）で固定されています。\n"
            "  定性面（経営リスク・競争優位性・経営陣の質）については公知情報・業界知識から\n"
            "  合理的な推定を行い、confidence（信頼度）を低めに設定してください。\n"
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
以下の 3 点について詳細に論じてください。

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

━━━━━━━━━━━━━━━━━━━━━━━━━
7. 出力形式
━━━━━━━━━━━━━━━━━━━━━━━━━
■ コア・ピッチ（150 文字以内）
  投資すべきか否かの結論と核心的理由を 1 段落で。

■ 深掘り分析（各項目 300〜500 文字程度）
  上記タスク (1)(2)(3) の論述。データ数値を引用して根拠を示すこと。

■ 出口戦略・監視ポイント
  - 損切り条件（価格・指標トリガー）
  - 利確条件（価格・イベントトリガー）
  - 継続保有を再評価すべき KPI（決算・マクロ指標）

■ 最終レーティング
  [強く推奨 / 推奨 / 中立 / 回避] と 12 ヶ月目標株価レンジ（ベース / ブル / ベア）。

━━━━━━━━━━━━━━━━━━━━━━━━━
8. JSON 出力（必須）
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
- confidence: 0.0〜1.0（有報なし・レジーム不確実性が高い場合は 0.6 以下を推奨）
- entry_price / stop_loss / take_profit: 現在の市場価格を基準に現実的な数値で設定
- stop_loss : entry_price の -5〜-15% が目安（ボラティリティに応じて調整）
- take_profit: entry_price の +10〜+30% が目安（スコアと holding_period に応じて調整）
- position_size: BUY かつ score≥7.0 → 0.10〜0.20、WATCH → 0.03〜0.08、SELL → 0.0
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
                from src.analyzers import format_yuho_for_prompt
                yuho_data = extract_yuho_data(ticker)
                yuho_summary = format_yuho_for_prompt(yuho_data)
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
    except:
        return False


def generate_output_filename(ticker: str) -> str:
    """自動生成される出力ファイル名"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ticker = ticker.replace('.', '_')
    return f"{safe_ticker}_{timestamp}.txt"


def main():
    parser = argparse.ArgumentParser(description='LLM 用投資判断プロンプトを生成（高品質版）')
    parser.add_argument('ticker', help='銘柄コード（例：7203.T, AAPL, XOM）')
    parser.add_argument('-o', '--output', help=f'出力ファイルパス（指定がない場合は prompts/ 配下に自動保存）')
    parser.add_argument('--copy', action='store_true', help='クリップボードにコピー')
    parser.add_argument('--simple', action='store_true', help='簡易モード（データ取得なし）')
    parser.add_argument('--no-cache', action='store_true', help='キャッシュを使用しない')
    parser.add_argument('--model', choices=['gemini', 'qwen', 'chatgpt', 'claude', 'groq'],
                       default='groq', help='対象モデル')

    args = parser.parse_args()

    print(f"🔍 プロンプト生成中：{args.ticker}")

    # プロンプト生成
    if args.simple:
        prompt = build_simple_prompt(args.ticker)
        api_calls = 0
    else:
        # 高品質モード：データを収集してプロンプト生成
        print(f"📊 データ収集中（キャッシュ優先）...")
        data, api_calls, yuho_summary = collect_data_minimal(
            args.ticker,
            use_cache=not args.no_cache
        )

        if data is None:
            print(f"⚠️ データ取得失敗のため、簡易プロンプトを生成します")
            prompt = build_simple_prompt(args.ticker)
        else:
            print(f"📝 プロンプト生成中...")
            prompt = build_high_quality_prompt(
                ticker=args.ticker,
                company_name=data.get('name', args.ticker),
                sector=data.get('sector', 'Unknown'),
                as_of_date=datetime.now().strftime("%Y-%m-%d"),
                regime=data.get('regime', 'NEUTRAL'),
                regime_weights=data.get('regime_weights', {}),
                scorecard=data.get('scorecard', {}),
                financial_metrics=data.get('metrics', {}),
                technical_data=data.get('technical', {}),
                yuho_summary=yuho_summary,
            )
            # Groq チャンク分割解析が発生した場合は警告をプロンプト冒頭に挿入
            sec_meta = data.get('sec_chunking_meta') if data else None
            if sec_meta:
                try:
                    from sec_analyzer_patch import inject_warning_into_prompt
                    prompt = inject_warning_into_prompt(prompt, sec_meta)
                except ImportError:
                    pass

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
    print(f"   --simple    : データ取得なし（最速）")
    print(f"   --no-cache  : 最新データ取得（API 呼び出しあり）")
    print(f"   -o <path>   : 出力先を指定")


if __name__ == '__main__':
    main()
