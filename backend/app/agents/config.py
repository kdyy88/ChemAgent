from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_ENV_LOADED = False
_LOGGED_BASE_URLS: set[str] = set()


# Known-native-reasoning model name prefixes (case-insensitive).
# Used as the automatic-detection fallback when CHEMAGENT_NATIVE_REASONING is unset.
_NATIVE_REASONING_PREFIXES = (
    "gpt-5",
    "o1",
    "o3",
    "o4",
    "o5",
    "claude-3-7",   # Claude 3.7 Sonnet with extended thinking
    "claude-3.7",
)


def _is_reasoning_capable_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return any(lowered.startswith(p) for p in _NATIVE_REASONING_PREFIXES)


def is_native_reasoning_model(model_name: str) -> bool:
    """Return True if *model_name* has built-in chain-of-thought / reasoning output.

    Resolution order
    ----------------
    1. ``CHEMAGENT_NATIVE_REASONING`` env var — explicit override ("1"/"true"/"yes"
       or "0"/"false"/"no").  Use this when the model name is opaque (proxy aliases,
       fine-tunes, Claude with extended thinking enabled, etc.).
    2. Prefix heuristic against ``_NATIVE_REASONING_PREFIXES`` — covers standard
       OpenAI model names automatically.

    When True the prompt factory suppresses ``<thinking>`` tag instructions
    (native Responses API reasoning is used instead); when False it injects
    explicit chain-of-thought guidance.
    """
    _load_environment()
    override = os.environ.get("CHEMAGENT_NATIVE_REASONING", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    # No override — fall back to prefix heuristic.
    return _is_reasoning_capable_model(model_name)


def get_active_model_name() -> str:
    """Return the model name that will be used for the main agent LLM call.

    Reads ``OPENAI_MODEL`` (same resolution order as ``build_llm_config``).
    Result is cached implicitly via ``_load_environment()``.
    """
    _load_environment()
    return os.environ.get("OPENAI_MODEL", "").strip() or _DEFAULT_MODEL


def _env_truthy(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/responses"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def _validate_base_url(url: str) -> None:
    """Raise ValueError if the URL scheme is not http or https."""
    from urllib.parse import urlparse
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"OPENAI_BASE_URL must use http or https scheme, got: '{parsed.scheme}://...'"
        )


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

    if _is_reasoning_capable_model(resolved_model):
        effort = os.environ.get("OPENAI_REASONING_EFFORT", "medium").strip() or "medium"
        summary = os.environ.get("OPENAI_REASONING_SUMMARY", "auto").strip() or "auto"
        config["reasoning"] = {
            "effort": effort,
            "summary": summary,
        }
        if _env_truthy("OPENAI_USE_RESPONSES_API", True):
            config["use_responses_api"] = True
            config["output_version"] = os.environ.get("OPENAI_OUTPUT_VERSION", "responses/v1").strip() or "responses/v1"

    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        _validate_base_url(base_url)
        normalized_base_url = _normalize_base_url(base_url)
        config["base_url"] = normalized_base_url
        if normalized_base_url not in _LOGGED_BASE_URLS:
            _LOGGED_BASE_URLS.add(normalized_base_url)
            if normalized_base_url != base_url.strip().rstrip("/"):
                logger.info("已自动规范化 BASE_URL: %s", normalized_base_url)
            else:
                logger.info("已检测到并挂载自定义 BASE_URL: %s", normalized_base_url)

    return {"config_list": [config]}


def get_fast_llm_config() -> dict[str, list[dict[str, Any]]]:
    fast_model = os.environ.get("FAST_MODEL", "").strip() or None
    return build_llm_config(fast_model)
