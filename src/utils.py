import json
import logging
import copy
import os
from typing import Dict, Any

logger = logging.getLogger("CIO_Utils")

def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        logger.warning(f"Config file not found: {config_path}")
        return {}
        
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}

def recursive_update(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively update dictionary."""
    for k, v in update.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            recursive_update(base[k], v)
        else:
            base[k] = v
    return base

def load_config_with_overrides(ticker: str, config_path: str = "config.json") -> Dict[str, Any]:
    """
    Load config and apply ticker-specific overrides.
    Target ticker assumes normalized format (e.g., "7203.T", "NVDA").
    """
    config = load_config(config_path)
    if not config: return {}
    
    # Normalize ticker (Standardize on Upper case)
    # Note: caller should handle .T suffix logic if needed, but here we just ensure basic normalization
    ticker = ticker.strip().upper()
    
    if not config.get("ticker_overrides"):
        return config
        
    overrides = config["ticker_overrides"].get(ticker)
    if not overrides:
        return config

    logger.info(f"Applying config overrides for {ticker}")
    
    # Create a deep copy to avoid modifying the original config
    merged_config = copy.deepcopy(config)
    
    # Merge overrides into the base config
    recursive_update(merged_config, overrides)
    
    return merged_config
