from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


_DEFAULT_MODEL = "gpt-4o-mini"
_ENV_LOADED = False

# Allowlist of models known to fully support system prompts + tool calling.
# If a user supplies a model not in this set the backend logs a warning and
# falls back to the default rather than sending a likely-broken API request.
_SUPPORTED_MODELS: frozenset[str] = frozenset({
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1-nano",
})


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/responses"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def _load_environment() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    env_file = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(dotenv_path=env_file, override=False)
    _ENV_LOADED = True


def build_llm_config(model: str | None = None) -> dict[str, list[dict[str, Any]]]:
    _load_environment()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("❌ 启动失败: 未找到环境变量 OPENAI_API_KEY，请检查环境配置！")

    resolved_model = model or os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL)
    if model and model not in _SUPPORTED_MODELS:
        warnings.warn(
            f"[ChemAgent] Unknown model '{model}' — falling back to default '{_DEFAULT_MODEL}'. "
            "Add it to _SUPPORTED_MODELS in config.py if it fully supports system prompts and tool calling.",
            stacklevel=2,
        )
        resolved_model = _DEFAULT_MODEL

    config: dict[str, Any] = {
        "model": resolved_model,
        "api_key": api_key,
    }

    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        normalized_base_url = _normalize_base_url(base_url)
        config["base_url"] = normalized_base_url
        if normalized_base_url != base_url.strip().rstrip("/"):
            print(f"[*] 已自动规范化 BASE_URL: {normalized_base_url}")
        else:
            print(f"[*] 已检测到并挂载自定义 BASE_URL: {normalized_base_url}")

    return {"config_list": [config]}


def get_fast_llm_config() -> dict[str, list[dict[str, Any]]]:
    return build_llm_config(os.environ.get("FAST_MODEL", _DEFAULT_MODEL))
