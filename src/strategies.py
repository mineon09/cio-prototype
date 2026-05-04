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

    def should_sell(self, row: pd.Series, past_slice: pd.DataFrame, ta: TechnicalAnalyzer, ctx: dict) -> tuple[bool, str, float]:
        """
        エグジット判定ロジック
        Args:
            row: バックテストの現在行 (Series)
            past_slice: PITスライス済み日足データ (DataFrame)
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
        fund_val = row.get("fundamental", 0)
        fund_score = float(fund_val) if isinstance(fund_val, (int, float)) else fund_val.get('score', 0) if isinstance(fund_val, dict) else 0
        
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

    def should_sell(self, row, past_slice, ta, ctx) -> tuple[bool, str, float]:
        long_cfg = self.config.get("exit_strategy", {}).get("long", {})
        price = row['price']
        buy_price = ctx.get('buy_price', price)
        trailing_high = ctx.get('trailing_high', price)
        entry_atr = ctx.get('entry_atr', 0)

        # --- 1. 損切り (Hard Stop / ATR Stop) ---
        atr_sl_mult = long_cfg.get("stop_loss_atr_multiplier", 2.0)
        if entry_atr and entry_atr > 0 and atr_sl_mult > 0:
            stop_price = buy_price - (entry_atr * atr_sl_mult)
            low = row.get('low', price)
            if isinstance(low, (int, float)) and low <= stop_price:
                return True, f"ATR Stop (x{atr_sl_mult})", stop_price
        else:
            # 固定%損切り（config未設定時: -12%）
            fixed_stop_pct = long_cfg.get("fixed_stop_loss_pct", -12.0)
            if fixed_stop_pct and (price - buy_price) / buy_price * 100 <= fixed_stop_pct:
                return True, f"Hard Stop ({fixed_stop_pct}%)", price

        # --- 2. 利確トレーリングストップ（ATRベース）---
        # 一定の利益（デフォルト8%）が出たら発動
        activation_pct = long_cfg.get("atr_trailing_activation_pct", 8.0)
        atr_trail_mult = long_cfg.get("trailing_stop_atr_multiplier", 3.0)
        gain_pct = (trailing_high - buy_price) / buy_price * 100 if buy_price > 0 else 0

        if gain_pct >= activation_pct and entry_atr and entry_atr > 0 and atr_trail_mult > 0:
            trail_stop = trailing_high - (entry_atr * atr_trail_mult)
            low = row.get('low', price)
            if isinstance(low, (int, float)) and low <= trail_stop:
                return True, f"Trailing Stop (gain={gain_pct:.1f}%, x{atr_trail_mult})", trail_stop

        # --- 3. 固定利確（config で take_profit_pct が設定されている場合）---
        tp_pct = long_cfg.get("take_profit_pct", 0.0)
        if tp_pct > 0:
            tp_price = buy_price * (1 + tp_pct / 100)
            high = row.get('high', price)
            if isinstance(high, (int, float)) and high >= tp_price:
                return True, f"Take Profit ({tp_pct}%)", tp_price

        # --- 4. Watch Zone Exit: スコア低迷が続いたらエグジット ---
        wz_cfg = long_cfg.get("watch_zone_exit", {})
        if wz_cfg.get("enabled", False):
            if row['score'] < wz_cfg.get("score_threshold", 4.5):
                ctx['low_score_months'] = ctx.get('low_score_months', 0) + 1
            else:
                ctx['low_score_months'] = 0

            if ctx.get('low_score_months', 0) >= wz_cfg.get("consecutive_months", 3):
                return True, "Watch Zone Exit", price

        # --- 5. 通常のスコア悪化エグジット ---
        sig_cfg = self.config.get("signals", {}).get("SELL", {"max_score": 3.5})
        if row['score'] <= sig_cfg.get("max_score", 3.5):
            return True, "Signal SELL", price

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
        fund_val = row.get('fundamental', 0)
        fund_score = float(fund_val) if isinstance(fund_val, (int, float)) else fund_val.get('score', 0) if isinstance(fund_val, dict) else 0
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
        # PIT: バックテスト日以前のデータのみを使用
        # PIT: バックテスト日以前のデータのみを使用 (daily_dataは既にスライス済みのpast_slice)
        ma75 = daily_data['Close'].rolling(75).mean().iloc[-1]
        price = daily_data['Close'].iloc[-1]
        if not pd.isna(ma75):
             ma75_ok = price > ma75
             details.append(f"Trend (Price > MA75): {'OK' if ma75_ok else 'NG'} ({price:.1f} vs {ma75:.1f})")
        else:
             ma75_ok = False # Data missing -> Safety first
             details.append("Trend: Data Missing -> NG")

        # スコアリングモード: LLMが重みを提案できる構造（config で有効化）
        # デフォルトは従来の AND 条件
        if entry_cfg.get("scoring_mode", False):
            weights = entry_cfg.get("scoring_weights", {
                "rsi": 1.0, "bb": 1.5, "vol": 0.8, "ma75": 2.0
            })
            score = (
                (rsi_ok * weights.get("rsi", 1.0)) +
                (bb_ok  * weights.get("bb",  1.5)) +
                (vol_ok * weights.get("vol", 0.8)) +
                (ma75_ok * weights.get("ma75", 2.0))
            )
            threshold = entry_cfg.get("scoring_threshold", 3.5)
            is_entry = score >= threshold
            details.append(f"Score: {score:.2f} / Threshold: {threshold} -> {'OK' if is_entry else 'NG'}")
            metrics["entry_score"] = score
            metrics["score_threshold"] = threshold
        else:
            is_entry = rsi_ok and bb_ok and vol_ok and ma75_ok
        return {"is_entry": is_entry, "details": details, "metrics": metrics}

    def should_sell(self, row, past_slice, ta, ctx) -> tuple[bool, str, float]:
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
        mask = (past_slice.index >= start_ts) & (past_slice.index <= end_ts)
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
        
        fund_val = row.get('fundamental', 0)
        fund_score = float(fund_val) if isinstance(fund_val, (int, float)) else fund_val.get('score', 0) if isinstance(fund_val, dict) else 0
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
        
        # 20日高値更新 (TA側の高値ベース判定)
        break_ok = ta.check_high_breakout(period=20)
        details.append(f"High Breakout (20d): {'OK' if break_ok else 'NG'}")
        
        # 陽線確認 (偽ブレイクアウト排除: 上ヒゲ・陰線スパイクを除外)
        if 'Open' in daily_data.columns:
            open_price = daily_data['Open'].iloc[-1]
            close_price = daily_data['Close'].iloc[-1]
            is_bullish = close_price > open_price
        else:
            is_bullish = True  # Openがない場合はスキップ
        
        if entry_cfg.get("require_bullish_close", True):
            details.append(f"Bullish Close: {'OK' if is_bullish else 'NG'}")
        
        # 終値ベースの20日高値更新 (ヒゲ先ブレイクの排除)
        if len(daily_data) >= 21 and 'High' in daily_data.columns:
            recent_high_20d = daily_data['High'].iloc[-21:-1].max()
            close_break_ok = daily_data['Close'].iloc[-1] > recent_high_20d
        else:
            close_break_ok = break_ok  # データ不足時はTA側の判定をそのまま使用
        details.append(f"Close Breakout (20d): {'OK' if close_break_ok else 'NG'}")
        
        # 出来高確認
        vol_mult = entry_cfg.get("volume_multiplier", 1.5)
        vol_ok = ta.check_volume_spike(multiplier=vol_mult)
        details.append(f"Volume Spike (x{vol_mult}): {'OK' if vol_ok else 'NG'}")
        
        # MA75フィルター
        # PIT: バックテスト日以前のデータのみを使用 (daily_dataは既にスライス済みのpast_slice)
        ma75 = daily_data['Close'].rolling(75).mean().iloc[-1]
        price = daily_data['Close'].iloc[-1]
        
        if not pd.isna(ma75):
            ma75_ok = price > ma75
            details.append(f"Trend (Price > MA75): {'OK' if ma75_ok else 'NG'} ({price:.1f} vs {ma75:.1f})")
        else:
            ma75_ok = False # Data missing -> Safety first
            details.append("Trend: Data Missing -> NG (Safety default)")
        
        # ADX強度確認 (有意なトレンド)
        adx_ok, adx_val = ta.check_adx_strength(threshold=25)
        details.append(f"ADX Trend (>25): {'OK' if adx_ok else 'NG'} (Val: {adx_val:.1f})")
        
        # CMF資金フロー確認 (ADXラグの補完)
        cmf_ok, cmf_val = ta.check_cmf(period=20)
        details.append(f"CMF (>0.05): {'OK' if cmf_ok else 'NG'} (Val: {cmf_val:.3f})")
        
        # ATR%レンジ相場フィルター（閾値は config.entry.atr_pct_min で設定可能、デフォルト 1.0%）
        atr_pct_min = entry_cfg.get("atr_pct_min", 1.0)
        atr_pct_ok, atr_pct_val = ta.check_atr_pct(period=14, min_pct=atr_pct_min)
        details.append(f"ATR% (>{atr_pct_min}%): {'OK' if atr_pct_ok else 'NG'} (Val: {atr_pct_val:.2f}%)")

        
        # エントリー条件の再構築
        # 必須: 終値ブレイクアウト + 陽線 + MA75より上 + ボラ十分(ATR%) + トレンド確認(ADX or CMF)
        # 加点(いずれか必須): 出来高スパイク もしくは 最近のGC
        bullish_filter = is_bullish if entry_cfg.get("require_bullish_close", True) else True
        # スコアリングモード: LLMが重みを提案できる構造（config で有効化）
        # デフォルトは従来の AND/OR 複合条件
        if entry_cfg.get("scoring_mode", False):
            weights = entry_cfg.get("scoring_weights", {
                "close_break": 2.5, "bullish": 1.0, "ma75": 2.0,
                "atr_pct": 1.5, "adx": 1.2, "cmf": 1.0, "vol": 0.8, "gc": 0.6
            })
            score = (
                (close_break_ok  * weights.get("close_break", 2.5)) +
                (bullish_filter  * weights.get("bullish", 1.0)) +
                (ma75_ok         * weights.get("ma75", 2.0)) +
                (atr_pct_ok      * weights.get("atr_pct", 1.5)) +
                (adx_ok          * weights.get("adx", 1.2)) +
                (cmf_ok          * weights.get("cmf", 1.0)) +
                (vol_ok          * weights.get("vol", 0.8)) +
                (gc_ok           * weights.get("gc", 0.6))
            )
            threshold = entry_cfg.get("scoring_threshold", 6.0)
            is_entry = score >= threshold
            details.append(f"Score: {score:.2f} / Threshold: {threshold} -> {'OK' if is_entry else 'NG'}")
            metrics["entry_score"] = score
            metrics["score_threshold"] = threshold
        else:
            is_entry = close_break_ok and bullish_filter and ma75_ok and atr_pct_ok and (adx_ok or cmf_ok) and (vol_ok or gc_ok)
        
        return {"is_entry": is_entry, "details": details, "metrics": metrics}

    def should_sell(self, row, past_slice, ta, ctx) -> tuple[bool, str, float]:
        exit_cfg = self.s_cfg.get("exit", {})
        price = row['price']
        buy_price = ctx['buy_price']
        
        # entry_atr はエントリー時点のATR（初期ストップ用）
        entry_atr = ctx.get('entry_atr', price * 0.02)  # fallback
        
        # past_slice から最新ATRを計算 (Chandelier Exit用)
        if 'High' in past_slice.columns and 'Low' in past_slice.columns and len(past_slice) >= 15:
            recent_high = past_slice['High'].iloc[-14:]
            recent_low = past_slice['Low'].iloc[-14:]
            recent_close = past_slice['Close'].iloc[-15:-1]
            tr1 = recent_high - recent_low
            tr2 = (recent_high - recent_close.values).abs()
            tr3 = (recent_low - recent_close.values).abs()
            current_atr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).mean()
        else:
            current_atr = entry_atr

        trailing_high = ctx.get('trailing_high', price)
        gain_pct = (trailing_high - buy_price) / buy_price * 100
        
        # 保有日数計算
        start_ts = pd.Timestamp(ctx['entry_date'])
        end_ts = pd.Timestamp(row['date'])
        mask = (past_slice.index >= start_ts) & (past_slice.index <= end_ts)
        bars_held = max(0, mask.sum() - 1)
        
        # --- 1. Hard Stop (損切り) - 広めのATR (x3.0) ---
        atr_sl_mult = exit_cfg.get("stop_loss_atr_multiplier", 3.0)
        if entry_atr > 0 and atr_sl_mult > 0:
            stop_price = buy_price - (entry_atr * atr_sl_mult)
            if row.get('low', price) <= stop_price:
                return True, f"ATR Stop (x{atr_sl_mult})", stop_price
        else:
            stop_pct = exit_cfg.get("hard_stop_pct", -3.0)
            stop_price = buy_price * (1 + stop_pct/100)
            if row.get('low', price) <= stop_price:
                return True, f"Hard Stop ({stop_pct}%)", stop_price
        
        # --- 2. Chandelier Exit (最新ATRベースの段階的Trailing) ---
        activation = exit_cfg.get("atr_trailing_activation_pct", 3.0)
        if gain_pct >= activation and current_atr > 0:
            # 利益フェーズに応じてTrailing幅を縮小
            if gain_pct >= 10.0:
                trail_mult = exit_cfg.get("chandelier_tight_mult", 1.5)   # タイト追随
            elif gain_pct >= 6.0:
                trail_mult = exit_cfg.get("chandelier_mid_mult", 2.0)     # 標準
            else:
                trail_mult = exit_cfg.get("chandelier_loose_mult", 2.5)   # 緩め
            
            trail_stop = trailing_high - (current_atr * trail_mult)
            if row.get('low', price) <= trail_stop:
                return True, f"Chandelier Exit (gain={gain_pct:.1f}%, x{trail_mult})", trail_stop
        
        # --- 3. Take Profit (利確) ---
        tp_pct = exit_cfg.get("take_profit_pct", 10.0)
        tp_price = buy_price * (1 + tp_pct/100)
        if row.get('high', price) >= tp_price:
            return True, f"Take Profit ({tp_pct}%)", tp_price

        # --- 4. 厳格化された Death Cross (MA10 < MA20 + 終値割れ) ---
        if exit_cfg.get("exit_on_death_cross", True):
            ma_short_period = exit_cfg.get("ma_short", 10)
            ma_long_period = exit_cfg.get("ma_long", 20)
            ma_short = past_slice['Close'].rolling(ma_short_period).mean().iloc[-1]
            ma_long = past_slice['Close'].rolling(ma_long_period).mean().iloc[-1]
            
            # デッドクロス ＋ 終値がMA長期を明確に下回っている場合のみ発動
            if not pd.isna(ma_short) and not pd.isna(ma_long) and ma_short < ma_long and price < ma_long:
                current_pnl = (price - buy_price) / buy_price * 100
                if current_pnl > 0 or bars_held > 10:
                    return True, f"Death Cross Exit (MA{ma_short_period}<MA{ma_long_period})", price
        
        # --- 5. Time Stop (損失時のみ) ---
        if bars_held >= exit_cfg.get("time_stop_bars", 40):
            if price < buy_price:
                return True, f"Time Stop ({bars_held}d)", price

        return False, "", 0.0

