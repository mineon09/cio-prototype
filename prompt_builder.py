"""
prompt_builder.py
-----------------
スコアカード・マクロレジーム・有報データを収集し、
LLM 投資分析プロンプトを自動生成するモジュール。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf

# ロガー設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("CIO_PromptBuilder")

# ---------------------------------------------------------------------------
# 内部 import（実プロジェクトの構造に合わせる）
# ---------------------------------------------------------------------------
try:
    from src.analyzers import generate_scorecard, TechnicalAnalyzer, format_yuho_for_prompt
    from src.macro_regime import get_macro_regime
    from src.data_fetcher import fetch_stock_data
    from src.utils import load_config_with_overrides
    from src.edinet_client import extract_yuho_data
except ImportError as e:
    logger.error(f"モジュールインポートエラー: {e}")
    raise

# SEC EDGAR（利用可能な場合のみ）
try:
    from src.sec_client import extract_sec_data, is_us_stock
    HAS_SEC = True
except ImportError:
    HAS_SEC = False
    def is_us_stock(ticker): return not str(ticker).endswith('.T')
    def extract_sec_data(ticker): return {}


# ---------------------------------------------------------------------------
# データクラス: 収集した全データをまとめるコンテナ
# ---------------------------------------------------------------------------
@dataclass
class PromptPayload:
    ticker: str
    company_name: str
    as_of_date: datetime
    regime: str
    regime_weights: dict
    scorecard: dict                    # generate_scorecard の生出力
    scorecard_text: str                # 整形済みテキスト
    yuho_summary: str                  # format_yuho_for_prompt の出力
    sector: str = ""                   # セクター文字列（セクター別フレーム生成用）
    raw_metrics: dict = field(default_factory=dict)   # デバッグ用


# ---------------------------------------------------------------------------
# Step 1: データ収集
# ---------------------------------------------------------------------------
def collect_prompt_data(
    ticker: str,
    as_of_date: Optional[datetime] = None,
    history_days: int = 400,
) -> PromptPayload:
    """
    LLM プロンプトに必要な全データを収集して PromptPayload を返す。

    Parameters
    ----------
    ticker       : 銘柄コード (例: "7203.T", "AAPL")
    as_of_date   : 分析基準日。None の場合は当日
    history_days : 過去データ取得日数 (テクニカル計算用)
    """
    as_of_date = as_of_date or datetime.today()
    config = load_config_with_overrides(ticker)

    # --- 1-A. 価格履歴 (PIT スライス) ---
    hist_start = (as_of_date - pd.Timedelta(days=history_days)).strftime("%Y-%m-%d")
    hist_end   = (as_of_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    raw_hist = yf.Ticker(ticker).history(start=hist_start, end=hist_end)
    if raw_hist.index.tz:
        raw_hist.index = raw_hist.index.tz_localize(None)
    price_history = raw_hist[raw_hist.index <= pd.Timestamp(as_of_date)]

    if price_history.empty:
        raise ValueError(f"[{ticker}] 価格データが取得できませんでした (as_of={as_of_date.date()})")

    # --- 1-B. マクロレジーム ---
    regime = get_macro_regime(as_of_date, config, ticker=ticker)

    # --- 1-C. ファンダメンタル・定性データ ---
    data = fetch_stock_data(ticker, as_of_date=as_of_date, price_history=price_history)
    company_name = data.get("company_name", data.get("name", ticker))

    # --- 1-D. テクニカル解析 ---
    ta = TechnicalAnalyzer(price_history)
    tech_data = data.get("technical", {})
    tech_data["perfect_order"] = ta.check_ma_alignment()

    # --- 1-E. スコアカード生成 ---
    buy_threshold = (
        config.get("signals", {})
              .get("BUY", {})
              .get("regime_overrides", {})
              .get(regime, {})
              .get("min_score", config.get("signals", {}).get("BUY", {}).get("min_score", 6.5))
    )
    
    # 実際にはマクロ環境からセクター重みを調整
    sector = data.get("sector", "")
    
    # 有報データ取得（日本株: EDINET, 米国株: SEC）
    yuho_data = {}
    if ticker.endswith('.T'):
        try:
            logger.info(f"EDINET 有報取得中...")
            yuho_data = extract_yuho_data(ticker)
        except Exception as e:
            logger.warning(f"有報取得エラー: {e}")
    elif HAS_SEC and is_us_stock(ticker):
        try:
            logger.info(f"SEC 10-K/10-Q 取得中...")
            yuho_data = extract_sec_data(ticker)
            if yuho_data and yuho_data.get('available'):
                logger.info("SEC データ取得成功")
            else:
                logger.warning("SEC データなし")
        except Exception as e:
            logger.warning(f"SEC 取得エラー: {e}")
            
    scorecard = generate_scorecard(
        data.get("metrics", {}),
        tech_data,
        yuho_data,
        sector=sector,
        macro_data={"regime": regime},
        buy_threshold=buy_threshold,
    )

    # --- 1-F. 適用ウェイト (レジーム別) ---
    regime_weights = (
        config.get("macro", {})
              .get("regime_weights", {})
              .get(regime, config.get("macro", {}).get("regime_weights", {}).get("NEUTRAL", {}))
    )
    if not regime_weights and scorecard.get("weights"):
        regime_weights = scorecard["weights"] # Generate Scorecard内で決定されたウェイトをフォールバックとして使用

    # --- 1-G. 有報サマリー (関数が存在する場合) ---
    yuho_summary = _get_yuho_summary(ticker, as_of_date, config, data, yuho_data)

    return PromptPayload(
        ticker=ticker,
        company_name=company_name,
        as_of_date=as_of_date,
        regime=regime,
        regime_weights=regime_weights,
        scorecard=scorecard,
        scorecard_text=_format_scorecard_text(scorecard),
        yuho_summary=yuho_summary,
        sector=sector,
        raw_metrics=data.get("metrics", {}),
    )


def _get_yuho_summary(ticker: str, as_of_date: datetime, config: dict, data: dict, yuho_data: dict) -> str:
    """
    有報フォーマット関数を動的に呼び出す。
    未実装 or 取得失敗の場合は空文字を返す（プロンプト生成は継続）。
    """
    try:
        return format_yuho_for_prompt(yuho_data)
    except Exception as e:
        logger.warning(f"有報フォーマットエラー ({ticker}): {e}")
        return data.get("yuho_summary", data.get("qualitative_summary", "（有報データ未取得または空）"))


def _format_scorecard_text(sc: dict) -> str:
    """scorecard dict → プロンプト貼り付け用テキスト"""
    fund  = sc.get("fundamental", {})
    val   = sc.get("valuation",   {})
    tech  = sc.get("technical",   {})
    qual  = sc.get("qualitative", {})

    lines = [
        f"  Fundamental  (地力)  : {fund.get('score', 'N/A'):>4} / 10",
        f"  Valuation  (割安度)  : {val.get('score',  'N/A'):>4} / 10",
        f"  Technical  (タイミング): {tech.get('score', 'N/A'):>4} / 10",
        f"  Qualitative (定性)   : {qual.get('score', 'N/A'):>4} / 10",
        f"  ─────────────────────────────",
        f"  総合スコア            : {sc.get('total_score', 'N/A'):>4} / 10",
        f"  シグナル              : 【{sc.get('signal', '---')}】",
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


# ---------------------------------------------------------------------------
# セクター別評価フレームのテキスト生成
# ---------------------------------------------------------------------------
_SECTOR_FRAMES = {
    "Financial Services": {
        "label": "金融サービス / 銀行・保険",
        "primary_metrics": [
            "NIM（純利ざや）: 金利環境とローン/預金スプレッドの趨勢",
            "CET1比率（普通株等Tier1）: 自己資本の充実度（バーゼルIII基準）",
            "信用コスト比率（貸倒引当金/貸出残高）: 景気サイクルとの連動性",
            "ROE vs 資本コスト（COE）スプレッド: 真の価値創造の有無",
            "PBR × ROE 効率性マトリクス: PBR1倍割れの正当性判断",
        ],
        "exclude_metrics": ["営業CF/純利益（銀行業務の性質上無意味）", "自己資本比率40%基準（バーゼル規制で別評価）"],
        "key_risks": ["信用サイクル転換", "金利逆転・NIM圧迫", "規制強化（追加資本要件）"],
    },
    "Financial": {
        "label": "金融サービス / 銀行・保険",
        "primary_metrics": [
            "NIM（純利ざや）: 金利環境とローン/預金スプレッドの趨勢",
            "CET1比率（普通株等Tier1）: 自己資本の充実度（バーゼルIII基準）",
            "信用コスト比率（貸倒引当金/貸出残高）: 景気サイクルとの連動性",
            "ROE vs 資本コスト（COE）スプレッド: 真の価値創造の有無",
            "PBR × ROE 効率性マトリクス: PBR1倍割れの正当性判断",
        ],
        "exclude_metrics": ["営業CF/純利益（銀行業務の性質上無意味）", "自己資本比率40%基準（バーゼル規制で別評価）"],
        "key_risks": ["信用サイクル転換", "金利逆転・NIM圧迫", "規制強化（追加資本要件）"],
    },
    "Energy": {
        "label": "エネルギー",
        "primary_metrics": [
            "EV/EBITDA: 設備投資の重さを反映するマルチプル",
            "フリーCFイールド（FCF/時価総額）: 還元余力の評価",
            "ブレークイーブン原油価格: 採算ライン vs 現在の商品価格",
            "埋蔵量交換率（Reserve Replacement Ratio）: 長期成長の担保",
        ],
        "exclude_metrics": [],
        "key_risks": ["商品価格の急落", "エネルギー転換リスク（座礁資産化）", "地政学リスク"],
    },
    "Technology": {
        "label": "テクノロジー（高成長）",
        "primary_metrics": [
            "PEG比率（PER / EPS成長率）: 成長を織り込んだバリュエーション",
            "Rule of 40（売上成長率 + 営業利益率 ≥ 40%）: 成長と収益のバランス",
            "R&D ROI推定: 研究開発投資の効率性",
            "TAM（対象市場規模）浸透率: 成長余地の定量化",
        ],
        "exclude_metrics": ["低PER基準（成長株には不適切）"],
        "key_risks": ["競合の急台頭・技術陳腐化", "金利上昇による割引率上昇", "規制リスク（独禁法）"],
    },
    "Communication Services": {
        "label": "コミュニケーション・サービス（高成長）",
        "primary_metrics": [
            "PEG比率（PER / EPS成長率）",
            "Rule of 40（売上成長率 + 営業利益率 ≥ 40%）",
            "ユーザー獲得コスト（CAC）vs 顧客生涯価値（LTV）",
            "ARR / MRR（サブスクリプション収益の安定性）",
        ],
        "exclude_metrics": [],
        "key_risks": ["ユーザー離脱・競合台頭", "広告収入の景気敏感性", "プラットフォーム規制"],
    },
    "Healthcare": {
        "label": "ヘルスケア",
        "primary_metrics": [
            "パイプライン価値（フェーズ別・成功確率調整済み）",
            "特許崖リスク（主要薬剤の特許期限）",
            "R&D投資対効果（成功確率×市場規模）",
            "規制承認リスク（FDA/PMDA審査状況）",
        ],
        "exclude_metrics": [],
        "key_risks": ["臨床試験失敗", "特許切れ・ジェネリック参入", "薬価規制強化"],
    },
}

_REGIME_WEIGHT_TABLE = {
    "RISK_ON":         {"Fundamental": "25%", "Valuation": "30%", "Technical": "25%", "Qualitative": "20%"},
    "NEUTRAL":         {"Fundamental": "30%", "Valuation": "25%", "Technical": "25%", "Qualitative": "20%"},
    "RISK_OFF":        {"Fundamental": "40%", "Valuation": "30%", "Technical": "15%", "Qualitative": "15%"},
    "RATE_HIKE":       {"Fundamental": "30%", "Valuation": "35%", "Technical": "20%", "Qualitative": "15%"},
    "RATE_CUT":        {"Fundamental": "20%", "Valuation": "25%", "Technical": "30%", "Qualitative": "25%"},
    "YIELD_INVERSION": {"Fundamental": "45%", "Valuation": "30%", "Technical": "10%", "Qualitative": "15%"},
    "CRISIS":          {"Fundamental": "50%", "Valuation": "15%", "Technical": "10%", "Qualitative": "25%"},
    "BOJ_HIKE":        {"Fundamental": "35%", "Valuation": "25%", "Technical": "25%", "Qualitative": "15%"},
    "YEN_WEAK":        {"Fundamental": "25%", "Valuation": "25%", "Technical": "30%", "Qualitative": "20%"},
    "YEN_STRONG":      {"Fundamental": "30%", "Valuation": "30%", "Technical": "20%", "Qualitative": "20%"},
    "NIKKEI_BULL":     {"Fundamental": "25%", "Valuation": "25%", "Technical": "30%", "Qualitative": "20%"},
}

_CONFIDENCE_MATRIX = """\
  ┌──────────────┬────────────────────┬──────────────────────┐
  │ データ品質   │ シグナル方向       │ 確信度レベル         │
  ├──────────────┼────────────────────┼──────────────────────┤
  │ 有報あり     │ ファンダ・定性一致 │ HIGH   (0.75+)       │
  │ 有報あり     │ ファンダ・定性乖離 │ MED    (0.55-0.74)   │
  │ 有報なし推定 │ ファンダ・テク一致 │ LOW    (0.40-0.54)   │
  │ 有報なし推定 │ シグナル分岐       │ VERY LOW (0.40-)     │
  └──────────────┴────────────────────┴──────────────────────┘"""


def _build_sector_frame_text(sector: str) -> str:
    """セクター別評価フレームの注記テキストを生成する。"""
    frame = _SECTOR_FRAMES.get(sector)
    if not frame:
        return ""
    lines = [
        f"【セクター別評価フレーム: {frame['label']}】",
        "  重点評価指標:",
    ]
    for m in frame["primary_metrics"]:
        lines.append(f"    ・{m}")
    if frame.get("exclude_metrics"):
        lines.append("  ※ 以下の汎用指標はこのセクターでは除外または参考程度:")
        for m in frame["exclude_metrics"]:
            lines.append(f"    ✗ {m}")
    if frame.get("key_risks"):
        lines.append(f"  固有リスク: {' / '.join(frame['key_risks'])}")
    return "\n".join(lines)


def _build_regime_weight_table(current_regime: str, current_weights: dict) -> str:
    """全レジームのウェイト比較表を生成し、現在のレジームをハイライト。"""
    w = current_weights if isinstance(current_weights, dict) else {}
    lines = [
        "【レジーム別ウェイト（参考）】",
        f"  ※ 現在のレジーム: 【{current_regime}】 ← 適用中",
        "  ┌─────────────────┬──────┬──────┬──────┬──────┐",
        "  │ レジーム        │ Fund │  Val │ Tech │ Qual │",
        "  ├─────────────────┼──────┼──────┼──────┼──────┤",
    ]
    for regime, weights in _REGIME_WEIGHT_TABLE.items():
        marker = " ◀" if regime == current_regime else "  "
        lines.append(
            f"  │ {regime:<15} │ {weights['Fundamental']:>4} │ {weights['Valuation']:>4} │"
            f" {weights['Technical']:>4} │ {weights['Qualitative']:>4} │{marker}"
        )
    lines.append("  └─────────────────┴──────┴──────┴──────┴──────┘")
    # 実際に適用されたウェイト（マクロ補正後）
    if w:
        applied = (
            f"  適用値（補正後）: "
            f"Fund {w.get('fundamental', 0):.0%} / "
            f"Val {w.get('valuation', 0):.0%} / "
            f"Tech {w.get('technical', 0):.0%} / "
            f"Qual {w.get('qualitative', 0):.0%}"
        )
        lines.append(applied)
    return "\n".join(lines)


def _build_confidence_block(confidence_level: str, confidence_score: float,
                             has_yuho: bool, is_estimated: bool) -> str:
    """確信度ブロックのテキストを生成する。"""
    level_emoji = {"HIGH": "🟢", "MED": "🟡", "LOW": "🟠", "VERY_LOW": "🔴"}.get(confidence_level, "⚪")
    data_status = "有報取得済み" if has_yuho else ("定量推定値" if is_estimated else "データなし")
    return (
        f"{level_emoji} 確信度: {confidence_level} ({confidence_score:.2f})  "
        f"| データ品質: {data_status}"
    )


# ---------------------------------------------------------------------------
# Step 2: プロンプト文字列の生成
# ---------------------------------------------------------------------------
PROMPT_TEMPLATE = """\
あなたはシニア・エクイティ・アナリストです。
以下の個別銘柄データセットに基づき、Investment Thesis を策定してください。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 基本情報・マクロ環境
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
銘柄名 / コード  : {company_name} ({ticker})
分析基準日       : {as_of_date}
市場レジーム     : {regime}
適用ウェイト     :
  Fundamental  : {w_fund:.0%}
  Valuation    : {w_val:.0%}
  Technical    : {w_tech:.0%}
  Qualitative  : {w_qual:.0%}{qualitative_note}

{regime_weight_table}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. スコアカード概要 (10点満点)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{scorecard_text}

確信度: {confidence_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. セクター別評価フレーム
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sector_frame_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. 定性データ・有価証券報告書要約
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{yuho_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. 分析タスク
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
以下の3点について詳細に論じてください。

(1) スコアの背後にある定性・定量の整合性判定
    数値上のファンダメンタルズ/バリュエーションと、有報が示す
    「経営リスク」「競争優位性」に矛盾はないか。
    「地力」と「定性」スコアの乖離がある場合、その要因を推測せよ。
    ※ 有報未取得の場合は、上記「セクター別評価フレーム」の重点指標で
      補完分析を行い、推定根拠と不確実性を明示すること。

(2) 市場レジーム ({regime}) に対する脆弱性と機会
    現在のマクロ環境（金利・為替・地政学リスク等）が
    このビジネスモデルにプラス/マイナスどちらに働くか。
    テクニカル指標との乖離から読み取れる変化はないか。

(3) 主要なアップサイド・ダウンサイドシナリオ（向こう12ヶ月）
    株価を動かす最大のカタリストは何か。
    投資を回避・ポジション縮小すべき最優先リスクは何か。

━━━━━━━━━━━━━━━━━━━━━━━━━
6. 出力形式
━━━━━━━━━━━━━━━━━━━━━━━━━
■ コア・ピッチ（200文字以内）
  投資すべきか否かの結論と核心的理由。

■ 深掘り分析（各項目 300〜500文字程度）
  上記タスク (1)(2)(3) の論述。

■ 目標価格（3手法トライアンギュレーション）
  以下3手法の加重平均で算出し、各前提を明示すること。
  ・手法A – DCF（WACC・永続成長率を明示、重み40%）
  ・手法B – 業界比較マルチプル（Peer median PER or EV/EBITDA、重み40%）
  ・手法C – 52週高値/安値レンジ中央値（重み20%）

  出力形式:
    ベア目標  : <価格>（DCF悲観 / Peer下位25%）
    ベース目標: <価格>（加重平均）
    ブル目標  : <価格>（DCF楽観 / Peer上位25%）
    乖離率    : 現在株価比 +/-XX%

■ エントリー・出口戦略
  ストップロス : entry_price − (ATR14 × 2.0)
    ※ ATR14 が不明な場合は 52週ボラティリティ(σ)から推定
  利確目標    : 直近レジスタンス（BB上限 or 52週高値）の −3%
    または Reward/Risk = 最低2.0 を確保できる水準

■ 最終レーティング
  [強く推奨 / 推奨 / 中立 / 回避] と根拠一文。

■ 確信度マトリクス（出力例）
{confidence_matrix}
  今回の評価: データ品質={data_quality} / シグナル方向={signal_alignment}
  → 確信度: {confidence_level} ({confidence_score:.2f})
"""


def build_prompt(payload: PromptPayload) -> str:
    """
    PromptPayload → LLM に貼り付けるプロンプト文字列を返す。
    """
    w = payload.regime_weights
    w_fund = w.get("fundamental", 0.3) if isinstance(w, dict) else 0.3
    w_val  = w.get("valuation",   0.25) if isinstance(w, dict) else 0.25
    w_tech = w.get("technical",   0.25) if isinstance(w, dict) else 0.25
    w_qual = w.get("qualitative", 0.20) if isinstance(w, dict) else 0.20

    sc = payload.scorecard
    qual = sc.get("qualitative", {})
    has_yuho  = bool(sc.get("fundamental", {}).get("data_points", 0) > 0 and
                     not qual.get("estimated"))
    is_estimated = bool(qual.get("estimated"))
    confidence_level = sc.get("confidence_level", "VERY_LOW")
    confidence_score = sc.get("confidence_score", 0.38)

    qualitative_note = ""
    if is_estimated:
        qualitative_note = "\n  ⚠️ Qualitative は有報未取得のため定量データから推定（確信度 LOW）"

    regime_weight_table = _build_regime_weight_table(payload.regime, w)
    sector_frame_text = _build_sector_frame_text(payload.sector)
    if not sector_frame_text:
        sector_frame_text = f"（セクター: {payload.sector or '不明'} — 汎用フレームで評価）"

    confidence_block = _build_confidence_block(
        confidence_level, confidence_score, has_yuho, is_estimated
    )

    data_quality    = "有報取得済み" if has_yuho else ("定量推定値" if is_estimated else "データなし")
    fund_score = sc.get("fundamental", {}).get("score", 5.0)
    tech_score = sc.get("technical",   {}).get("score", 5.0)
    signal_alignment = "一致" if (fund_score >= 5.5) == (tech_score >= 5.5) else "分岐"

    return PROMPT_TEMPLATE.format(
        company_name        = payload.company_name,
        ticker              = payload.ticker,
        as_of_date          = payload.as_of_date.strftime("%Y-%m-%d"),
        regime              = payload.regime,
        w_fund              = w_fund,
        w_val               = w_val,
        w_tech              = w_tech,
        w_qual              = w_qual,
        qualitative_note    = qualitative_note,
        regime_weight_table = regime_weight_table,
        scorecard_text      = payload.scorecard_text,
        confidence_block    = confidence_block,
        sector_frame_text   = sector_frame_text,
        yuho_summary        = payload.yuho_summary or "（有報データ未取得 — セクターフレームに基づき補完分析を実施）",
        confidence_matrix   = _CONFIDENCE_MATRIX,
        data_quality        = data_quality,
        signal_alignment    = signal_alignment,
        confidence_level    = confidence_level,
        confidence_score    = confidence_score,
    )


# ---------------------------------------------------------------------------
# Step 3: API 直接呼び出し（オプション）
# ---------------------------------------------------------------------------
def call_llm_api(
    prompt: str,
    provider: str = "gemini",
    model: str = "gemini-2.0-flash",
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> str:
    """
    プロンプトを LLM API に送信し、レスポンステキストを返す。
    provider: "anthropic" | "openai" | "gemini" | "groq"
    """
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    elif provider == "openai":
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model=model or "gpt-4o",
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    elif provider == "gemini":
        import google.generativeai as genai
        import os
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        m = genai.GenerativeModel(model or "gemini-2.0-flash")
        response = m.generate_content(
            prompt,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        return response.text
        
    elif provider == "groq":
        from groq import Groq
        import os
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model or "llama3-70b-8192",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    else:
        raise ValueError(f"未対応の provider: {provider}")


# ---------------------------------------------------------------------------
# メインエントリーポイント
# ---------------------------------------------------------------------------
def analyze(
    ticker: str,
    as_of_date: Optional[datetime] = None,
    auto_call_api: bool = False,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    save_prompt: bool = True,
) -> dict:
    """
    ワンコール完結の分析実行関数。

    Parameters
    ----------
    ticker        : 銘柄コード
    as_of_date    : 分析基準日 (None = 今日)
    auto_call_api : True にすると LLM API を自動呼び出し
    provider      : 省略時は config.json (ai_engine) の設定に従う
    model         : 省略時は config.json (ai_engine) の設定に従う
    save_prompt   : True にするとプロンプトを .txt で保存
    """
    logger.info(f"[{ticker}] データ収集開始 ...")
    
    # Provider と Model の動的解決
    config = load_config_with_overrides(ticker)
    ai_engine = config.get("ai_engine", {})
    
    if not provider:
        provider = ai_engine.get("primary", "gemini")
    if not model:
        if provider == ai_engine.get("primary"):
            model = ai_engine.get("primary_model", "gemini-2.0-flash")
        elif provider == ai_engine.get("fallback"):
            model = ai_engine.get("fallback_model", "llama3-70b-8192")
        elif provider == "openai":
            model = "gpt-4o"
        elif provider == "anthropic":
            model = "claude-3-opus-20240229"
            
    temperature = ai_engine.get("temperature", 0.2)
    
    payload = collect_prompt_data(ticker, as_of_date)
    prompt  = build_prompt(payload)

    if save_prompt:
        date_str  = payload.as_of_date.strftime("%Y%m%d")
        file_path = f"prompt_{ticker.replace('.', '_')}_{date_str}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        logger.info(f"プロンプト保存: {file_path}")

    llm_output = None
    if auto_call_api:
        logger.info(f"LLM API 呼び出し中 (provider={provider}, model={model}) ...")
        try:
            llm_output = call_llm_api(prompt, provider=provider, model=model, temperature=temperature)
            logger.info("LLM レスポンス受信完了")
        except Exception as e:
            logger.error(f"API 呼び出しエラー: {e}")
            logger.info("Fallback engine の使用を試みます...")
            fallback_provider = ai_engine.get("fallback")
            fallback_model = ai_engine.get("fallback_model")
            if fallback_provider and fallback_provider != provider:
                try:
                    llm_output = call_llm_api(prompt, provider=fallback_provider, model=fallback_model, temperature=temperature)
                    logger.info("Fallback LLM レスポンス受信完了")
                except Exception as fallback_e:
                    logger.error(f"Fallback API 呼び出しエラー: {fallback_e}")

    return {
        "prompt"    : prompt,
        "payload"   : payload,
        "llm_output": llm_output,
    }


# ---------------------------------------------------------------------------
# CLI 実行
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="CIO Prototype — LLM 分析プロンプト生成")
    parser.add_argument("ticker",     help="銘柄コード (例: 7203.T)")
    parser.add_argument("--date",     help="分析基準日 YYYY-MM-DD (省略時: 今日)", default=None)
    parser.add_argument("--api",      help="LLM API を自動呼び出す", action="store_true")
    parser.add_argument("--provider", help="LLM プロバイダ",          default=None)
    parser.add_argument("--model",    help="モデル名",                 default=None)
    parser.add_argument("--no-save",  help="プロンプトのテキスト書き出しをスキップ", action="store_true")
    args = parser.parse_args()

    as_of = datetime.strptime(args.date, "%Y-%m-%d") if args.date else None

    result = analyze(
        ticker        = args.ticker,
        as_of_date    = as_of,
        auto_call_api = args.api,
        provider      = args.provider,
        model         = args.model,
        save_prompt   = not args.no_save,
    )

    if result["llm_output"]:
        print("\n" + "="*60)
        print(result["llm_output"])
    else:
        print("\n--- 生成プロンプト (プレビュー) ---")
        print(result["prompt"][:800], "...\n[以降省略]")
