"""
logging_utils.py - ロギングユーティリティ
==========================================
アプリケーション全体で使用するロギング設定を提供する。

使用例:
    from src.logging_utils import get_logger
    logger = get_logger(__name__)
    logger.info("処理開始")
    logger.debug("デバッグ情報")
    logger.warning("警告")
    logger.error("エラー")
"""

import logging
import sys
from typing import Optional

# ログフォーマット
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ログレベルマッピング
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    名前付きロガーを取得する。

    Args:
        name: ロガー名（通常は __name__）
        level: ログレベル（省略時は INFO）

    Returns:
        設定済みの Logger インスタンス
    """
    logger = logging.getLogger(name)
    
    # すでにハンドラーが設定されている場合はそのまま返す
    if logger.handlers:
        return logger
    
    # ログレベルの設定
    log_level = LOG_LEVELS.get(level or "INFO", logging.INFO)
    logger.setLevel(log_level)
    
    # コンソールハンドラーの作成
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    # フォーマッターの設定
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    console_handler.setFormatter(formatter)
    
    # ハンドラーの追加
    logger.addHandler(console_handler)
    
    # 伝播を無効化（重複ログ防止）
    logger.propagate = False
    
    return logger


def set_log_level(level: str) -> None:
    """
    全ロガーのログレベルを一括変更する。

    Args:
        level: ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）
    """
    log_level = LOG_LEVELS.get(level.upper(), logging.INFO)
    
    for logger_name in logging.root.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        logger.setLevel(log_level)
        for handler in logger.handlers:
            handler.setLevel(log_level)


def add_file_handler(logger: logging.Logger, filepath: str, level: Optional[str] = None) -> None:
    """
    ファイルハンドラーを追加する。

    Args:
        logger: 対象のロガー
        filepath: ログファイルパス
        level: ログレベル（省略時はロガーと同じ）
    """
    log_level = LOG_LEVELS.get(level or "INFO", logging.INFO)
    
    try:
        file_handler = logging.FileHandler(filepath, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"ファイルハンドラーの追加に失敗: {e}")
