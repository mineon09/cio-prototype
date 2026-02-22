
import json
import os
import logging

logger = logging.getLogger("CIO_Portfolio")


def calculate_position_sizing(ticker: str, sector: str, config: dict, results_file: str = "data/results.json") -> tuple[float, str]:
    """
    ポジションサイジングとセクター集中度を計算する。

    CRIT-003 修正: BUYシグナル=保有中という仮定を排除。
    results.json の history 内の 'holding' フラグを参照して現在の保有状態を判定する。
    'holding' フラグが存在しない場合（旧データ）は BUY シグナルをフォールバックとして使用するが、
    その旨を警告として明示する。

    Args:
        ticker: 対象銘柄コード
        sector: 対象セクター
        config: config.jsonの内容
        results_file: 結果dbのパス

    Returns:
        (recommended_pct, warning_message)
        recommended_pct: 推奨ポジションサイズ (0.0 ~ 1.0)
        warning_message: 警告メッセージ (なければ空文字)
    """
    ps_config = config.get("position_sizing", {})
    base_pct = ps_config.get("pct_per_trade", 0.10)
    max_sector_pct = ps_config.get("max_sector_exposure_pct", 0.30)

    # セクター情報がない場合はチェックをスキップ（またはデフォルト扱い）
    if not sector or sector == "不明":
        return base_pct, "（セクター不明のため集中度チェック除外）"

    current_sector_exposure = 0.0
    existing_tickers = []
    used_fallback = False

    if os.path.exists(results_file):
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for t, info in data.items():
                if t == ticker:
                    continue  # 自分自身は除外

                t_sector = info.get("sector", "Unknown")
                if t_sector != sector:
                    continue  # 別セクターはスキップ

                is_holding = False

                # 方法1: 明示的な保有フラグを確認（推奨）
                if "holding" in info:
                    is_holding = bool(info["holding"])
                # 方法2: history の最新エントリから保有フラグを確認
                elif "history" in info and info["history"]:
                    latest = info["history"][-1]
                    if "holding" in latest:
                        is_holding = bool(latest["holding"])
                    else:
                        # フォールバック: BUYシグナルを保有の推定に使用（旧データ互換）
                        signal = latest.get("signal", "WATCH")
                        if signal == "BUY":
                            is_holding = True
                            used_fallback = True

                if is_holding:
                    # 保有サイズを results.json から取得（存在する場合）
                    position_size = info.get("position_size", base_pct)
                    current_sector_exposure += position_size
                    existing_tickers.append(t)

        except Exception as e:
            return base_pct, f"（履歴読み込みエラー: {e}）"

    # フォールバック使用時の警告
    fallback_warning = ""
    if used_fallback:
        fallback_warning = "（⚠️ 保有フラグ未記録のため BUY シグナルから推定。実態と乖離する可能性あり）"
        logger.warning("portfolio.py: 'holding' flag not found in results.json, falling back to BUY signal estimation")

    # 容量チェック
    remaining_capacity = max_sector_pct - current_sector_exposure

    # 完全に超過している場合
    if remaining_capacity <= 0:
        msg = f"⚠️ セクター上限({max_sector_pct*100:.0f}%)超過: 既存{len(existing_tickers)}銘柄 ({', '.join(existing_tickers)}) で {current_sector_exposure*100:.0f}% 占有中{fallback_warning}"
        return 0.0, msg

    # 部分的に空きがあるが、Baseサイズより小さい場合
    if remaining_capacity < base_pct:
        msg = f"⚠️ セクター枠残余のみ割り当て ({base_pct*100:.0f}% -> {remaining_capacity*100:.1f}%). 既存: {', '.join(existing_tickers)}{fallback_warning}"
        return remaining_capacity, msg

    # 十分な空きがある場合
    msg = ""
    if current_sector_exposure > 0:
        msg = f"(同セクター既存: {', '.join(existing_tickers)} {current_sector_exposure*100:.0f}%){fallback_warning}"
    elif fallback_warning:
        msg = fallback_warning

    return base_pct, msg
