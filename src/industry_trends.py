"""
industry_trends.py - 業界動向・セクター分析モジュール
===================================================
Gemini 検索機能を使用して、
銘柄の所属するセクターの業界動向、トレンド、リスクを分析する。
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict

try:
    from .data_fetcher import call_groq
except ImportError:
    from data_fetcher import call_groq


# セクター定義
SECTOR_MAPPING = {
    "Technology": {
        "name_jp": "テクノロジー",
        "keywords": ["半導体", "ソフトウェア", "ハードウェア", "AI", "クラウド", "サイバーセキュリティ"],
        "key_metrics": ["R&D 投資率", "売上成長率", "グロスマージン", "ARR"],
    },
    "Healthcare": {
        "name_jp": "ヘルスケア",
        "keywords": ["医薬品", "バイオテクノロジー", "医療機器", "デジタルヘルス", "治験"],
        "key_metrics": ["パイプライン", "特許切れリスク", "規制承認", "保険収載"],
    },
    "Financial Services": {
        "name_jp": "金融",
        "keywords": ["銀行", "保険", "資産運用", "フィンテック", "決済"],
        "key_metrics": ["NIM", "BIS 自己資本比率", "ROE", "不良債権比率"],
    },
    "Consumer Cyclical": {
        "name_jp": "景気循環消費",
        "keywords": ["小売", "自動車", " luxury", "旅行", "エンターテインメント"],
        "key_metrics": ["同店売上高", "顧客単価", "在庫回転率"],
    },
    "Consumer Defensive": {
        "name_jp": "生活必需消費",
        "keywords": ["食品", "飲料", "日用品", "タバコ", "家庭用品"],
        "key_metrics": ["価格転嫁率", "ブランド力", "_distribution", "コスト削減"],
    },
    "Industrials": {
        "name_jp": "産業",
        "keywords": ["航空宇宙", "防衛", "建設機械", "物流", "エンジニアリング"],
        "key_metrics": ["受注残高", "オペレーティングマージン", "フリーキャッシュフロー"],
    },
    "Energy": {
        "name_jp": "エネルギー",
        "keywords": ["石油", "ガス", "再生可能エネルギー", "太陽光", "風力"],
        "key_metrics": ["生産量", "埋蔵量", "ブレイクイーブン価格"],
    },
    "Basic Materials": {
        "name_jp": "素材",
        "keywords": ["化学", "鉄鋼", "非鉄金属", "鉱業", "紙パルプ"],
        "key_metrics": ["商品価格", "生産コスト", "キャパシティ利用率"],
    },
    "Real Estate": {
        "name_jp": "不動産",
        "keywords": ["REIT", "商業用不動産", "住宅", "物流施設"],
        "key_metrics": ["NOI", "稼働率", "FFO", "利回り"],
    },
    "Communication Services": {
        "name_jp": "コミュニケーションサービス",
        "keywords": ["通信", "メディア", "広告", "ゲーム", "SNS"],
        "key_metrics": ["ユーザー数", "ARPU", "解約率", "広告単価"],
    },
    "Utilities": {
        "name_jp": "公益事業",
        "keywords": ["電力", "ガス", "水道"],
        "key_metrics": ["規制料金", "発電量", "配当利回り"],
    },
}


def fetch_industry_overview(sector: str, company_name: str = None, ticker: str = None) -> Dict:
    """
    業界概要を Gemini 検索で取得
    
    Parameters
    ----------
    sector       : セクター名（英語）
    company_name : 会社名（オプション）
    ticker       : 銘柄コード（オプション）
    
    Returns
    -------
    業界概要データ
    """
    sector_info = SECTOR_MAPPING.get(sector, {})
    sector_name_jp = sector_info.get("name_jp", sector)
    keywords = sector_info.get("keywords", [])
    
    company_context = ""
    if company_name:
        company_context = f"特に {company_name}"
    if ticker:
        company_context += f" ({ticker})"
    
    prompt = f"""
You are an industry analyst specializing in {sector_name_jp} sector.
Provide a comprehensive industry overview for investment analysis.

{company_context} is operating in this sector.

【Required Analysis】
1. Industry Growth Rate (CAGR forecast for next 3-5 years)
2. Key Growth Drivers (top 3-5 trends)
3. Major Risks/Headwinds (top 3-5 concerns)
4. Competitive Landscape (consolidation, new entrants, disruption)
5. Regulatory Environment (pending changes, geopolitical factors)
6. Technology Trends (disruptive technologies, R&D focus areas)
7. Valuation Context (sector PE vs historical, vs market)

【Output Format】
Return a JSON object with the following structure:
{{
  "sector_name_jp": "日本語セクター名",
  "sector_name_en": "{sector}",
  "growth_rate_cagr": "数値（%）または範囲（例：「8-12%」）",
  "growth_drivers": [
    {{"driver": "要因名", "impact": "high/medium/low", "description": "説明（日本語）"}}
  ],
  "risks": [
    {{"risk": "リスク名", "impact": "high/medium/low", "description": "説明（日本語）"}}
  ],
  "competitive_landscape": "競争環境の説明（日本語 200 文字）",
  "regulatory_environment": "規制環境の説明（日本語 150 文字）",
  "technology_trends": ["トレンド 1", "トレンド 2", "トレンド 3"],
  "valuation_context": "バリュエーション状況（日本語 100 文字）",
  "outlook": "業界展望（日本語 200 文字）"
}}

Use recent data from the past 3 months. Output in Japanese.
"""
    
    try:
        print(f"  🌐 {sector_name_jp} 業界の動向を調査中...")
        result, model = call_groq(prompt, parse_json=True)
        
        if isinstance(result, dict):
            return {
                "available": True,
                **result,
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        else:
            return {"available": False, "error": "Invalid response format"}
    except Exception as e:
        print(f"  ⚠️ 業界動向取得エラー：{e}")
        return {"available": False, "error": str(e)}


def fetch_peer_comparison(ticker: str, sector: str, peers: List[str] = None) -> Dict:
    """
    同業他社との比較分析を生成
    
    Parameters
    ----------
    ticker : 対象銘柄
    sector : セクター
    peers  : 競合他社リスト（オプション）
    
    Returns
    -------
    比較分析データ
    """
    sector_info = SECTOR_MAPPING.get(sector, {})
    sector_name_jp = sector_info.get("name_jp", sector)
    
    peers_context = ""
    if peers and len(peers) > 0:
        peers_context = f"特に以下の競合他社と比較：{', '.join(peers[:5])}"
    
    prompt = f"""
You are an equity research analyst.
Compare {ticker} with its peers in the {sector_name_jp} sector.

{peers_context}

【Comparison Axes】
1. Valuation (P/E, P/B, EV/EBITDA vs peers)
2. Profitability (ROE, Operating Margin, FCF Margin vs peers)
3. Growth (Revenue CAGR, EPS CAGR vs peers)
4. Financial Health (Debt/Equity, Interest Coverage vs peers)

【Output Format】
Return a JSON object:
{{
  "valuation_vs_peers": "higher/lower/inline",
  "valuation_commentary": "バリュエーション比較（日本語 100 文字）",
  "profitability_vs_peers": "superior/average/inferior",
  "profitability_commentary": "収益性比較（日本語 100 文字）",
  "growth_vs_peers": "faster/inline/slower",
  "growth_commentary": "成長性比較（日本語 100 文字）",
  "financial_health_vs_peers": "stronger/average/weaker",
  "financial_health_commentary": "財務健全性比較（日本語 100 文字）",
  "competitive_positioning": "総合的な競争ポジション（日本語 150 文字）",
  "key_differentiators": ["差別化要因 1", "差別化要因 2"]
}}

Output in Japanese.
"""
    
    try:
        result, _ = call_groq(prompt, parse_json=True)
        
        if isinstance(result, dict):
            return {
                "available": True,
                **result,
            }
        else:
            return {"available": False}
    except Exception as e:
        print(f"  ⚠️ 競合比較エラー：{e}")
        return {"available": False, "error": str(e)}


def _validate_and_fix_catalysts(catalysts: list, reference_date: datetime = None) -> list:
    """
    カタリストの日付バリデーションと自動修正

    過去日付のカタリストを検出し除外する。
    """
    import re

    if reference_date is None:
        reference_date = datetime.now()

    current_year = reference_date.year
    current_quarter_num = (reference_date.month - 1) // 3 + 1

    validated = []
    for cat in catalysts:
        timing = (
            cat.get("expected_date", "")
            or cat.get("expected_timing", "")
            or cat.get("timing", "")
            or cat.get("date", "")
        )
        year_match = re.search(r"(20\d{2})", str(timing))
        if year_match:
            year = int(year_match.group(1))
            if year < current_year:
                print(
                    f"  ⚠️ 過去カタリストを除外: {timing} → {str(cat.get('event', ''))[:30]}"
                )
                continue
            if year == current_year:
                q_match = re.search(r"Q(\d)", str(timing), re.IGNORECASE)
                if q_match and int(q_match.group(1)) < current_quarter_num:
                    print(f"  ⚠️ 過去四半期カタリストを除外: {timing}")
                    continue
        validated.append(cat)
    return validated


def fetch_catalyst_calendar(ticker: str, company_name: str = None) -> Dict:
    """
    今後のカタリスト（予定）を収集
    
    Parameters
    ----------
    ticker       : 銘柄コード
    company_name : 会社名
    
    Returns
    -------
    カタリストカレンダー
    """
    name = company_name or ticker
    today = datetime.now()
    current_year = today.year
    current_quarter = f"{current_year}Q{(today.month - 1) // 3 + 1}"
    next_quarter_num = (today.month - 1) // 3 + 2
    next_quarter = (
        f"{current_year}Q{next_quarter_num}"
        if next_quarter_num <= 4
        else f"{current_year + 1}Q1"
    )

    prompt = f"""
Today's date: {today.strftime('%Y-%m-%d')}
Current quarter: {current_quarter}

CRITICAL TEMPORAL CONSTRAINTS:
- You are writing for an investor reading this on {today.strftime('%Y-%m-%d')}.
- All dates you output MUST be {current_year} or later. NEVER output any date before {today.strftime('%Y-%m-%d')}.
- Use {current_quarter} as the current quarter, {next_quarter} as the next quarter.
- If a specific date is uncertain, use "{current_year}H1" or "{current_year}H2" or "{current_year + 1}" rather than guessing a past date.

You are an investment research assistant.
Identify upcoming catalysts for {name} ({ticker}).

【Catalyst Types to Consider】
- Earnings announcements (next 2-3 quarters)
- Product launches / updates
- Regulatory decisions (FDA approvals, etc.)
- Investor days / analyst meetings
- Contract announcements
- M&A possibilities
- Index rebalancing
- Lock-up expirations

【Output Format】
Return a JSON array of upcoming catalysts:
[
  {{
    "event": "イベント名（日本語）",
    "expected_date": "YYYY-MM-DD または YYYY-Q# または「未定」",
    "type": "earnings/product/regulatory/other",
    "importance": "high/medium/low",
    "description": "説明（日本語 100 文字）",
    "potential_impact": "positive/negative/mixed"
  }}
]

Focus on the next 12 months from today ({today.strftime('%Y-%m-%d')}). Output in Japanese.
If specific dates are unknown, provide estimates based on historical patterns but always use {current_year} or {current_year + 1}.
"""
    
    try:
        result, _ = call_groq(prompt, parse_json=True)
        
        if isinstance(result, list):
            validated = _validate_and_fix_catalysts(result)
            return {
                "available": True,
                "catalysts": validated[:5],  # 最大 5 件
            }
        elif isinstance(result, dict) and "catalysts" in result:
            validated = _validate_and_fix_catalysts(result["catalysts"])
            return {
                "available": True,
                "catalysts": validated[:5],
            }
        else:
            return {"available": False}
    except Exception as e:
        print(f"  ⚠️ カタリスト取得エラー：{e}")
        return {"available": False, "error": str(e)}


def fetch_all_industry_data(
    ticker: str,
    sector: str,
    company_name: str = None,
    peers: List[str] = None
) -> Dict:
    """
    全ての業界データを1回の Gemini 呼び出しで収集する。
    （旧実装: 3回 → 新実装: 1回、精度維持のため1プロンプトに統合）

    Parameters
    ----------
    ticker       : 銘柄コード
    sector       : セクター
    company_name : 会社名
    peers        : 競合他社リスト
    """
    print(f"  🏭 {sector} 業界の分析を開始...")

    sector_info = SECTOR_MAPPING.get(sector, {})
    sector_name_jp = sector_info.get("name_jp", sector)
    name = company_name or ticker
    peers_context = f"特に以下の競合他社と比較：{', '.join(peers[:5])}" if peers else ""

    today = datetime.now()
    current_year = today.year
    current_quarter = f"{current_year}Q{(today.month - 1) // 3 + 1}"
    next_quarter_num = (today.month - 1) // 3 + 2
    next_quarter = (
        f"{current_year}Q{next_quarter_num}"
        if next_quarter_num <= 4
        else f"{current_year + 1}Q1"
    )

    # ── 3つのプロンプトを1つに統合（use_search=True で最新情報を取得） ──
    prompt = f"""
Today's date: {today.strftime('%Y-%m-%d')}
Current quarter: {current_quarter}

CRITICAL TEMPORAL CONSTRAINTS (strictly enforced):
- You are writing for an investor reading this on {today.strftime('%Y-%m-%d')}.
- All future events in "catalysts" MUST be dated {current_year} or later.
- NEVER output any catalyst date before {today.strftime('%Y-%m-%d')}.
- Use {current_quarter} as the current quarter, {next_quarter} as the next quarter.
- If a specific date is uncertain, use "{current_year}H1", "{current_year}H2", or "{current_year + 1}" instead of guessing a past date.

You are a senior investment analyst. Analyze {name} ({ticker}) and its industry ({sector_name_jp}).
Use the latest available data (past 3 months) via search.

{peers_context}

Return a SINGLE JSON object with the following three sections:

{{
  "overview": {{
    "sector_name_jp": "日本語セクター名",
    "sector_name_en": "{sector}",
    "growth_rate_cagr": "数値（%）または範囲（例：「8-12%」）",
    "growth_drivers": [
      {{"driver": "要因名", "impact": "high/medium/low", "description": "説明（日本語）"}}
    ],
    "risks": [
      {{"risk": "リスク名", "impact": "high/medium/low", "description": "説明（日本語）"}}
    ],
    "competitive_landscape": "競争環境の説明（日本語 200 文字）",
    "regulatory_environment": "規制環境の説明（日本語 150 文字）",
    "technology_trends": ["トレンド 1", "トレンド 2", "トレンド 3"],
    "valuation_context": "バリュエーション状況（日本語 100 文字）",
    "outlook": "業界展望（日本語 200 文字）"
  }},
  "peer_comparison": {{
    "valuation_vs_peers": "higher/lower/inline",
    "valuation_commentary": "バリュエーション比較（日本語 100 文字）",
    "profitability_vs_peers": "superior/average/inferior",
    "profitability_commentary": "収益性比較（日本語 100 文字）",
    "growth_vs_peers": "faster/inline/slower",
    "growth_commentary": "成長性比較（日本語 100 文字）",
    "financial_health_vs_peers": "stronger/average/weaker",
    "financial_health_commentary": "財務健全性比較（日本語 100 文字）",
    "competitive_positioning": "総合的な競争ポジション（日本語 150 文字）",
    "key_differentiators": ["差別化要因 1", "差別化要因 2"]
  }},
  "catalysts": [
    {{
      "event": "イベント名（日本語）",
      "expected_date": "YYYY-MM-DD または YYYY-Q# または「未定」",
      "type": "earnings/product/regulatory/other",
      "importance": "high/medium/low",
      "description": "説明（日本語 100 文字）",
      "potential_impact": "positive/negative/mixed"
    }}
  ]
}}

Rules:
- growth_drivers: top 3-5 items
- risks: top 3-5 items
- catalysts: next 12 months from {today.strftime('%Y-%m-%d')}, up to 5 items, ALL dated {current_year} or {current_year + 1}
- All text fields must be in Japanese
- Output ONLY valid JSON. No markdown, no explanation.
"""

    try:
        print(f"  🌐 {sector_name_jp} 業界の動向を調査中... (Groq 統合1回)")
        result, model = call_groq(prompt, parse_json=True)

        if not isinstance(result, dict):
            raise ValueError(f"期待するdictではありません: {type(result)}")

        # 各サブセクションを既存の戻り値形式に合わせて組み立て
        overview_raw = result.get("overview", {})
        peer_raw = result.get("peer_comparison", {})
        catalysts_raw = result.get("catalysts", [])

        overview = {"available": bool(overview_raw), **overview_raw,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        peer_comparison = {"available": bool(peer_raw), **peer_raw}
        catalysts_list = _validate_and_fix_catalysts(
            catalysts_raw if isinstance(catalysts_raw, list) else []
        )
        catalysts = {"available": bool(catalysts_list), "catalysts": catalysts_list[:5]}

        return {
            "available": True,
            "overview": overview,
            "peer_comparison": peer_comparison,
            "catalysts": catalysts,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    except Exception as e:
        print(f"  ⚠️ 業界動向（統合）取得エラー: {e} → 個別取得にフォールバック")
        # フォールバック：個別取得（Groq）
        overview = fetch_industry_overview(sector, company_name, ticker)
        peer_comparison = fetch_peer_comparison(ticker, sector, peers)
        catalysts = fetch_catalyst_calendar(ticker, company_name)
        return {
            "available": True,
            "overview": overview,
            "peer_comparison": peer_comparison,
            "catalysts": catalysts,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def format_industry_for_prompt(industry_data: Dict) -> str:
    """
    業界データをプロンプト用テキストに整形
    
    Parameters
    ----------
    industry_data : fetch_all_industry_data の戻り値
    
    Returns
    -------
    整形済みテキスト
    """
    if not industry_data or not industry_data.get("available"):
        return "（業界データ未取得）"
    
    lines = []
    
    # 業界概要
    overview = industry_data.get("overview", {})
    if overview.get("available"):
        lines.append(f"【業界：{overview.get('sector_name_jp', overview.get('sector_name_en', 'Unknown'))}】")
        
        cagr = overview.get("growth_rate_cagr")
        if cagr:
            lines.append(f"  予想成長率（CAGR）: {cagr}")
        
        drivers = overview.get("growth_drivers", [])
        if drivers:
            lines.append(f"  成長ドライバー:")
            for d in drivers[:3]:
                impact = d.get("impact", "")
                impact_mark = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(impact, "")
                lines.append(f"    {impact_mark} {d.get('driver', '')}")
        
        risks = overview.get("risks", [])
        if risks:
            lines.append(f"  主要リスク:")
            for r in risks[:3]:
                impact = r.get("impact", "")
                impact_mark = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(impact, "")
                lines.append(f"    {impact_mark} {r.get('risk', '')}")
        
        outlook = overview.get("outlook", "")
        if outlook:
            lines.append(f"  業界展望：{outlook}")
    
    # 競合比較
    peer_comp = industry_data.get("peer_comparison", {})
    if peer_comp.get("available"):
        lines.append(f"\n【競合比較】")
        
        val_vs = peer_comp.get("valuation_vs_peers", "")
        val_comment = peer_comp.get("valuation_commentary", "")
        if val_comment:
            lines.append(f"  バリュエーション：{val_vs} - {val_comment}")
        
        prof_vs = peer_comp.get("profitability_vs_peers", "")
        prof_comment = peer_comp.get("profitability_commentary", "")
        if prof_comment:
            lines.append(f"  収益性：{prof_vs} - {prof_comment}")
        
        growth_vs = peer_comp.get("growth_vs_peers", "")
        growth_comment = peer_comp.get("growth_commentary", "")
        if growth_comment:
            lines.append(f"  成長性：{growth_vs} - {growth_comment}")
        
        positioning = peer_comp.get("competitive_positioning", "")
        if positioning:
            lines.append(f"  ポジショニング：{positioning}")
    
    # カタリスト
    catalysts_data = industry_data.get("catalysts", {})
    if catalysts_data.get("available"):
        catalysts = catalysts_data.get("catalysts", [])
        if catalysts:
            lines.append(f"\n【今後のカタリスト】")
            for c in catalysts[:3]:
                event = c.get("event", "")
                date = c.get("expected_date", "")
                importance = c.get("importance", "")
                impact = c.get("potential_impact", "")
                
                imp_mark = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(importance, "")
                impact_mark = {"positive": "📈", "negative": "📉", "mixed": "➡️"}.get(impact, "")
                
                lines.append(f"  {imp_mark}{impact_mark} {event} ({date})")
    
    return "\n".join(lines)


# テスト実行
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AMAT"
    sector = sys.argv[2] if len(sys.argv) > 2 else "Technology"
    
    print(f"🧪 Industry Trends テスト：{ticker} ({sector})")
    result = fetch_all_industry_data(ticker, sector)
    print("\n" + "="*60)
    print(format_industry_for_prompt(result))
    print("="*60)
