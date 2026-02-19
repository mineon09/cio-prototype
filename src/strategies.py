import pandas as pd
import numpy as np
from .analyzers import TechnicalAnalyzer

# ==========================================
# Strategy Pattern Implementation
# ==========================================

class BaseStrategy:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.s_cfg = config.get("strategies", {}).get(name, {}) if name != "long" else {}

    def analyze_entry(self, row: pd.Series, daily_data: pd.DataFrame, ta: TechnicalAnalyzer) -> dict:
        """
        詳細なエントリー分析を行う
        Returns:
            dict: {
                "is_entry": bool,
                "details": list[str], # ログ用メッセージリスト
                "metrics": dict       # 数値データ (rsi, ma_gap, etc.)
            }
        """
        if not self.s_cfg.get("enabled", True):
             return {"is_entry": False, "details": ["Strategy Disabled (via config)"], "metrics": {}}
        return {"is_entry": False, "details": [], "metrics": {}}

    def should_buy(self, row: pd.Series, daily_data: pd.DataFrame, ta: TechnicalAnalyzer) -> bool:
        """
        エントリー判定ロジック (analyze_entryのラッパー)
        Returns:
            bool: エントリーすべきならTrue
        """
        if not self.s_cfg.get("enabled", True):
             return False
        result = self.analyze_entry(row, daily_data, ta)
        return result["is_entry"]

    def should_sell(self, row: pd.Series, daily_data: pd.DataFrame, ta: TechnicalAnalyzer, ctx: dict) -> tuple[bool, str, float]:
        """
        エグジット判定ロジック
        Args:
            row: バックテストの現在行 (Series)
            daily_data: 日足データ全体 (DataFrame)
            ta: TechnicalAnalyzerインスタンス
            ctx: トレードコンテキスト (entry_price, entry_date, etc.)
        Returns:
            (should_sell, reason, exit_price)
        """
        return False, "", 0.0

    def get_buy_threshold(self, regime: str) -> float:
        """レジームに応じたBUY閾値を返すヘルパー"""
        overrides = self.config.get("signals", {}).get("BUY", {}).get("regime_overrides", {})
        default = self.config.get("signals", {}).get("BUY", {}).get("min_score", 6.5)
        return overrides.get(regime, {}).get("min_score", default)


class LongStrategy(BaseStrategy):
    """
    中長期トレンドフォロー戦略 (Fundamental + Valuation重視)
    """
    def analyze_entry(self, row, daily_data, ta) -> dict:
        details = []
        metrics = {}
        
        # Premium Quality Override
        pq_cfg = self.config.get("signals", {}).get("BUY", {}).get("premium_quality_override", {})
        min_score = self.get_buy_threshold(row.get('regime', 'NEUTRAL'))
        fund_score = row.get("fundamental", 0)
        
        entry_min_score = min_score
        is_premium = False
        if pq_cfg.get("enabled", False) and fund_score >= pq_cfg.get("min_fundamental", 8.0):
            entry_min_score = min(entry_min_score, pq_cfg.get("min_score", 5.5))
            is_premium = True
            details.append(f"Premium Quality Override Active (Fund: {fund_score} >= 8.0)")

        metrics["score"] = row['score']
        metrics["min_score"] = entry_min_score
        
        # Check Score
        score_ok = row['score'] >= entry_min_score
        details.append(f"Score: {row['score']:.1f} (Threshold: {entry_min_score}) -> {'OK' if score_ok else 'NG'}")

        # Fundamental Min Check
        fund_min = self.config.get("signals", {}).get("BUY", {}).get("min_fundamental", 0.0)
        fund_ok = True
        if fund_score < fund_min and not is_premium:
            fund_ok = False
            details.append(f"Fundamental: {fund_score:.1f} (Min: {fund_min}) -> NG")
        
        is_entry = score_ok and fund_ok
        return {"is_entry": is_entry, "details": details, "metrics": metrics}

    def should_sell(self, row, daily_data, ta, ctx) -> tuple[bool, str, float]:
        # Watch Zone Exit: スコア低迷が続いたらエグジット
        wz_cfg = self.config.get("exit_strategy", {}).get("long", {}).get("watch_zone_exit", {})
        if wz_cfg.get("enabled", False):
            if row['score'] < wz_cfg.get("score_threshold", 4.5):
                ctx['low_score_months'] = ctx.get('low_score_months', 0) + 1
            else:
                ctx['low_score_months'] = 0
            
            if ctx.get('low_score_months', 0) >= wz_cfg.get("consecutive_months", 3):
                return True, "Watch Zone Exit", row['price']
        
        # 通常のスコア悪化エグジット
        sig_cfg = self.config.get("signals", {}).get("SELL", {"max_score": 3.5})
        if row['score'] <= sig_cfg.get("max_score", 3.5):
            return True, "Signal SELL", row['price']
            
        return False, "", 0.0


class BounceStrategy(BaseStrategy):
    """
    短期逆張り（リバウンド）戦略
    RSI <= 32 かつ BB下限タッチでエントリー
    """
    def analyze_entry(self, row, daily_data, ta) -> dict:
        entry_cfg = self.s_cfg.get("entry", {})
        details = []
        metrics = {}
        
        # 1. 基礎フィルター (Fundamental / Regime)
        fund_score = row.get('fundamental', 0)
        fund_min = entry_cfg.get("fundamental_min", 5.0)
        metrics["fundamental"] = fund_score
        
        if fund_score < fund_min:
             details.append(f"Fundamental: {fund_score:.1f} (Min: {fund_min}) -> NG")
             return {"is_entry": False, "details": details, "metrics": metrics}
             
        regime = row.get('regime')
        enabled_regimes = self.s_cfg.get("enabled_regimes", [])
        if regime not in enabled_regimes:
             details.append(f"Regime: {regime} (Allowed: {enabled_regimes}) -> NG")
             return {"is_entry": False, "details": details, "metrics": metrics}
        
        # 2. テクニカルフィルター
        # RSI 売られすぎ
        rsi_val = ta.get_latest().get('RSI_9', 0) # TechnicalAnalyzer実装に依存
        # work around if get_latest not returning what we expect or we recalculate?
        # ta.check_rsi_condition already does calculation. use that.
        rsi_threshold = entry_cfg.get("rsi_threshold", 32)
        rsi_ok = ta.check_rsi_condition(rsi_threshold, condition="below")
        # Retry getting value for logging if possible, assuming TA has cache or calculating it
        # Try to get value from daily_data if available or rely on TA
        
        # For logging purposes, let's assume we can get it or just log status
        details.append(f"RSI(9) < {rsi_threshold}: {'OK' if rsi_ok else 'NG'}")
        
        # BB 下限タッチ
        bb_ok, bb_pct = ta.check_bollinger_touch(sigma=entry_cfg.get("bb_std", 2.0))
        details.append(f"BB Touch: {'OK' if bb_ok else 'NG'} (Position: {bb_pct:.1%})")
        
        # 出来高急増 (Selling Climax)
        vol_mult = entry_cfg.get("volume_multiplier", 1.3)
        vol_ok = ta.check_volume_spike(multiplier=vol_mult)
        details.append(f"Volume Spike (x{vol_mult}): {'OK' if vol_ok else 'NG'}")
        
        # 長期トレンドフィルター (MA75より上にあること = 上昇トレンド中の押し目買い)
        ma75 = daily_data['Close'].rolling(75).mean().iloc[-1]
        ma75_ok = True
        price = daily_data['Close'].iloc[-1]
        if not pd.isna(ma75):
             ma75_ok = price > ma75
             details.append(f"Trend (Price > MA75): {'OK' if ma75_ok else 'NG'} ({price:.1f} vs {ma75:.1f})")
        else:
             ma75_ok = False # Data missing -> Safety first
             details.append("Trend: Data Missing -> NG")

        is_entry = rsi_ok and bb_ok and vol_ok and ma75_ok
        return {"is_entry": is_entry, "details": details, "metrics": metrics}

    def should_sell(self, row, daily_data, ta, ctx) -> tuple[bool, str, float]:
        exit_cfg = self.s_cfg.get("exit", {})
        price = row['price']
        buy_price = ctx['buy_price']
        entry_atr = ctx.get('entry_atr', 0)
        
        # 1. Hard Stop (損切り) - ATR優先
        stop_price = 0.0
        atr_sl_mult = exit_cfg.get("stop_loss_atr_multiplier", 0.0)
        
        if entry_atr and entry_atr > 0 and atr_sl_mult > 0:
            stop_price = buy_price - (entry_atr * atr_sl_mult)
            if row.get('low', price) <= stop_price:
                return True, f"ATR Stop (x{atr_sl_mult})", stop_price
        else:
            stop_pct = exit_cfg.get("hard_stop_pct", -2.5)
            stop_price = buy_price * (1 + stop_pct/100)
            if row.get('low', price) <= stop_price:
                return True, f"Hard Stop ({stop_pct}%)", stop_price
            
        # 2. Time Stop (期間切れ)
        # エントリーからの経過日数
        start_ts = pd.Timestamp(ctx['entry_date'])
        end_ts = pd.Timestamp(row['date'])
        # daily_dataのインデックスもTimestampであることを前提とするか、安全に変換してカウント
        mask = (daily_data.index >= start_ts) & (daily_data.index <= end_ts)
        bars_held = max(0, mask.sum() - 1)
        if bars_held >= exit_cfg.get("time_stop_bars", 7):
            condition = exit_cfg.get("time_stop_condition", "loss_only")
            if condition == "always" or (price < buy_price):
                return True, f"Time Stop ({bars_held} days)", price
                
        # 3. Take Profit (利確) - ATR優先
        tp_price = 0.0
        atr_tp_mult = exit_cfg.get("take_profit_atr_multiplier", 0.0)
        
        if entry_atr and entry_atr > 0 and atr_tp_mult > 0:
            tp_price = buy_price + (entry_atr * atr_tp_mult)
            if row.get('high', price) >= tp_price:
                return True, f"ATR Profit (x{atr_tp_mult})", tp_price
        else:
            tp_pct = exit_cfg.get("take_profit_pct", 5.0)
            tp_price = buy_price * (1 + tp_pct/100)
            if row.get('high', price) >= tp_price:
                return True, f"Take Profit ({tp_pct}%)", tp_price
            
        # 4. ATR Trailing Stop
        # 一定以上利益が出たらトレーリングストップを発動
        activation = exit_cfg.get("atr_trailing_activation_pct", 2.0)
        max_profit_pct = (ctx['trailing_high'] - buy_price) / buy_price * 100
        
        if max_profit_pct >= activation:
            atr = ctx.get('entry_atr', 0)
            if atr and atr > 0:
                stop = ctx['trailing_high'] - (atr * exit_cfg.get("atr_trailing_multiplier", 1.5))
                if row.get('low', price) <= stop:
                    return True, "ATR Trailing", stop
        
        # 5. Technical Exit (RSI過熱感)
        if ta.check_rsi_condition(exit_cfg.get("rsi_exit_threshold", 65), condition="above"):
            return True, "Technical Exit (RSI)", price

        return False, "", 0.0


class BreakoutStrategy(BaseStrategy):
    """
    ブレイクアウト戦略 (順張り)
    直近高値更新 + MAゴールデンクロス + 出来高増
    """
    def analyze_entry(self, row, daily_data, ta) -> dict:
        entry_cfg = self.s_cfg.get("entry", {})
        details = []
        metrics = {}
        
        fund_score = row.get('fundamental', 0)
        fund_min = entry_cfg.get("fundamental_min", 5.0)
        metrics["fundamental"] = fund_score

        if fund_score < fund_min:
             details.append(f"Fundamental: {fund_score:.1f} (Min: {fund_min}) -> NG")
             return {"is_entry": False, "details": details, "metrics": metrics}
             
        regime = row.get('regime')
        enabled_regimes = self.s_cfg.get("enabled_regimes", [])
        if regime not in enabled_regimes:
             details.append(f"Regime: {regime} (Allowed: {enabled_regimes}) -> NG")
             return {"is_entry": False, "details": details, "metrics": metrics}
            
        # ゴールデンクロス (直近N日)
        gc_days = entry_cfg.get("gc_lookback_days", 3)
        gc_ok = ta.check_ma_cross(lookback=gc_days)
        details.append(f"Golden Cross (Lookback {gc_days}d): {'OK' if gc_ok else 'NG'}")
        
        # 20日高値更新
        break_ok = ta.check_high_breakout(period=20)
        details.append(f"High Breakout (20d): {'OK' if break_ok else 'NG'}")
        
        # 出来高確認
        vol_mult = entry_cfg.get("volume_multiplier", 1.5)
        vol_ok = ta.check_volume_spike(multiplier=vol_mult)
        details.append(f"Volume Spike (x{vol_mult}): {'OK' if vol_ok else 'NG'}")
        
        # MA75フィルター
        ma75 = daily_data['Close'].rolling(75).mean().iloc[-1]
        ma75_ok = True
        price = daily_data['Close'].iloc[-1]
        
        if not pd.isna(ma75):
            ma75_ok = price > ma75
            details.append(f"Trend (Price > MA75): {'OK' if ma75_ok else 'NG'} ({price:.1f} vs {ma75:.1f})")
        else:
            ma75_ok = False # Data missing -> Safety first
            details.append("Trend: Data Missing -> NG (Safety default)")
        
        is_entry = gc_ok and break_ok and vol_ok and ma75_ok
        return {"is_entry": is_entry, "details": details, "metrics": metrics}

    def should_sell(self, row, daily_data, ta, ctx) -> tuple[bool, str, float]:
        exit_cfg = self.s_cfg.get("exit", {})
        price = row['price']
        buy_price = ctx['buy_price']
        entry_atr = ctx.get('entry_atr', 0)
        
        # 1. Hard Stop - ATR優先
        stop_price = 0.0
        atr_sl_mult = exit_cfg.get("stop_loss_atr_multiplier", 0.0)
        
        if entry_atr and entry_atr > 0 and atr_sl_mult > 0:
            stop_price = buy_price - (entry_atr * atr_sl_mult)
            if row.get('low', price) <= stop_price:
                return True, f"ATR Stop (x{atr_sl_mult})", stop_price
        else:
            stop_pct = exit_cfg.get("hard_stop_pct", -3.0)
            stop_price = buy_price * (1 + stop_pct/100)
            if row.get('low', price) <= stop_price:
                return True, f"Hard Stop ({stop_pct}%)", stop_price
            
        # 2. Time Stop
        start_ts = pd.Timestamp(ctx['entry_date'])
        end_ts = pd.Timestamp(row['date'])
        mask = (daily_data.index >= start_ts) & (daily_data.index <= end_ts)
        bars_held = max(0, mask.sum() - 1)
        if bars_held >= exit_cfg.get("time_stop_bars", 15):
            if price < buy_price:
                return True, f"Time Stop ({bars_held} days)", price
                
        # 3. Take Profit - ATR優先
        tp_price = 0.0
        atr_tp_mult = exit_cfg.get("take_profit_atr_multiplier", 0.0)
        
        if entry_atr and entry_atr > 0 and atr_tp_mult > 0:
            tp_price = buy_price + (entry_atr * atr_tp_mult)
            if row.get('high', price) >= tp_price:
                return True, f"ATR Profit (x{atr_tp_mult})", tp_price
        else:
            tp_pct = exit_cfg.get("take_profit_pct", 8.0)
            tp_price = buy_price * (1 + tp_pct/100)
            if row.get('high', price) >= tp_price:
                return True, f"Take Profit ({tp_pct}%)", tp_price
            
        # 4. Dead Cross Exit (MA5 < MA25)
        # トレンド終了を示唆
        if exit_cfg.get("exit_on_death_cross", True):
            ma5 = daily_data['Close'].rolling(5).mean().iloc[-1]
            ma25 = daily_data['Close'].rolling(25).mean().iloc[-1]
            if not pd.isna(ma5) and not pd.isna(ma25) and ma5 < ma25:
                return True, "Technical Exit (Dead Cross)", price

        # ATR Trailing Stop (Added per review)
        activation = exit_cfg.get("atr_trailing_activation_pct", 3.0)
        max_profit_pct = (ctx['trailing_high'] - buy_price) / buy_price * 100
        
        if max_profit_pct >= activation:
            atr = ctx.get('entry_atr', 0)
            if atr and atr > 0:
                stop = ctx['trailing_high'] - (atr * exit_cfg.get("atr_trailing_multiplier", 1.5))
                if row.get('low', price) <= stop:
                    return True, "ATR Trailing", stop

        return False, "", 0.0
