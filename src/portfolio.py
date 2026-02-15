
import json
import os

def calculate_position_sizing(ticker: str, sector: str, config: dict, results_file: str = "data/results.json") -> tuple[float, str]:
    """
    ポジションサイジングとセクター集中度を計算する。
    
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
    
    if os.path.exists(results_file):
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            for t, info in data.items():
                if t == ticker: continue # 自分自身は除外
                
                # 最新のシグナルを確認
                if "history" in info and info["history"]:
                    latest = info["history"][-1]
                    signal = latest.get("signal", "WATCH")
                    
                    # BUYシグナルの銘柄を保有中とみなす
                    if signal == "BUY":
                        t_sector = info.get("sector", "Unknown")
                        # セクター一致確認
                        if t_sector == sector:
                            # 保有サイズは一律 base_pct と仮定（簡易計算）
                            # 本来は results.json に保有サイズを記録すべきだが、現在は未実装のため
                            current_sector_exposure += base_pct
                            existing_tickers.append(t)
                            
        except Exception as e:
            return base_pct, f"（履歴読み込みエラー: {e}）"
            
    # 容量チェック
    remaining_capacity = max_sector_pct - current_sector_exposure
    
    # 完全に超過している場合
    if remaining_capacity <= 0:
        msg = f"⚠️ セクター上限({max_sector_pct*100:.0f}%)超過: 既存{len(existing_tickers)}銘柄 ({', '.join(existing_tickers)}) で {current_sector_exposure*100:.0f}% 占有中"
        return 0.0, msg
        
    # 部分的に空きがあるが、Baseサイズより小さい場合
    if remaining_capacity < base_pct:
        msg = f"⚠️ セクター枠残余のみ割り当て ({base_pct*100:.0f}% -> {remaining_capacity*100:.1f}%). 既存: {', '.join(existing_tickers)}"
        return remaining_capacity, msg
        
    # 十分な空きがある場合
    msg = ""
    if current_sector_exposure > 0:
        msg = f"(同セクター既存: {', '.join(existing_tickers)} {current_sector_exposure*100:.0f}%)"
        
    return base_pct, msg
