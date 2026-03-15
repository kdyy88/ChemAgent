from __future__ import annotations

import os


_DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:80",
    "http://127.0.0.1:80",
]


def get_allowed_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_ALLOWED_ORIGINS)
    if raw == "*":
        return ["*"]
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def is_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True

    allowed_origins = get_allowed_origins()
    if "*" in allowed_origins:
        return True

    return origin.rstrip("/") in allowed_origins