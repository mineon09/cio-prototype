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
    
    # 有報データ取得
    yuho_data = {}
    if ticker.endswith('.T'):
        try:
            yuho_data = extract_yuho_data(ticker)
        except Exception as e:
            logger.warning(f"有報取得エラー: {e}")
            
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
  Qualitative  : {w_qual:.0%}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. スコアカード概要 (10点満点)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{scorecard_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. 定性データ・有価証券報告書要約
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{yuho_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. 分析タスク
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
以下の3点について詳細に論じてください。

(1) スコアの背後にある定性・定量の整合性判定
    数値上のファンダメンタルズ/バリュエーションと、有報が示す
    「経営リスク」「競争優位性」に矛盾はないか。
    「地力」と「定性」スコアの乖離がある場合、その要因を推測せよ。

(2) 市場レジーム ({regime}) に対する脆弱性と機会
    現在のマクロ環境（金利・為替・地政学リスク等）が
    このビジネスモデルにプラス/マイナスどちらに働くか。
    テクニカル指標との乖離から読み取れる変化はないか。

(3) 主要なアップサイド・ダウンサイドシナリオ（向こう12ヶ月）
    株価を動かす最大のカタリストは何か。
    投資を回避・ポジション縮小すべき最優先リスクは何か。

━━━━━━━━━━━━━━━━━━━━━━━━━
5. 出力形式
━━━━━━━━━━━━━━━━━━━━━━━━━
■ コア・ピッチ（200文字以内）
  投資すべきか否かの結論と核心的理由。

■ 深掘り分析（各項目 300〜500文字程度）
  上記タスク (1)(2)(3) の論述。

■ 最終レーティング
  [強く推奨 / 推奨 / 中立 / 回避] と目標レンジの方向感。
"""


def build_prompt(payload: PromptPayload) -> str:
    """
    PromptPayload → LLM に貼り付けるプロンプト文字列を返す。
    """
    w = payload.regime_weights
    w_fund = w.get("fundamental", 0.3) if isinstance(w, dict) else 0.3
    w_val = w.get("valuation", 0.25) if isinstance(w, dict) else 0.25
    w_tech = w.get("technical", 0.25) if isinstance(w, dict) else 0.25
    w_qual = w.get("qualitative", 0.20) if isinstance(w, dict) else 0.20
    
    return PROMPT_TEMPLATE.format(
        company_name  = payload.company_name,
        ticker        = payload.ticker,
        as_of_date    = payload.as_of_date.strftime("%Y-%m-%d"),
        regime        = payload.regime,
        w_fund        = w_fund,
        w_val         = w_val,
        w_tech        = w_tech,
        w_qual        = w_qual,
        scorecard_text = payload.scorecard_text,
        yuho_summary  = payload.yuho_summary,
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
