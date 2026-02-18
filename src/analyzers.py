"""
analyzers.py - 4軸スコアリングエンジン
=======================================
Fundamental / Valuation / Technical / Qualitative の4レイヤーで
ルールベーススコアリングを行う（Gemini API呼び出しなし）。

改善点:
  - セクター別スコアリング閾値 (High-Growth / Value / Financial)
  - 経営陣トーン分析 (management_tone) のスコア反映

各スコアは 0–10 のスケールで、根拠テキスト付きで返す。
"""

import json, math, logging
import pandas as pd

# ロガー設定
logger = logging.getLogger("CIO_Analyzers")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

try:
    with open("config.json", encoding="utf-8") as f:
        _CFG = json.load(f)
except Exception:
    _CFG = {}

SCORING_CFG = _CFG.get("scoring", {
    "fundamental": {"roe_good": 10, "op_margin_good": 15, "equity_ratio_good": 40},
    "valuation":   {"per_cheap": 15, "pbr_cheap": 1.0},
    "technical":   {"rsi_oversold": 30, "rsi_overbought": 70},
})

# セクター別スコアリングプロファイル
_DEFAULT_WEIGHTS = {"fundamental": 0.30, "valuation": 0.25, "technical": 0.20, "qualitative": 0.25}
SECTOR_PROFILES = _CFG.get("sector_profiles", {
    "high_growth": {
        "sectors": ["Technology", "Communication Services"],
        "weights":      {"fundamental": 0.20, "valuation": 0.25, "technical": 0.25, "qualitative": 0.30},
        "fundamental":  {"roe_good": 15, "op_margin_good": 20, "equity_ratio_good": 30, "rd_weight": 1.5},
        "valuation":    {"per_cheap": 30, "pbr_cheap": 4.0},
        "technical":    {"rsi_oversold": 25, "rsi_overbought": 75},
    },
    "healthcare": {
        "sectors": ["Healthcare"],
        "weights":      {"fundamental": 0.25, "valuation": 0.20, "technical": 0.20, "qualitative": 0.35},
        "fundamental":  {"roe_good": 12, "op_margin_good": 18, "equity_ratio_good": 35, "rd_weight": 2.0},
        "valuation":    {"per_cheap": 25, "pbr_cheap": 3.0},
        "technical":    {"rsi_oversold": 28, "rsi_overbought": 72},
    },
    "value": {
        "sectors": ["Industrials", "Consumer Defensive", "Utilities", "Basic Materials",
                    "Energy", "Consumer Cyclical", "Real Estate"],
        "weights":      {"fundamental": 0.35, "valuation": 0.30, "technical": 0.20, "qualitative": 0.15},
        "fundamental":  {"roe_good": 8, "op_margin_good": 10, "equity_ratio_good": 40, "rd_weight": 0.5},
        "valuation":    {"per_cheap": 12, "pbr_cheap": 1.0},
        "technical":    {"rsi_oversold": 30, "rsi_overbought": 70},
    },
    "financial": {
        "sectors": ["Financial Services", "Financial"],
        "weights":      {"fundamental": 0.35, "valuation": 0.30, "technical": 0.20, "qualitative": 0.15},
        "fundamental":  {"roe_good": 8, "op_margin_good": 25, "equity_ratio_good": 8, "rd_weight": 0.0},
        "valuation":    {"per_cheap": 10, "pbr_cheap": 0.8},
        "technical":    {"rsi_oversold": 30, "rsi_overbought": 70},
    },
})


def resolve_sector_profile(sector: str) -> tuple:
    """
    yfinanceの sector 文字列から適切なスコアリングプロファイルを選択。
    Returns: (profile_name, fundamental_cfg, valuation_cfg, technical_cfg, weights)
    """
    default_fund = SCORING_CFG.get("fundamental", {})
    default_valu = SCORING_CFG.get("valuation", {})
    default_tech = SCORING_CFG.get("technical", {})

    if not sector:
        return "default", default_fund, default_valu, default_tech, dict(_DEFAULT_WEIGHTS)

    for profile_name, profile in SECTOR_PROFILES.items():
        if sector in profile.get("sectors", []):
            return (
                profile_name,
                profile.get("fundamental", default_fund),
                profile.get("valuation", default_valu),
                profile.get("technical", default_tech),
                profile.get("weights", dict(_DEFAULT_WEIGHTS)),
            )

    return "default", default_fund, default_valu, default_tech, dict(_DEFAULT_WEIGHTS)


def _safe(v, default=None):
    """None / nan を default に変換"""
    if v is None:
        return default
    try:
        if isinstance(v, float) and math.isnan(v):
            return default
    except (TypeError, ValueError):
        pass
    return v


def _clamp(score: float) -> float:
    """スコアを 0–10 に制限"""
    return max(0.0, min(10.0, round(score, 1)))


# ==========================================
# Layer 1: Fundamental（企業の地力）
# ==========================================

def score_fundamental(metrics: dict, sector: str = "") -> dict:
    """
    ROE, 営業利益率, 自己資本比率, CF品質, R&D比率 から地力スコアを算出。
    sectorに応じた閾値・R&D重みを自動選択。
    """
    profile_name, cfg, _, _, _ = resolve_sector_profile(sector)
    if not cfg:
        cfg = SCORING_CFG.get("fundamental", {})
    rd_weight = cfg.get("rd_weight", 1.0)  # セクター別 R&D 重み
    parts = []
    total = 0.0
    count = 0

    # ROE
    roe = _safe(metrics.get('roe'))
    if roe is not None:
        roe_good = cfg.get("roe_good", 10)
        # 数学的連続性を確保 (roe_good で 7点、 roe_good*2 で 10点、0 で 0点)
        if roe >= roe_good:
            s = 7 + (roe - roe_good) / roe_good * 3
            status = "良好" if roe < roe_good * 2 else "極めて高い"
        else:
            s = (roe / roe_good) * 7
            status = "平均的" if roe >= 5 else "低い"
        
        if roe <= 0: s = 0; status = "赤字"
            
        parts.append(f"ROE {roe}% — {status}な資本効率")
        total += _clamp(s)
        count += 1

    # 営業利益率
    op = _safe(metrics.get('op_margin'))
    if op is not None:
        op_good = cfg.get("op_margin_good", 15)
        if op >= op_good:
            s = 7 + (op - op_good) / op_good * 3
            status = "高収益" if op < op_good * 2 else "圧倒的収益力"
        else:
            s = (op / op_good) * 7
            status = "標準的" if op >= 5 else "低収益"
        
        if op <= 0: s = 0; status = "営業赤字"

        parts.append(f"営業利益率 {op}% — {status}")
        total += _clamp(s)
        count += 1

    # 自己資本比率
    eq = _safe(metrics.get('equity_ratio'))
    if eq is not None:
        eq_good = cfg.get("equity_ratio_good", 40)
        if eq >= eq_good:
            s = 7 + (eq - eq_good) / eq_good * 3
            status = "安全" if eq < eq_good * 2 else "極めて安全"
        else:
            s = (eq / eq_good) * 7
            status = "注意" if eq >= 20 else "財務リスクあり"
            
        if eq <= 0: s = 0

        parts.append(f"自己資本比率 {eq}% — {status}")
        total += _clamp(s)
        count += 1

    # CF品質 (Operating CF / Net Income)
    cf = _safe(metrics.get('cf_quality'))
    if cf is not None and cf > 0:
        if cf >= 1.5:
            s = 9
            parts.append(f"CF品質 {cf} — キャッシュリッチ")
        elif cf >= 1.0:
            s = 7
            parts.append(f"CF品質 {cf} — 健全")
        elif cf >= 0.5:
            s = 4
            parts.append(f"CF品質 {cf} — やや弱い")
        else:
            s = 2
            parts.append(f"CF品質 {cf} — 利益と現金の乖離大")
        total += _clamp(s)
        count += 1

    # R&D 比率（高いほど将来投資、セクター別重み付き）
    rd = _safe(metrics.get('rd_ratio'))
    if rd is not None and rd > 0 and rd_weight > 0:
        if rd >= 15:
            s = 9
            parts.append(f"R&D比率 {rd}% — 積極的な将来投資")
        elif rd >= 8:
            s = 7
            parts.append(f"R&D比率 {rd}% — 標準的な研究開発投資")
        elif rd >= 3:
            s = 5
            parts.append(f"R&D比率 {rd}% — 控えめ")
        else:
            s = 3
            parts.append(f"R&D比率 {rd}% — 低い研究投資")
        # rd_weight でスコアへの寄与度を調整
        total += _clamp(s) * rd_weight
        count += rd_weight  # 重み付きカウント
        if rd_weight != 1.0:
            parts[-1] += f" (重み×{rd_weight})"

    score = _clamp(total / max(count, 1))
    if sector:
        parts.insert(0, f"セクター: {sector} → プロファイル[{profile_name}]で評価")
    return {
        "layer": "Fundamental",
        "score": score,
        "details": parts,
        "data_points": count,
    }


# ==========================================
# Layer 2: Valuation（割安度）
# ==========================================

def score_valuation(metrics: dict, technical: dict = None, sector: str = "",
                    dcf_data: dict = None):
    """
    PER, PBR, 配当利回り, アナリスト目標価格との乖離, DCF理論株価から割安度を算出。
    sectorに応じた閾値を自動選択。
    """
    profile_name, _, cfg, _, _ = resolve_sector_profile(sector)
    if not cfg:
        cfg = SCORING_CFG.get("valuation", {})
    parts = []
    total = 0.0
    count = 0

    # PER
    per = _safe(metrics.get('per'))
    if per is not None and per > 0:
        per_cheap = cfg.get("per_cheap", 15)
        if per <= per_cheap * 0.5:
            s = 10
            parts.append(f"PER {per:.1f}倍 — 超割安")
        elif per <= per_cheap:
            s = 7 + (per_cheap - per) / per_cheap * 3
            parts.append(f"PER {per:.1f}倍 — 割安圏")
        elif per <= per_cheap * 2:
            s = 4 + (per_cheap * 2 - per) / per_cheap * 3
            parts.append(f"PER {per:.1f}倍 — 適正〜やや割高")
        else:
            s = max(0, 4 - (per - per_cheap * 2) / per_cheap * 2)
            parts.append(f"PER {per:.1f}倍 — 割高")
        total += _clamp(s)
        count += 1

    # PBR
    pbr = _safe(metrics.get('pbr'))
    if pbr is not None and pbr > 0:
        pbr_cheap = cfg.get("pbr_cheap", 1.0)
        if pbr <= pbr_cheap * 0.5:
            s = 10
            parts.append(f"PBR {pbr:.2f}倍 — 超割安（簿価割れ深刻）")
        elif pbr <= pbr_cheap:
            s = 8
            parts.append(f"PBR {pbr:.2f}倍 — 割安圏")
        elif pbr <= pbr_cheap * 3:
            s = 5
            parts.append(f"PBR {pbr:.2f}倍 — 適正")
        elif pbr <= pbr_cheap * 5:
            s = 3
            parts.append(f"PBR {pbr:.2f}倍 — やや割高")
        else:
            s = 1
            parts.append(f"PBR {pbr:.2f}倍 — 割高")
        total += _clamp(s)
        count += 1

    # 配当利回り
    div = _safe(metrics.get('dividend_yield'))
    if div is not None and div > 0:
        if div >= 5:
            s = 9
            parts.append(f"配当利回り {div}% — 高配当")
        elif div >= 3:
            s = 7
            parts.append(f"配当利回り {div}% — 魅力的")
        elif div >= 1.5:
            s = 5
            parts.append(f"配当利回り {div}% — 標準")
        else:
            s = 3
            parts.append(f"配当利回り {div}% — 低配当")
        total += _clamp(s)
        count += 1

    # アナリスト目標価格との乖離
    if technical:
        cur    = _safe(technical.get('current_price'))
        target = _safe(technical.get('analyst_target'))
        if cur and target and cur > 0:
            upside = (target - cur) / cur * 100
            if upside >= 30:
                s = 10
                parts.append(f"目標価格乖離 +{upside:.0f}% — 大幅な上昇余地")
            elif upside >= 15:
                s = 8
                parts.append(f"目標価格乖離 +{upside:.0f}% — 上昇余地あり")
            elif upside >= 0:
                s = 5
                parts.append(f"目標価格乖離 +{upside:.0f}% — 概ね適正")
            else:
                s = max(0, 3 + upside / 20)
                parts.append(f"目標価格乖離 {upside:.0f}% — 下落リスク")
            total += _clamp(s)
            count += 1

    # DCF理論株価との乖離
    if dcf_data and dcf_data.get("available"):
        upside = dcf_data.get("upside", 0)
        fv = dcf_data.get("fair_value", 0)
        cp = dcf_data.get("current_price", 0)
        if upside >= 30:
            s = 10
            parts.append(f"DCF乖離 +{upside:.0f}% (理論: ${fv:,.0f} vs 現在: ${cp:,.0f}) — 大幅な安全域")
        elif upside >= 15:
            s = 8
            parts.append(f"DCF乖離 +{upside:.0f}% (理論: ${fv:,.0f}) — 割安")
        elif upside >= 0:
            s = 5
            parts.append(f"DCF乖離 +{upside:.0f}% (理論: ${fv:,.0f}) — 概ね適正")
        elif upside >= -15:
            s = 3
            parts.append(f"DCF乖離 {upside:.0f}% (理論: ${fv:,.0f}) — やや割高")
        else:
            s = 1
            parts.append(f"DCF乖離 {upside:.0f}% (理論: ${fv:,.0f}) — 割高")
        total += _clamp(s)
        count += 1

    score = _clamp(total / max(count, 1))
    return {
        "layer": "Valuation",
        "score": score,
        "details": parts,
        "data_points": count,
    }


# ==========================================
# Layer 3: Technical（タイミング）
# ==========================================

def score_technical(technical: dict, sector: str = "") -> dict:
    """
    RSI, MA乖離率, ボリンジャーバンド位置, ボラティリティ, 出来高比率から
    エントリータイミングスコアを算出。
    sectorに応じたRSI閾値を自動選択。
    """
    _, _, _, tech_cfg, _ = resolve_sector_profile(sector)
    cfg = tech_cfg if tech_cfg else SCORING_CFG.get("technical", {})
    parts = []
    total = 0.0
    count = 0

    if not technical:
        return {"layer": "Technical", "score": 5.0, "details": ["テクニカルデータなし"], "data_points": 0}

    # RSI
    rsi = _safe(technical.get('rsi'))
    if rsi is not None:
        oversold  = cfg.get("rsi_oversold", 30)
        overbought = cfg.get("rsi_overbought", 70)
        if rsi <= oversold:
            s = 9
            parts.append(f"RSI {rsi} — 売られ過ぎ（買いシグナル）")
        elif rsi <= 45:
            s = 7
            parts.append(f"RSI {rsi} — やや売られ過ぎ")
        elif rsi <= 55:
            s = 5
            parts.append(f"RSI {rsi} — 中立")
        elif rsi <= overbought:
            s = 3
            parts.append(f"RSI {rsi} — やや過熱")
        else:
            s = 1
            parts.append(f"RSI {rsi} — 過熱（売りシグナル）")
        total += _clamp(s)
        count += 1

    # MA25 乖離率
    ma25 = _safe(technical.get('ma25_deviation'))
    if ma25 is not None:
        if ma25 <= -10:
            s = 9
            parts.append(f"MA25乖離 {ma25}% — 大幅下方乖離（反発期待）")
        elif ma25 <= -3:
            s = 7
            parts.append(f"MA25乖離 {ma25}% — 下方乖離")
        elif ma25 <= 3:
            s = 5
            parts.append(f"MA25乖離 {ma25}% — 移動平均近辺")
        elif ma25 <= 10:
            s = 3
            parts.append(f"MA25乖離 {ma25}% — 上方乖離")
        else:
            s = 1
            parts.append(f"MA25乖離 {ma25}% — 大幅上方乖離（過熱）")
        total += _clamp(s)
        count += 1

    # MA75 乖離率
    ma75 = _safe(technical.get('ma75_deviation'))
    if ma75 is not None:
        if ma75 <= -15:
            s = 9
            parts.append(f"MA75乖離 {ma75}% — 中期トレンド大幅下方乖離")
        elif ma75 <= -5:
            s = 7
            parts.append(f"MA75乖離 {ma75}% — 中期下方乖離")
        elif ma75 <= 5:
            s = 5
            parts.append(f"MA75乖離 {ma75}% — 中期トレンド近辺")
        elif ma75 <= 15:
            s = 3
            parts.append(f"MA75乖離 {ma75}% — 中期上方乖離")
        else:
            s = 1
            parts.append(f"MA75乖離 {ma75}% — 中期過熱")
        total += _clamp(s)
        count += 1

    # ボリンジャーバンド位置
    bb = _safe(technical.get('bb_position'))
    if bb is not None:
        if bb <= 10:
            s = 9
            parts.append(f"BB位置 {bb}% — 下限バンド付近（買い）")
        elif bb <= 30:
            s = 7
            parts.append(f"BB位置 {bb}% — 下方域")
        elif bb <= 70:
            s = 5
            parts.append(f"BB位置 {bb}% — 中央帯")
        elif bb <= 90:
            s = 3
            parts.append(f"BB位置 {bb}% — 上方域")
        else:
            s = 1
            parts.append(f"BB位置 {bb}% — 上限バンド付近（売り）")
        total += _clamp(s)
        count += 1

    # 出来高比率
    vr = _safe(technical.get('volume_ratio'))
    if vr is not None and vr > 0:
        if vr >= 2.0:
            s = 8
            parts.append(f"出来高比率 {vr}x — 異常出来高（注目）")
        elif vr >= 1.2:
            s = 6
            parts.append(f"出来高比率 {vr}x — やや活発")
        elif vr >= 0.8:
            s = 5
            parts.append(f"出来高比率 {vr}x — 通常")
        else:
            s = 3
            parts.append(f"出来高比率 {vr}x — 閑散")
        total += _clamp(s)
        count += 1

    score = _clamp(total / max(count, 1))
    return {
        "layer": "Technical",
        "score": score,
        "details": parts,
        "data_points": count,
    }


# ==========================================
# Layer 4: Qualitative（有報による定性分析）
# ==========================================


# ==========================================
# Technical Analyzer (v1.4 Swing Strategy Support)
# ==========================================

class TechnicalAnalyzer:
    """
    バックテストおよび日次分析のためのテクニカル判定クラス。
    Bounce/Breakout戦略のエントリー/エグジット判定を集約。
    """
    def __init__(self, daily_df):
        self.df = daily_df

    def get_latest(self):
        return self.df.iloc[-1]

    def check_rsi_condition(self, threshold: float, period: int = 9, condition: str = "below") -> bool:
        """RSIが閾値以下(below)か以上(above)かを判定"""
        # RSI計算はデータフェッチャー側で行われている前提だが、期間が違う場合再計算が必要
        # ここでは簡易的に既存の 'RSI' カラムがあればそれを使うが、
        # period=9指定などで厳密にやるなら再計算ロジックが必要。
        # v1.4では data_fetcher.py で RSI(9) も計算するようにするか、ここで計算する。
        # ここでは計算済みと仮定し、カラム名が 'RSI_9' などでない場合は 'RSI' (通常14) を使う妥協案か、
        # talib等で再計算する。依存関係を減らすため、pandasで簡易計算する。
        
        delta = self.df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        current_rsi = rsi.iloc[-1]
        if condition == "below":
            return current_rsi < threshold
        elif condition == "above":
            return current_rsi > threshold
        return False

    def check_bollinger_touch(self, sigma: float = 2.0, period: int = 20) -> tuple:
        """株価がボリンジャーバンド下限以下か、位置(%)を返す"""
        close = self.df['Close']
        ma = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = ma + (std * sigma)
        lower = ma - (std * sigma)
        
        current_close = close.iloc[-1]
        current_lower = lower.iloc[-1]
        
        is_touching_lower = current_close <= current_lower
        
        # BB Position %
        current_upper = upper.iloc[-1]
        if (current_upper - current_lower) == 0:
            pct = 0.5
        else:
            pct = (current_close - current_lower) / (current_upper - current_lower)
            
        return is_touching_lower, pct

    def check_ma_cross(self, fast_period: int = 5, slow_period: int = 25, lookback: int = 3) -> bool:
        """指定期間内(lookback)にゴールデンクロスが発生したか"""
        close = self.df['Close']
        ma_fast = close.rolling(window=fast_period).mean()
        ma_slow = close.rolling(window=slow_period).mean()
        
        # 直近 lookback 日分をチェック
        for i in range(lookback):
            idx = -(i + 1)
            prev_idx = -(i + 2)
            if abs(prev_idx) > len(self.df):
                break
                
            # GC: 前日 Fast <= Slow, 当日 Fast > Slow
            if ma_fast.iloc[prev_idx] <= ma_slow.iloc[prev_idx] and \
               ma_fast.iloc[idx] > ma_slow.iloc[idx]:
                return True
        return False
    
    def check_ma_alignment(self) -> bool:
        """
        パーフェクトオーダー (Price > MA5 > MA25 > MA75) を判定する (Momentum Bonus用)
        """
        try:
            if len(self.df) < 75:
                return False
                
            current = self.df.iloc[-1]
            
            # キャッシュまたは再計算
            ma5 = current.get('MA5')
            if ma5 is None or pd.isna(ma5):
                ma5 = self.df['Close'].rolling(5).mean().iloc[-1]
                
            ma25 = current.get('MA25')
            if ma25 is None or pd.isna(ma25):
                ma25 = self.df['Close'].rolling(25).mean().iloc[-1]
                
            ma75 = current.get('MA75')
            if ma75 is None or pd.isna(ma75):
                ma75 = self.df['Close'].rolling(75).mean().iloc[-1]
                
            if pd.isna(ma5) or pd.isna(ma25) or pd.isna(ma75):
                return False
                
            price = current['Close']
            # Price > MA5 > MA25 > MA75
            return price > ma5 > ma25 > ma75
        except Exception as e:
            logger.debug(f"MA Alignment Check Error: {e}")
            return False

    def check_volume_spike(self, multiplier: float = 1.3, period: int = 20) -> bool:
        """出来高急増判定"""
        vol = self.df['Volume']
        ma_vol = vol.rolling(window=period).mean()
        
        current_vol = vol.iloc[-1]
        return current_vol >= (ma_vol.iloc[-1] * multiplier)

    def check_high_breakout(self, period: int = 20) -> bool:
        """直近高値ブレイク判定"""
        close = self.df['Close']
        current_close = close.iloc[-1]
        # 当日を除く過去period日間の最高値
        past_high = close.iloc[-(period+1):-1].max()
        
        return current_close > past_high


# ==========================================
# Layer 4: Qualitative（有報による定性分析）
# ==========================================

def score_qualitative(yuho_data: dict) -> dict:
    """
    有報解析データ（リスクTOP3, 堀, R&D, 経営課題）からスコアを算出。
    有報データがない場合は 5.0（中立）を返す。
    """
    if not yuho_data or not yuho_data.get("available"):
        reason = yuho_data.get("reason", "有報データなし") if yuho_data else "有報データなし"
        return {
            "layer": "Qualitative",
            "score": 5.0,
            "details": [f"定性分析スキップ（{reason}）"],
            "data_points": 0,
        }

    parts = []
    total = 0.0
    count = 0

    # 堀（Moat）評価
    moat = yuho_data.get("moat", {})
    if isinstance(moat, dict) and moat.get("type") and moat.get("type") != "データなし":
        durability = moat.get("durability", "中")
        if durability == "高":
            s = 9
            parts.append(f"堀: {moat['type']} — 耐久性[高] → 長期優位性あり")
        elif durability == "中":
            s = 6
            parts.append(f"堀: {moat['type']} — 耐久性[中]")
        else:
            s = 3
            parts.append(f"堀: {moat['type']} — 耐久性[低] → 競争激化リスク")
        total += _clamp(s)
        count += 1

    # リスク評価（リスクが高いほど低スコア）
    risks = yuho_data.get("risk_top3", [])
    if isinstance(risks, list) and risks:
        high_count = sum(1 for r in risks if isinstance(r, dict) and r.get("severity") == "高")
        mid_count  = sum(1 for r in risks if isinstance(r, dict) and r.get("severity") == "中")

        if high_count >= 2:
            s = 2
            parts.append(f"リスク: 高severity {high_count}件 — 重大リスク集中")
        elif high_count == 1:
            s = 4
            parts.append(f"リスク: 高severity {high_count}件, 中 {mid_count}件")
        elif mid_count >= 2:
            s = 5
            parts.append(f"リスク: 中severity {mid_count}件 — 標準的リスク水準")
        else:
            s = 7
            parts.append(f"リスク: severity全体的に低い — 安定経営")
        total += _clamp(s)
        count += 1

        risk_names = [r.get("risk", "不明") for r in risks[:3]]
        parts.append(f"  主要リスク: {', '.join(risk_names)}")

    # R&D 注力分野（あれば加点）
    rd_focus = yuho_data.get("rd_focus", [])
    if isinstance(rd_focus, list) and rd_focus and isinstance(rd_focus[0], dict) and rd_focus[0].get("area", "") != "データなし":
        s = 7
        areas = [r.get("area", "") for r in rd_focus[:3]]
        parts.append(f"R&D注力: {', '.join(areas)} — 将来成長への投資あり")
        total += _clamp(s)
        count += 1

    # 経営陣トーン分析（management_tone）
    tone = yuho_data.get("management_tone", {})
    if isinstance(tone, dict) and tone.get("overall") and tone.get("overall") != "データなし":
        overall = tone.get("overall", "中立")
        if overall == "強気":
            s = 8
            parts.append(f"経営陣トーン: [強気] — 攻めの姿勢")
        elif overall == "中立":
            s = 5
            parts.append(f"経営陣トーン: [中立] — バランス型")
        elif overall == "慎重":
            s = 4
            parts.append(f"経営陣トーン: [慎重] — 守りの姿勢（リスク意識高）")
        else:  # 弱気
            s = 2
            parts.append(f"経営陣トーン: [弱気] — 防御的（警戒必要）")
        key_phrases = tone.get("key_phrases", [])
        if key_phrases:
            parts.append(f"  キーフレーズ: {', '.join(key_phrases[:3])}")
        total += _clamp(s)
        count += 1

    # 各項目が空（解析待ち）の場合は中立スコア 5.0 をベースにする
    if count == 0:
        return {
            "layer": "Qualitative",
            "score": 5.0,
            "details": ["有報/10-Kデータあり（詳細はAIレポートを参照）"],
            "data_points": 0,
        }

    score = _clamp(total / count)
    return {
        "layer": "Qualitative",
        "score": score,
        "details": parts,
        "data_points": count,
    }


# ==========================================
# スコアカード統合
# ==========================================

def generate_scorecard(metrics: dict, technical: dict, yuho_data: dict = None,
                       sector: str = "", dcf_data: dict = None,
                       macro_data: dict = None, buy_threshold: float = None) -> dict:
    """
    4軸スコアを一括算出し、統合スコアカードを生成する。
    buy_threshold が指定されている場合、その値をシグナル判定(BUY)に使用する。
    """
    fund = score_fundamental(metrics, sector=sector)
    valu = score_valuation(metrics, technical, sector=sector, dcf_data=dcf_data)
    tech = score_technical(technical, sector=sector)
    qual = score_qualitative(yuho_data)

    # セクター別ベースウェイトを取得
    _, _, _, _, sector_weights = resolve_sector_profile(sector)
    weights = dict(sector_weights)

    # 有報データがない場合は定性分析の重みを他に再配分
    if not yuho_data or not yuho_data.get("available"):
        q_share = weights.get("qualitative", 0.25)
        weights["fundamental"] += q_share * 0.4
        weights["valuation"]   += q_share * 0.3
        weights["technical"]   += q_share * 0.3
        weights["qualitative"] = 0.00

    # マクロ環境による重み補正 (v1.2)
    regime_label = ""
    if macro_data and macro_data.get("regime"):
        try:
            # マクロモジュールから補正値を取得
            try:
                from .macro_regime import get_weight_adjustments
            except (ImportError, ValueError):
                try:
                    from macro_regime import get_weight_adjustments
                except ImportError:
                    from src.macro_regime import get_weight_adjustments
            
            regime_label = macro_data["regime"]
            adj = get_weight_adjustments(regime_label, sector)
            
            # 補正を適用
            new_weights = weights.copy()
            for axis in new_weights:
                new_weights[axis] = max(0, new_weights[axis] + adj.get(axis, 0.0))
            
            # 正規化 (合計が1.0になるように)
            total_w = sum(new_weights.values())
            if total_w > 0:
                for axis in new_weights:
                    weights[axis] = round(new_weights[axis] / total_w, 3)
                
        except Exception as e:
            print(f"⚠️ マクロ重み適用エラー: {e}")

    # テクニカル指標の抽出
    ma25_dev = technical.get("ma25_deviation", 0) or 0
    ma75_dev = technical.get("ma75_deviation", 0) or 0
    rsi = technical.get("rsi", 50) or 50

    # --- Momentum Bonus Logic (v1.4.3 Remediated) ---
    # パーフェクトオーダー (Price > MA5 > MA25 > MA75) が確認されている場合
    if technical.get("perfect_order", False):
        momentum_bonus = 0.5
        tech["score"] = min(10.0, tech["score"] + momentum_bonus)
        if "details" not in tech:
            tech["details"] = []
        tech["details"].append(f"Momentum Bonus +{momentum_bonus} (Perfect Order Alignment)")

    total = _clamp(
        fund["score"] * weights["fundamental"] +
        valu["score"] * weights["valuation"] +
        tech["score"] * weights["technical"] +
        qual["score"] * weights["qualitative"]
    )

    # シグナル判定
    sig_cfg = _CFG.get("signals", {"BUY": {"min_score": 6.5}, "WATCH": {"min_score": 4}, "SELL": {"max_score": 3.5}})
    
    # buy_threshold が渡された場合は優先使用 (Regime Overrides対応)
    buy_limit = buy_threshold if buy_threshold is not None else sig_cfg.get("BUY", {}).get("min_score", 6.5)

    if total >= buy_limit:
        signal = "BUY"
    elif total <= sig_cfg.get("SELL", {}).get("max_score", 3.5):
        signal = "SELL"
    else:
        signal = "WATCH"

    # サマリーテキスト生成
    lines = [
        f"━━━ 📋 4軸スコアカード ━━━",
        f"📊 Fundamental (地力):     {fund['score']}/10  [データ{fund['data_points']}件]",
        f"💰 Valuation (割安度):     {valu['score']}/10  [データ{valu['data_points']}件]",
        f"⏱️  Technical (タイミング): {tech['score']}/10  [データ{tech['data_points']}件]",
        f"📋 Qualitative (定性):     {qual['score']}/10  [データ{qual['data_points']}件]",
        f"",
        f"🔢 総合スコア: {total}/10 → 🎯 {signal}",
    ]

    weight_str = f"地力{weights['fundamental']*100:.0f}%/割安{weights['valuation']*100:.0f}%/技術{weights['technical']*100:.0f}%/定性{weights['qualitative']*100:.0f}%"
    if regime_label:
        lines.append(f"(重み: {weight_str} | 🌍 {regime_label})")
    elif yuho_data and yuho_data.get("available"):
        lines.append(f"(重み: {weight_str})")
    else:
        lines.append(f"(重み: 地力{weights['fundamental']*100:.0f}%/割安{weights['valuation']*100:.0f}%/技術{weights['technical']*100:.0f}% — 有報なし)")

    return {
        "fundamental":  fund,
        "valuation":    valu,
        "technical":    tech,
        "qualitative":  qual,
        "total_score":  total,
        "signal":       signal,
        "summary_text": "\n".join(lines),
        "weights":      weights,
    }


def format_yuho_for_prompt(yuho_data: dict) -> str:
    """
    有報解析結果をGeminiプロンプトに注入するテキスト形式に変換。
    """
    if not yuho_data or not yuho_data.get("available"):
        return ""

    lines = ["【有価証券報告書分析】"]

    # 書類情報
    doc = yuho_data.get("doc_info", {})
    if doc:
        lines.append(f"提出者: {doc.get('filer_name', '不明')}")
        lines.append(f"対象期間: {doc.get('period_start', '?')} ～ {doc.get('period_end', '?')}")
        lines.append(f"提出日: {doc.get('submit_date', '?')}")
        lines.append("")

    # リスクTOP3
    risks = yuho_data.get("risk_top3", [])
    if isinstance(risks, list) and risks:
        lines.append("〈経営リスクTOP3〉")
        for i, r in enumerate(risks, 1):
            if isinstance(r, dict):
                lines.append(f"  {i}. [{r.get('severity', '?')}] {r.get('risk', '不明')}: {r.get('detail', '')}")
        lines.append("")

    # 堀
    moat = yuho_data.get("moat", {})
    if isinstance(moat, dict) and moat.get("type"):
        source_text = f" (源泉: {moat.get('source', '?')})" if moat.get("source") else ""
        lines.append(f"〈競争優位性（堂）〉 {moat.get('type', '不明')}{source_text} (耐久性: {moat.get('durability', '?')})")
        lines.append(f"  {moat.get('description', '')}")
        lines.append("")

    # 経営陣トーン
    tone = yuho_data.get("management_tone", {})
    if isinstance(tone, dict) and tone.get("overall"):
        lines.append(f"〈経営陣トーン〉 {tone.get('overall', '?')}")
        lines.append(f"  {tone.get('detail', '')}")
        key_phrases = tone.get("key_phrases", [])
        if isinstance(key_phrases, list) and key_phrases:
            lines.append(f"  キーフレーズ: {', '.join(key_phrases[:3])}")
        lines.append("")

    # R&D
    rd = yuho_data.get("rd_focus", [])
    if isinstance(rd, list) and rd:
        lines.append("〈R&D注力分野〉")
        for item in rd[:5]:
            if isinstance(item, dict):
                lines.append(f"  ・{item.get('area', '?')}: {item.get('detail', '')}")
        lines.append("")

    # 経営課題
    mc = yuho_data.get("management_challenges")
    if mc:
        lines.append(f"〈経営課題〉{mc}")
        lines.append("")

    # サマリー
    summary = yuho_data.get("summary")
    if summary:
        lines.append(f"〈アナリスト要約〉{summary}")

    return "\n".join(lines)


# ==========================================
# セルフテスト
# ==========================================

if __name__ == "__main__":
    print("=== analyzers.py セルフテスト ===\n")

    # テスト用サンプルデータ（トヨタ風）
    sample_metrics = {
        'roe': 12.5,
        'op_margin': 8.3,
        'net_margin': 6.1,
        'equity_ratio': 38.5,
        'cf_quality': 1.4,
        'rd_ratio': 3.8,
        'per': 10.2,
        'pbr': 1.1,
        'dividend_yield': 2.8,
        'revenue_growth': 5.2,
        'earnings_growth': 8.1,
    }

    sample_technical = {
        'current_price': 2850,
        'ma25_deviation': -2.1,
        'ma75_deviation': 3.5,
        'rsi': 45.2,
        'bb_position': 35.0,
        'volatility': 22.5,
        'volume_ratio': 1.1,
        'analyst_target': 3200,
    }

    sample_yuho = {
        'available': True,
        'doc_info': {
            'filer_name': 'トヨタ自動車株式会社',
            'period_start': '2024-04-01',
            'period_end': '2025-03-31',
            'submit_date': '2025-06-20',
        },
        'risk_top3': [
            {'risk': 'EV転換リスク', 'detail': '電気自動車への移行遅れが競争力に影響', 'severity': '高'},
            {'risk': '為替変動リスク', 'detail': '円安是正が利益を圧迫する可能性', 'severity': '中'},
            {'risk': 'サプライチェーン', 'detail': '半導体不足の再発リスク', 'severity': '中'},
        ],
        'moat': {
            'type': '技術/ブランド',
            'source': 'ハイブリッド特許群26,000件超、世界販売台1,000万台超のブランド基盤',
            'description': 'ハイブリッド技術で世界トップ。トヨタブランドの信頼性は圧倒的。',
            'durability': '高',
        },
        'management_tone': {
            'overall': '慎重',
            'detail': 'EV転換に対して「全方位戦略」を強調し、性急な転換には慎重な姿勢。',
            'key_phrases': ['全方位戦略', 'カーボンニュートラル', '持続的成長'],
        },
        'rd_focus': [
            {'area': '水素エンジン', 'detail': '次世代燃料電池車の実用化'},
            {'area': '自動運転', 'detail': 'Level 4 自動運転の商用化'},
        ],
        'management_challenges': 'カーボンニュートラル達成に向けた全方位戦略の実行と、ソフトウェア定義車両への転換。',
        'summary': 'トヨタは依然として世界最大の自動車メーカーとしての地位を維持。EV転換は遅れているが、全固体電池技術で巻き返しを図る。',
    }

    # テスト実行
    test_sector = "Consumer Cyclical"  # トヨタ = 自動車 = Valueプロファイル

    print(f"--- セクタープロファイル解決 ---")
    profile_name, f_cfg, v_cfg, _, _ = resolve_sector_profile(test_sector)
    print(f"  {test_sector} => [{profile_name}]")
    print(f"  ROE閾値: {f_cfg.get('roe_good')}, PER閾値: {v_cfg.get('per_cheap')}")
    profile_name2, _, _, _, _ = resolve_sector_profile("Technology")
    print(f"  Technology => [{profile_name2}]")
    profile_name3, _, _, _, _ = resolve_sector_profile("Financial Services")
    print(f"  Financial Services => [{profile_name3}]")

    print("\n--- Fundamental (セクター対応) ---")
    fund = score_fundamental(sample_metrics, sector=test_sector)
    print(f"  Score: {fund['score']}/10 ({fund['data_points']}指標)")
    for d in fund['details']:
        print(f"    {d}")

    print("\n--- Valuation (セクター対応) ---")
    valu = score_valuation(sample_metrics, sample_technical, sector=test_sector)
    print(f"  Score: {valu['score']}/10 ({valu['data_points']}指標)")
    for d in valu['details']:
        print(f"    {d}")

    print("\n--- Technical ---")
    tech = score_technical(sample_technical)
    print(f"  Score: {tech['score']}/10 ({tech['data_points']}指標)")
    for d in tech['details']:
        print(f"    {d}")

    print("\n--- Qualitative (トーン分析対応) ---")
    qual = score_qualitative(sample_yuho)
    print(f"  Score: {qual['score']}/10 ({qual['data_points']}指標)")
    for d in qual['details']:
        print(f"    {d}")

    print("\n--- 統合スコアカード ---")
    card = generate_scorecard(sample_metrics, sample_technical, sample_yuho, sector=test_sector)
    print(card['summary_text'])

    print("\n--- 有報なしのケース ---")
    card_no_yuho = generate_scorecard(sample_metrics, sample_technical, None, sector=test_sector)
    print(card_no_yuho['summary_text'])

    # バリデーション: 全スコアが 0–10 の範囲内
    print("\n--- バリデーション ---")
    all_scores = [
        fund['score'], valu['score'], tech['score'], qual['score'],
        card['total_score'], card_no_yuho['total_score'],
    ]
    valid = all(0 <= s <= 10 for s in all_scores)
    print(f"  {'✅' if valid else '❌'} 全スコアが 0–10 範囲内: {all_scores}")

    print("\n=== テスト完了 ===")

# エクスポート
__all__ = [
    "score_fundamental",
    "score_valuation",
    "score_technical",
    "score_qualitative",
    "generate_scorecard",
    "format_yuho_for_prompt",
    "resolve_sector_profile",
    "TechnicalAnalyzer",
]
