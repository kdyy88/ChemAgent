from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_ENV_LOADED = False


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

    # Search order: backend/.env → project-root/.env → CWD/.env
    # Supports both "run from backend/" and Docker / monorepo layouts.
    candidates = [
        Path(__file__).resolve().parents[2] / ".env",          # backend/.env
        Path(__file__).resolve().parents[3] / ".env",          # project-root/.env
        Path.cwd() / ".env",
    ]
    for env_file in candidates:
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
            logger.debug("Loaded env from %s", env_file)
    _ENV_LOADED = True


def build_llm_config(model: str | None = None) -> dict[str, list[dict[str, Any]]]:
    _load_environment()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("❌ 启动失败: 未找到环境变量 OPENAI_API_KEY，请检查环境配置！")

    resolved_model = model or os.environ.get("OPENAI_MODEL", "").strip() or _DEFAULT_MODEL

    config: dict[str, Any] = {
        "model": resolved_model,
        "api_key": api_key,
    }

    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        normalized_base_url = _normalize_base_url(base_url)
        config["base_url"] = normalized_base_url
        if normalized_base_url != base_url.strip().rstrip("/"):
            logger.info("已自动规范化 BASE_URL: %s", normalized_base_url)
        else:
            logger.info("已检测到并挂载自定义 BASE_URL: %s", normalized_base_url)

    return {"config_list": [config]}


def get_fast_llm_config() -> dict[str, list[dict[str, Any]]]:
    fast_model = os.environ.get("FAST_MODEL", "").strip() or None
    return build_llm_config(fast_model)
