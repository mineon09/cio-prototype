"""
main.py - CIO司令塔 オーケストレーター (Professional CIO Edition)
================================================================
API呼び出し: 最大3回
  1回目: Geminiが比較対象を自動選定（JSON）
  2回目: (日本株のみ) EDINET有報をGeminiで解析
       (米国株のみ) SEC 10-K/10-QをGeminiで解析
  3回目: 対戦表 + 4軸分析 + 有報/10-Kインサイト + 最終判断を一括生成

4軸分析:
  - Fundamental（地力）: ROE, 営業利益率, 自己資本比率
  - Valuation（割安度）: PER, PBR, 目標価格乖離
  - Technical（タイミング）: RSI, MA乖離, BB位置
  - Qualitative（定性）: 有報/10-Kリスク, 堀, R&D

使い方:
  python main.py 7203.T
  python main.py 7203.T 8306.T AAPL
  python main.py --ticker AMAT
"""

import os, sys, re, json, time, io
from datetime import datetime

# Windows cp932 環境での絵文字出力エラーを防止（標準ストリームの場合のみ）
if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'buffer') and sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass
from dotenv import load_dotenv

# 環境変数を先にロード（モジュールが import 時に参照するため）
load_dotenv()

# モジュールインポート
import yfinance as yf  # DESIGN-003: モジュールレベルに移動
import pandas as pd
from src.data_fetcher import (
    fetch_stock_data, select_competitors, call_gemini,
    short_name, clean_val, pad_east_asian, get_east_asian_width_count,
)
from src.md_writer import write_to_md
from src.notion_writer import write_to_notion
from src.edinet_client import extract_yuho_data, is_japanese_stock
from src.analyzers import generate_scorecard, format_yuho_for_prompt, resolve_sector_profile
from src.portfolio import calculate_position_sizing

# SEC EDGAR（利用可能な場合のみ）
try:
    from src.sec_client import extract_sec_data, is_us_stock
    HAS_SEC = True
except ImportError:
    HAS_SEC = False
    def is_us_stock(ticker): return not ticker.endswith('.T')
    def extract_sec_data(ticker): return {}

# DCF理論株価
try:
    from src.dcf_model import estimate_fair_value
    HAS_DCF = True
except ImportError:
    HAS_DCF = False
    def estimate_fair_value(ticker): return {"available": False}

# マクロ環境判定
try:
    from src.macro_regime import detect_regime
    HAS_MACRO = True
except ImportError:
    HAS_MACRO = False
    def detect_regime(ticker=""): return {}



try:
    with open("config.json", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {
        "competitor_selection": {"direct_count": 3, "substitute_count": 2, "benchmark_count": 2},
        "sheets": {"output": "分析結果"}
    }


# ==========================================
# AI出力 事後矛盾チェック (Bug #3 対策)
# ==========================================

def _validate_market_bug_logic(metrics: dict, all_data: dict, target_ticker: str, report: str) -> str:
    """
    AIが出力した「市場のバグ」セクションについて、
    財務指標と結論の矛盾を検出して警告を追記する。
    """
    roe = metrics.get('roe') or 0
    per = metrics.get('per') or 0

    # 同業他社の平均PERを算出
    peer_pers = []
    for t, data in all_data.items():
        if t == target_ticker:
            continue
        peer_per = (data.get('metrics') or {}).get('per')
        if peer_per and peer_per > 0:
            peer_pers.append(peer_per)
    avg_per = sum(peer_pers) / len(peer_pers) if peer_pers else 0

    warnings = []

    # ROE低 + PER高 なのに「過小評価」と書いている場合
    if roe < 5 and per > 0 and avg_per > 0 and per > avg_per and "過小評価" in report:
        warnings.append(
            f"⚠️ [自動検証] ROE({roe}%)が低く、PER({per:.1f}倍)が同業平均({avg_per:.1f}倍)より高いにもかかわらず"
            f"「過小評価」と判定されています。指標と結論が矛盾している可能性があります。要確認。"
        )

    # ROE高 + PER低 なのに「過大評価」と書いている場合
    if roe > 15 and per > 0 and avg_per > 0 and per < avg_per * 0.7 and "過大評価" in report:
        warnings.append(
            f"⚠️ [自動検証] ROE({roe}%)が高く、PER({per:.1f}倍)が同業平均({avg_per:.1f}倍)より低いにもかかわらず"
            f"「過大評価」と判定されています。指標と結論が矛盾している可能性があります。要確認。"
        )

    if warnings:
        report += "\n\n" + "\n".join(warnings)

    return report


# ==========================================
# 全分析一括生成
# ==========================================

def analyze_all(target_ticker: str, all_data: dict, competitors: dict,
                yuho_data: dict = None, scorecard: dict = None,
                macro_data: dict = None, dcf_data: dict = None) -> tuple[str, str, str]:
    labels = {
        'op_margin':     '営業利益率(%)',
        'net_margin':    '純利益率(%)',
        'roe':           'ROE(%)',
        'revenue_growth':'売上成長率(%)',
        'rd_ratio':      'R&D/売上(%)',
        'cf_quality':    'CF品質',
        'equity_ratio':  '自己資本比率(%)',
        'per':           'PER(倍)',
        'pbr':           'PBR(倍)',
        'dividend_yield':'配当利回り(%)',
    }

    tickers = list(all_data.keys())
    name_map = {t: short_name(all_data[t].get('name', t)) for t in tickers}

    label_w = 22
    col_w   = 13

    header_row = pad_east_asian('指標', label_w) + " | " + " | ".join(f"{name_map[t]:<{col_w}}" for t in tickers)
    ticker_row = pad_east_asian('(ティッカー)', label_w) + " | " + " | ".join(f"{t:<{col_w}}" for t in tickers)
    line_len = get_east_asian_width_count(header_row)
    sep_line = "=" * line_len
    sub_line = "-" * line_len

    table_lines = [
        sep_line,
        f"📊 対戦表: {all_data[target_ticker].get('name', target_ticker)}",
        sep_line, header_row, ticker_row, sub_line,
    ]
    for key, label in labels.items():
        vals = [f"{clean_val(all_data[t].get('metrics', {}).get(key)):<{col_w}}" for t in tickers]
        table_lines.append(pad_east_asian(label, label_w) + " | " + " | ".join(vals))
    table_lines.append(sep_line)
    table_str = "\n".join(table_lines)

    target    = all_data[target_ticker]
    tech      = target.get('technical', {})
    sector    = target.get('sector', '不明')
    metrics   = target.get('metrics', {})

    # セクター別閾値をプロンプト用に解決
    profile_name, fund_cfg, valu_cfg, tech_cfg, weights = resolve_sector_profile(sector)
    sector_context = ""
    if profile_name != "default":
        sector_context = f"""【セクター別評価基準 ({sector} → {profile_name})】
このセクターでは以下の閾値を「良好」とみなす:
- ROE: {fund_cfg.get('roe_good', 10)}%以上が良好
- 営業利益率: {fund_cfg.get('op_margin_good', 15)}%以上が良好
- 自己資本比率: {fund_cfg.get('equity_ratio_good', 40)}%以上が良好
- PER: {valu_cfg.get('per_cheap', 15)}倍以下が割安
- PBR: {valu_cfg.get('pbr_cheap', 1.0)}倍以下が割安
これらの閾値はセクター特性に基づいて調整されている。一般的な閾値ではなく、上記の値に基づいて判断せよ。
"""
    
    # ポジションサイズの計算
    rec_pct, port_warning = calculate_position_sizing(target_ticker, sector, CONFIG)
    rec_pct_str = f"{rec_pct*100:.1f}%"
    
    port_constraint_text = ""
    if port_warning or rec_pct < CONFIG.get("position_sizing", {}).get("pct_per_trade", 0.10):
        port_constraint_text = f"【ポートフォリオ制約 (セクター集中度)】\\n推奨ポジションサイズ: {rec_pct_str} (上限到達や分散ルールによる制限)\\n⚠️ 警告: {port_warning}\\n※アクションの「ポジションサイズ」は上記推奨値以下に設定すること。\\n"
    else:
        port_constraint_text = f"【ポートフォリオ制約】特になし (推奨最大: {rec_pct_str})\\n"
    
    # ニュースの切り詰め（最新10件程度または文字数制限）
    news_list = target.get('news', [])
    news_text = "\n".join(news_list[:10]) or "ニュースなし"
    if len(news_text) > 2000:
        news_text = news_text[:2000] + "\n...(以下略)"

    # マクロ文脈テキストの生成（LLMがregimeを「解釈」できるよう指示）
    regime = ''
    vix_val = ''
    us10y_val = ''
    usdjpy_val = ''
    if macro_data:
        regime = macro_data.get('regime', 'NEUTRAL')
        vix_val = macro_data.get('vix', {}).get('current', '') if isinstance(macro_data.get('vix'), dict) else macro_data.get('vix', '')
        us10y_val = macro_data.get('us10y', '')
        usdjpy_val = macro_data.get('usdjpy', {}).get('current', '') if isinstance(macro_data.get('usdjpy'), dict) else macro_data.get('usdjpy', '')
    
    macro_context_text = f"""【マクロ環境と判断指針】
レジーム: {regime or 'NEUTRAL'}"""
    if vix_val:
        vix_note = "リスクオフ局面、新規エントリーは慎重に" if isinstance(vix_val, (int, float)) and vix_val > 20 else "リスク環境は落ち着いている"
        macro_context_text += f"\nVIX: {vix_val} — {vix_note}"
    if us10y_val:
        rate_note = "高金利継続、グロース株のバリュエーション圧迫" if isinstance(us10y_val, (int, float)) and us10y_val > 4.0 else "金利低下局面"
        macro_context_text += f"\n米10年金利: {us10y_val}% — {rate_note}"
    if usdjpy_val:
        macro_context_text += f"\nドル円: {usdjpy_val}円"
    macro_context_text += "\n上記マクロ環境を踏まえ、このセクター・銘柄への影響を分析に明示的に反映すること。"
    macro_context_text += "\nニュースが空の場合でも、マクロ指標とレジームから合理的に推論し、センチメント分析に反映すること。"
    
    # DCF 信頼度テキスト（FCF変動が大きい銘柄への対策）
    dcf_section = ""
    if dcf_data and dcf_data.get('available'):
        rel = dcf_data.get('reliability', 'low')
        fv = dcf_data.get('fair_value', 0)
        upside_dcf = dcf_data.get('upside', 0)
        if rel == 'low':
            dcf_section = f"\n【DCF理論株価】{fv:,.0f} {target.get('currency', 'USD')}（⚠️ FCF変動大のため低信頼度。参考値として扱え）"
        else:
            dcf_section = f"\n【DCF理論株価】{fv:,.0f} {target.get('currency', 'USD')}（上昇余地: {upside_dcf:+.1f}%）"

    cur       = tech.get('current_price', 'N/A')
    currency  = target.get('currency', 'USD')

    yuho_text = format_yuho_for_prompt(yuho_data) if yuho_data else ""
    # SEC生テキストがある場合はプロンプトに含める
    raw_text = yuho_data.get('raw_text', '') if yuho_data else ''
    if raw_text:
        yuho_text = (yuho_text + "\n\n【10-K/10-Q 原文抜粋】\n" + raw_text)[:6000]
    if len(yuho_text) > 6000:
        yuho_text = yuho_text[:6000] + "\n...(有報/10-Kデータを一部省略)"
    yuho_section = f"\n{yuho_text}\n" if yuho_text else "\n【有価証券報告書/10-K】対象外または未取得\n"

    scorecard_text = scorecard.get('summary_text', '') if scorecard else ''
    scorecard_section = f"\n{scorecard_text}\n" if scorecard_text else ''

    layer3_format = ""
    if yuho_data and yuho_data.get('available'):
        layer3_format = """
━━━ 📋 Layer3: 定性分析（有報/10-K） ━━━
🏰 競争優位性（堀）: [有報/10-Kデータに基づき、堀の種類・耐久性・具体例]
⚠️ 経営リスクTOP3: [「事業等のリスク」/Risk Factorsから、現在の株価に織り込まれているか判断]
🔬 R&D戦略: [R&D比率の数字が具体的にどの技術に投資されているか]
📋 定性スコア: X/10 [根拠2行]
"""

    print(f"🚀 [API 1/1] 全分析を一括生成中...")
    prompt = f"""
あなたは外資系ヘッジファンドのCIOです。
以下のデータをすべて使い、投資レポートを日本語で1つのレスポンスとして完成させてください。

【比較の文脈】{competitors.get('reasoning', '')}

{port_constraint_text}

{table_str}

【テクニカル（{target_ticker}）】
現在価格:{cur} {currency} / MA25乖離:{tech.get('ma25_deviation')}% / MA75乖離:{tech.get('ma75_deviation')}%
RSI:{tech.get('rsi')} / BB位置:{tech.get('bb_position')}% / ボラ:{tech.get('volatility')}% / 出来高比:{tech.get('volume_ratio')}x
アナリスト目標:{tech.get('analyst_target')}
{yuho_section}
{scorecard_section}
【ニュース・センチメント（直近7日）】
{news_text}
※ ニュースがある場合、センチメント分析ではニュースの内容を具体的に引用し、
  株価への影響を「ポジティブ/中立/ネガティブ」と強度で明示すること。
  ニュースがない場合は「情報なし」と記載し、マクロ環境から推論すること。

{macro_context_text}
{dcf_section}

{sector_context}
【注意】"-"はデータ未取得を意味する。銀行・金融業はcf_qualityが異常値になりやすいため、ROE・PBR・純利益率を重視して判断せよ。
有報/10-Kデータがある場合は、数値指標とテキストを照合し、数字の「裏側」にある経営意図を読み解くこと。
4軸スコアカード（Layer3末尾の数値）は、あなたの論理的思考の「検算」として機能させること。
同じ銘柄を再度分析する場合、以前の評価と著しく乖離しないよう、事実（Fact）に基づく公平な評価を徹底すること。

【スコア制約（厳守）】
本質的価値スコア・タイミングスコア・定性スコアの数値は変更禁止。
提供されたスコアカードの数値をそのまま使用し、最終判断のスコアと必ず一致させること。
分析コメントでの評価の深掘りは歓迎するが、数値の上方・下方いずれの修正も行わないこと。
「🔢 総合スコア」は4軸の加重平均と大きく乖離しないこと。

【指標の方向性（厳守）】
ROE: 高いほど良い（資本効率が高い）。低ROEは投資効率に懸念あり。
PER: 低いほど割安。高PERは成長期待が織り込まれている可能性あり。
PBR: 低いほど割安。1倍割れは資産価値以下。
配当利回り: 高いほど株主還元が厚い。
重要: ROEが低く(5%以下)かつPERが同業比で高い場合、それは「過小評価」ではなく「過大評価」の兆候である。逆にROEが高くPERが低い場合が「過小評価」の可能性を示す。この方向性を絶対に間違えないこと。

【出力形式（厳守）】

━━━ ⚔️ Layer1: 地力分析 ━━━
💪 競争優位性: [数値根拠付き3項目]
⚠️ 競争劣位性: [2項目]
🐛 市場のバグ: [過小評価 or 過大評価のいずれかを、数値根拠を付けて公平に判定。ROEが低くPERが高い場合に「過小評価」と断定しないこと。]
📊 本質的価値スコア: X/10 [根拠2行]

━━━ ⏱️ Layer2: タイミング分析 ━━━
📰 センチメント: [ポジティブ/中立/ネガティブ] 強度[高/中/低] [根拠2行]
📈 テクニカル: [過熱/適正/割安] [根拠2行]
⚠️ 指標の矛盾: [あれば記載、なければ「矛盾なし」]
📅 カタリスト: [具体的イベント・日付]
⏱️ タイミングスコア: X/10
{layer3_format}
━━━ ✅ 最終投資判断 ━━━
🎯 シグナル: BUY / WATCH / SELL
📊 地力スコア: X/10
⏱️ タイミングスコア: X/10
📋 定性スコア: X/10（有報/10-Kデータがある場合）
🔢 総合スコア: X/10
【根拠】[3行]
【アクション】
- エントリー価格: {currency} XXX
- 損切りライン:   {currency} XXX（理由:）
- 利確ライン:     {currency} XXX（理由:）
- ポジションサイズ: ポートフォリオの X% (上限:{rec_pct_str})
【出口戦略】
- 利確条件: [価格 or イベント]
- 損切り条件: [価格 AND ファンダメンタル変化]
【監視ポイント】1. 2.
"""
    # 日本株の場合は google_search ツールを有効化（yfinanceニュースが日本株ではほぼ空のため）
    is_jp = target_ticker.endswith('.T')
    report, model_name = call_gemini(prompt, use_search=is_jp)

    # Bug #3: AI出力の事後矛盾チェック
    if report and report != "分析失敗":
        report = _validate_market_bug_logic(metrics, all_data, target_ticker, report)

    if not report or report == "分析失敗":
        print(f"  ⚠️ Gemini/Groq ともに失敗。ローカルでの簡易要約に切り替えます...")
        print(f"  📝 デバッグ: report={repr(report)[:100]}")
        report = f"""
━━━ ⚔️ Layer1: 地力分析 ━━━
💪 競争優位性: 対戦表の数値を参照（要手動確認）
📊 本質的価値スコア: {scorecard.get('fundamental', {}).get('score', 0)}/10

━━━ ⏱️ Layer2: タイミング分析 ━━━
📈 テクニカル: RSI {tech.get('rsi', '-')} / MA25乖離 {tech.get('ma25_deviation', '-')}
⏱️ タイミングスコア: {scorecard.get('technical', {}).get('score', 0)}/10

━━━ ✅ 最終投資判断 ━━━
🎯 シグナル: {scorecard.get('signal', 'WATCH')}
🔢 総合スコア: {scorecard.get('total_score', 0)}/10
【注意】AIによる詳細レポート生成に失敗しました。スコアカードの数値を優先して確認してください。
"""
        model_name = "Local Fallback"

    # レポート末尾にモデル名を追記
    if model_name:
        report += f"\n\n(分析エンジン: {model_name})"

    return report, table_str, model_name, rec_pct


# ==========================================
# メインフロー
# ==========================================

def run(ticker: str, strategy: str = "long"):
    print(f"\n{'='*60}\n🚀 {ticker} の司令塔分析を開始 (Professional CIO Edition)\n{'='*60}")

    target_data = fetch_stock_data(ticker)
    
    if "price_warning" in target_data.get("technical", {}) or not target_data.get("metrics"):
        warning_msg = f"{ticker}: データ品質が基準を満たさないため分析をスキップします (NaN超過 または 株価異常変動)"
        print(f"  ⚠️ {warning_msg}")
        return "分析スキップ (データ品質)"

    # ── マクロ環境判定（競合選定の前に実行） ──
    # A-1: 失敗時に NEUTRAL との区別がつくよう安全な初期値を設定
    macro_data = {"regime": "UNAVAILABLE"}
    if HAS_MACRO:
        try:
            macro_data = detect_regime(ticker)
        except Exception as e:
            print(f"  ⚠️ マクロ取得失敗（NEUTRAL扱いで続行）: {e}")
            macro_data = {"regime": "NEUTRAL", "_fetch_error": True}

    # ── 競合選定（マクロ環境を考慮） ──
    competitors = select_competitors(target_data, macro_data=macro_data)

    all_tickers = [ticker] + competitors.get('direct',[]) + competitors.get('substitute',[]) + competitors.get('benchmark',[])
    all_data = {ticker: target_data}

    for ct in all_tickers[1:]:
        if ct not in all_data:
            try:
                all_data[ct] = fetch_stock_data(ct)
            except Exception as e:
                print(f"  ⚠️ {ct} 取得失敗: {e}")
                all_data[ct] = {"ticker": ct, "name": ct, "metrics": {}, "technical": {}}

    # ── 有報/10-K 取得 ──
    yuho_data = {}
    if is_japanese_stock(ticker):
        print(f"\n🇯🇵 日本株: EDINET有報を検索中...")
        # A-3: EDINET API障害時も有報なしで分析続行
        try:
            yuho_data = extract_yuho_data(ticker)
        except Exception as e:
            print(f"  ⚠️ EDINET取得失敗（有報なしで続行）: {e}")
            yuho_data = {}
        if yuho_data and yuho_data.get('available'):
            print(f"  ✅ 有報データ取得成功")
        else:
            print(f"  ⚠️ 有報データなし")
    elif HAS_SEC and is_us_stock(ticker):
        print(f"\n🇺🇸 米国株: SEC 10-K/10-Q を検索中...")
        yuho_data = extract_sec_data(ticker)
        if yuho_data and yuho_data.get('available'):
            print(f"  ✅ 10-K/10-Q データ取得成功")
        else:
            print(f"  ⚠️ SEC データなし")
    else:
        print(f"ℹ️ 有価証券報告書の取得をスキップ")

    # ── ニュース取得（Gemini google_search） ──
    # 日本株・米国株問わずニュースを取得
    if not target_data.get('news'):
        print(f"  📰 {ticker} のニュースを検索中...")
        try:
            from src.news_fetcher import fetch_all_news
            
            # 過去 14 日分のニュースを取得
            news_data = fetch_all_news(
                ticker=ticker,
                company_name=target_data.get('name', ''),
                include_google=True,
                yf_limit=5,
                google_limit=10,
                google_days=14
            )
            
            # ニュースを文字列リストに変換
            all_news = news_data.get('all_news', [])
            if all_news:
                target_data['news'] = []
                for n in all_news[:10]:
                    date = n.get('published_at', '')[:10] if n.get('published_at') else ''
                    title = n.get('title', '')
                    source = n.get('publisher', '') or n.get('source', '')
                    if title:
                        target_data['news'].append(f"[{date}] {title} ({source})")
                print(f"  ✅ ニュース取得：{len(target_data['news'])}件")
                
                # センチメント情報も保存
                sentiment = news_data.get('sentiment', {})
                target_data['news_sentiment'] = sentiment
            else:
                print(f"  ⚠️ ニュース取得失敗（スキップ）")
                target_data['news'] = []
        except Exception as e:
            print(f"  ⚠️ ニュース取得エラー：{e}")
            target_data['news'] = []

    # ── DCF理論株価算出 ──
    dcf_data = {}
    if HAS_DCF:
        dcf_data = estimate_fair_value(ticker)

    # ── コンフィグ読み込み (Override適用) ──
    from src.utils import load_config_with_overrides
    config = load_config_with_overrides(ticker)

    # ── 4軸スコアカード算出（セクター別閾値 + DCF + マクロ補正） ──
    sector = target_data.get('sector', '')
    if sector and sector != '不明':
        print(f"🏭 セクター: {sector}")
        
    # Regime Overrides に基づく BUY閾値を解決
    regime = macro_data.get('regime', 'NEUTRAL') if macro_data else 'NEUTRAL'
    buy_threshold = (
        CONFIG.get("signals", {})
        .get("BUY", {})
        .get("regime_overrides", {})
        .get(regime, {})
        .get("min_score")
    )  # None の場合は generate_scorecard 内のデフォルト 6.5 が使用される

    # ベースのスコアカード生成
    base_scorecard = generate_scorecard(
            target_data.get('metrics', {}),
            target_data.get('technical', {}),
            yuho_data,
            sector=sector,
            dcf_data=dcf_data,
            macro_data=macro_data,
            buy_threshold=buy_threshold,
    )
    
    # 戦略分析を実行
    scorecard = run_strategy_analysis(ticker, strategy, base_scorecard, macro_data, config)

    summary_text = scorecard.get('summary_text', '')
    if summary_text:
        print(f"\n{summary_text}")

    report, table_str, model_name, rec_pct = analyze_all(
        ticker, all_data, competitors,
        yuho_data=yuho_data, scorecard=scorecard,
        macro_data=macro_data, dcf_data=dcf_data,
    )

    # ── 新規出力 (MDとNotion) ──
    try:
        md_file_path = write_to_md(ticker, target_data, report, scorecard)
        write_to_notion(ticker, target_data, report, scorecard, md_file_path)
    except Exception as e:
        print(f"⚠️ MD/Notion保存エラー: {e}")

    # ── ダッシュボード用JSON出力（履歴蓄積型） ──
    save_to_dashboard_json(ticker, target_data, scorecard, report,
                           dcf_data=dcf_data, macro_data=macro_data, model_name=model_name,
                           rec_pct=rec_pct)

    print("\n" + "="*60 + "\n" + report + "\n" + "="*60)
    return report

def run_strategy_analysis(ticker, strategy, base_scorecard, macro_data, config):
    """
    指定された戦略に基づいて詳細分析を行う (Shared Logic)
    GUI (app.py) からも利用される。
    """
    # DESIGN-003: モジュールレベルで import 済みの pandas / yfinance を使用
    scorecard = base_scorecard.copy() # Baseをコピーして使用

    if strategy not in ["bounce", "breakout"]:
        return scorecard

    print(f"🔄 スイング戦略 ({strategy}) で分析を実行します... (Shared Logic)")
    
    # 1. 必要なデータ取得 (History)
    # 取得期間は長めに (MA75等計算用)
    hist = yf.Ticker(ticker).history(period="1y") 
    if hist.empty:
            print("⚠️ ヒストリカルデータ取得失敗")
            # エラー時はベースを返すか、エラー情報を付与するか
            scorecard['signal'] = "ERROR"
            scorecard['summary_text'] = "⚠️ データの取得に失敗しました"
            return scorecard

    from src.analyzers import TechnicalAnalyzer
    from src.strategies import BounceStrategy, BreakoutStrategy
    
    ta = TechnicalAnalyzer(hist)
    
    # 2. Strategy インスタンス化
    strat_map = {
        "bounce": BounceStrategy,
        "breakout": BreakoutStrategy
    }
    strat_class = strat_map.get(strategy)
    strat = strat_class(strategy, config)
    
    # 3. Rowデータの作成 (Strategyが期待する形式)
    row = hist.iloc[-1].copy()
    row['regime'] = macro_data.get('regime', 'NEUTRAL')
    row['fundamental'] = base_scorecard.get('fundamental', {}).get('score', 0)
    row['score'] = base_scorecard.get('total_score', 0)
    
    # 4. エントリー分析実行
    result = strat.analyze_entry(row, hist, ta)
    
    is_entry = result["is_entry"]
    details = result["details"]
    metrics = result.get("metrics", {})
    
    signal = "BUY" if is_entry else "WATCH"
    scorecard['signal'] = signal
    scorecard['strategy_details'] = details
    scorecard['strategy_metrics'] = metrics # GUI表示用にメトリクスも保存
    scorecard['summary_text'] = f"【{strategy.upper()}戦略 (v1.5)】\n判定: {signal}\n" + "\n".join(details)
    
    return scorecard


def save_to_dashboard_json(ticker, target_data, scorecard, report,
                           dcf_data=None, macro_data=None, model_name=None, rec_pct=None):
    """分析結果をWebダッシュボード用のJSON（履歴蓄積型）に保存する"""
    data_dir = "data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    file_path = os.path.join(data_dir, "results.json")
    
    # C-3: 排他ロックで並列実行時のデータ競合を防止
    try:
        from filelock import FileLock
        lock = FileLock(file_path + ".lock", timeout=10)
    except ImportError:
        from contextlib import nullcontext
        lock = nullcontext()

    import tempfile
    try:
        with lock:
            # 既存データの読み込み（ロック内で最新状態を取得）
            all_results = {}
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        all_results = json.load(f)
                except Exception:
                    all_results = {}

            # new_entry の定義 (C-1: holding / position_size を含む)
            new_entry = {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "scores": {
                    "fundamental": scorecard.get("fundamental", {}).get("score", 0),
                    "valuation":   scorecard.get("valuation", {}).get("score", 0),
                    "technical":   scorecard.get("technical", {}).get("score", 0),
                    "qualitative": scorecard.get("qualitative", {}).get("score", 0),
                },
                "weights":    scorecard.get("weights", {}),
                "signal":     scorecard.get("signal", "WATCH"),
                "holding":    scorecard.get("signal") == "BUY",       # C-1
                "position_size": rec_pct if rec_pct is not None else 0.10,  # 算出済み推奨値を使用
                "total_score": scorecard.get("total_score", 0),
                "metrics":    target_data.get("metrics", {}),
                "technical_data": target_data.get("technical", {}),
                "report":     report,
                "ai_model":   model_name or "Unknown",
            }

            # DCF データがあれば追加
            if dcf_data and dcf_data.get("available"):
                new_entry["dcf"] = {
                    "fair_value": dcf_data.get("fair_value"),
                    "upside": dcf_data.get("upside"),
                    "wacc": dcf_data.get("wacc"),
                }

            # マクロ環境データがあれば追加
            if macro_data and macro_data.get("regime"):
                new_entry["macro"] = {
                    "regime": macro_data.get("regime"),
                    "detail": macro_data.get("detail", ""),
                }

            # 既存のエントリを取得 or 新規作成
            if ticker in all_results:
                existing = all_results[ticker]
                # 旧フォーマット（historyキーなし）→ マイグレーション
                if "history" not in existing:
                    old_entry = {
                        "date": existing.get("date", ""),
                        "scores": existing.get("scores", {}),
                        "weights": existing.get("weights", {}),
                        "signal": existing.get("signal", "WATCH"),
                        "total_score": existing.get("total_score", 0),
                        "metrics": existing.get("metrics", {}),
                        "technical_data": existing.get("technical_data", {}),
                        "report": existing.get("report", ""),
                    }
                    existing = {
                        "name": existing.get("name", ticker),
                        "sector": existing.get("sector", "不明"),
                        "currency": existing.get("currency", "USD"),
                        "history": [old_entry],
                    }
                existing["history"].append(new_entry)
                # 最大20件保持
                existing["history"] = existing["history"][-20:]
                # メタデータの更新
                existing["name"] = target_data.get("name", ticker)
                existing["sector"] = target_data.get("sector", "不明")
                existing["currency"] = target_data.get("currency", "USD")
                all_results[ticker] = existing
            else:
                all_results[ticker] = {
                    "name": target_data.get("name", ticker),
                    "sector": target_data.get("sector", "不明"),
                    "currency": target_data.get("currency", "USD"),
                    "history": [new_entry],
                }

            # 一時ファイルに書き込んでから置換（アトミックな書き込み）
            import numpy as np
            def _json_safe(obj):
                """numpy型をPython標準型に変換してJSONシリアライズ可能にする"""
                if isinstance(obj, (np.integer,)): return int(obj)
                if isinstance(obj, (np.floating,)): return float(obj)
                if isinstance(obj, np.ndarray): return obj.tolist()
                if isinstance(obj, (np.bool_,)): return bool(obj)
                raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=data_dir, suffix=".tmp") as tf:
                json.dump(all_results, tf, indent=2, ensure_ascii=False, default=_json_safe)
                tempname = tf.name

            # Windows では os.replace を使用する前にファイルを閉じる必要がある
            if os.path.exists(file_path):
                os.remove(file_path)
            os.rename(tempname, file_path)

        history_count = len(all_results[ticker]["history"])
        print(f"📁 ダッシュボード用データ保存完了 ({ticker}, 履歴数: {history_count})")
    except Exception as e:
        print(f"❌ データ保存失敗: {e}")


def main():
    if not os.environ.get('GEMINI_API_KEY'):
        print("❌ GEMINI_API_KEY が未設定")
        sys.exit(1)

    args = sys.argv[1:]
    tickers = []
    strategy = "long" # Default
    skip = False
    
    for i, arg in enumerate(args):
        if skip: skip = False; continue
        if arg.lower() == '--ticker':
            if i + 1 < len(args): tickers.append(args[i+1].upper()); skip = True
        elif arg.lower() == '--strategy':
            if i + 1 < len(args): 
                strategy = args[i+1].lower()
                skip = True
        elif not arg.startswith('--'):
            tickers.append(arg.upper())

    # ティッカーバリデーション: パスやコマンドの誤混入を防止
    valid_tickers = [t for t in tickers if re.match(r'^[A-Z0-9\.\^\-]{1,15}$', t)]
    invalid = set(tickers) - set(valid_tickers)
    if invalid:
        print(f"⚠️ 無効なティッカーをスキップ: {invalid}")
    tickers = valid_tickers

    if not tickers:
        raw = input("銘柄コードを入力（例: 7203.T AAPL）> ").strip()
        tickers = [t.upper() for t in raw.replace(',', ' ').split() if t]
        tickers = [t for t in tickers if re.match(r'^[A-Z0-9\.\^\-]{1,15}$', t)]

    if not tickers:
        print("❌ 銘柄コードが入力されていません")
        sys.exit(1)

    print(f"🎯 分析対象: {', '.join(tickers)}")
    for i, ticker in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}] {ticker}")
        try:
            run(ticker, strategy=strategy)
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {ticker} 失敗: {err_msg}")
            import traceback
            tb = traceback.format_exc()
            print(f"{err_msg}\n{tb}")
        if i < len(tickers) - 1:
            print("⏳ 5秒待機...")
            time.sleep(5)


if __name__ == "__main__":
    main()
