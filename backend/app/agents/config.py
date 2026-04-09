from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_ENV_LOADED = False
_LOGGED_BASE_URLS: set[str] = set()
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_RESPONSES_REASONING_GPT_PREFIXES = (
    "gpt-5",
)
_MODEL_CONTEXT_WINDOW_LIMITS: tuple[tuple[str, int], ...] = (
    ("gpt-5", 400_000),
)


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


def resolve_model_name(model: str | None = None) -> str:
    _load_environment()
    return (model or os.environ.get("OPENAI_MODEL", "").strip() or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def get_active_model_name(model: str | None = None) -> str:
    """Return the model name that will be used for the main agent LLM call.

    Reads ``OPENAI_MODEL`` (same resolution order as ``build_llm_config``).
    Result is cached implicitly via ``_load_environment()``.
    """
    return resolve_model_name(model)


def get_fast_model_name() -> str:
    _load_environment()
    return resolve_model_name(os.environ.get("FAST_MODEL", "").strip() or None)


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

    resolved_model = resolve_model_name(model)

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


def get_openai_api_key() -> str:
    _load_environment()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("❌ 启动失败: 未找到环境变量 OPENAI_API_KEY，请检查环境配置！")
    return api_key


def get_normalized_openai_base_url() -> str:
    _load_environment()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if not base_url:
        return _DEFAULT_OPENAI_BASE_URL
    _validate_base_url(base_url)
    return _normalize_base_url(base_url)


def is_parameter_compatible_model(model_name: str) -> bool:
    lowered = str(model_name or "").strip().lower()
    if not lowered:
        return False
    return (
        any(lowered.startswith(prefix) for prefix in _RESPONSES_REASONING_GPT_PREFIXES)
        and _is_reasoning_capable_model(lowered)
    )


def _normalize_model_entry(model_id: str) -> dict[str, Any] | None:
    normalized = str(model_id or "").strip()
    if not normalized or not is_parameter_compatible_model(normalized):
        return None

    default_model = get_active_model_name()
    return {
        "id": normalized,
        "label": normalized,
        "is_default": normalized == default_model,
        "is_reasoning": is_native_reasoning_model(normalized),
        "max_context_tokens": get_model_context_window_limit(normalized),
    }


def get_model_context_window_limit(model_name: str) -> int:
    lowered = str(model_name or "").strip().lower()
    for prefix, limit in _MODEL_CONTEXT_WINDOW_LIMITS:
        if lowered.startswith(prefix):
            return limit
    return 400_000


def get_fallback_model_catalog() -> list[dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for model_name in (get_active_model_name(), get_fast_model_name()):
        item = _normalize_model_entry(model_name)
        if item is not None:
            catalog[item["id"]] = item
    return list(catalog.values())


async def fetch_available_models(timeout: float = 10.0) -> tuple[list[dict[str, Any]], str | None]:
    base_url = get_normalized_openai_base_url()
    headers = {
        "Authorization": f"Bearer {get_openai_api_key()}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch model catalog from provider: %s", exc)
        return get_fallback_model_catalog(), str(exc)

    payload = response.json()
    raw_models = payload.get("data", []) if isinstance(payload, dict) else []
    catalog: dict[str, dict[str, Any]] = {}
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        item = _normalize_model_entry(str(entry.get("id", "")))
        if item is not None:
            catalog[item["id"]] = item

    if not catalog:
        return get_fallback_model_catalog(), "provider returned no parameter-compatible chat models"

    models = list(catalog.values())
    models.sort(key=lambda item: (not item["is_default"], item["id"]))
    return models, None
