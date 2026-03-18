"""
src/copilot_client.py - GitHub Models API クライアント
=======================================================
GitHub Models (https://models.inference.ai.azure.com) 経由で LLM を呼び出す。
GitHub 認証トークン（gh auth token）を使用するため、追加の API キー設定は不要。

対応モデル（GitHub Models 経由）:
  gpt-4o             : 高品質（推奨）
  gpt-4o-mini        : 高速・低コスト
  llama405b          : Meta-Llama-3.1-405B-Instruct
  llama70b           : Meta-Llama-3.1-70B-Instruct
  mistral            : Mistral-large-2407

注意:
  Claude Sonnet は現時点で GitHub Models API 経由では利用不可。
  gh copilot suggest は shell/git/gh コマンド提案専用のため、
  投資分析などの一般テキスト生成には本モジュール（GitHub Models API）を使用。
"""

import subprocess
import json
import requests
from typing import Optional

GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com/chat/completions"

SUPPORTED_MODELS: dict[str, str] = {
    "gpt-4o":        "gpt-4o",
    "gpt-4o-mini":   "gpt-4o-mini",
    "llama405b":     "Meta-Llama-3.1-405B-Instruct",
    "llama70b":      "Meta-Llama-3.1-70B-Instruct",
    "mistral":       "Mistral-large-2407",
}

DEFAULT_SYSTEM_PROMPT = "あなたはシニア・エクイティ・アナリストです。"


def get_gh_token() -> Optional[str]:
    """gh CLI から GitHub 認証トークンを取得する"""
    try:
        result = subprocess.check_output(
            ["gh", "auth", "token"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return result.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def call_github_models(
    prompt: str,
    model: str = "gpt-4o",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> tuple[str, str]:
    """
    GitHub Models API 経由で LLM を呼び出す。

    Parameters
    ----------
    prompt        : ユーザープロンプト
    model         : モデル略称（SUPPORTED_MODELS のキー）または正式モデル名
    max_tokens    : 最大生成トークン数
    temperature   : 生成温度（0.0 = 決定論的）
    system_prompt : システムプロンプト

    Returns
    -------
    tuple[str, str] : (レスポンステキスト, 使用モデル名)

    Raises
    ------
    RuntimeError : 認証失敗 / API エラー時
    """
    resolved_model = SUPPORTED_MODELS.get(model, model)

    token = get_gh_token()
    if not token:
        raise RuntimeError(
            "GitHub トークンが取得できません。`gh auth login` を実行してください。"
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = requests.post(
            GITHUB_MODELS_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        used_model = data.get("model", resolved_model)
        return content, f"GitHub Models ({used_model})"
    except requests.HTTPError as e:
        body = e.response.text[:300] if e.response else ""
        raise RuntimeError(f"GitHub Models API エラー ({e.response.status_code}): {body}") from e
    except requests.Timeout:
        raise RuntimeError("GitHub Models API タイムアウト（120秒）") from None
    except Exception as e:
        raise RuntimeError(f"GitHub Models 呼び出し失敗: {e}") from e


def list_available_models() -> list[str]:
    """GitHub Models API で利用可能なモデル一覧を取得する"""
    token = get_gh_token()
    if not token:
        return list(SUPPORTED_MODELS.keys())
    try:
        resp = requests.get(
            "https://models.inference.ai.azure.com/models",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        models = resp.json()
        return [m["name"] for m in models if m.get("task") == "chat-completion"]
    except Exception:
        return list(SUPPORTED_MODELS.keys())
