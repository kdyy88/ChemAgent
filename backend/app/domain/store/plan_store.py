from __future__ import annotations

import os
import re
from pathlib import Path

from app.domain.schemas.workflow import PlanPointer

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_PLAN_ID = re.compile(r"^[A-Fa-f0-9-]{16,64}$")
_DEFAULT_ROOT = Path(
    os.getenv(
        "CHEMAGENT_PLAN_DIR",
        Path(__file__).resolve().parents[3] / ".plans",
    )
)


def _sanitize_segment(value: str, *, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or not _SAFE_SEGMENT.fullmatch(normalized):
        raise ValueError(f"Unsafe plan-store {label}: {value!r}")
    return normalized


def _sanitize_plan_id(plan_id: str) -> str:
    normalized = str(plan_id or "").strip()
    if not normalized or not _SAFE_PLAN_ID.fullmatch(normalized):
        raise ValueError(f"Unsafe plan_id: {plan_id!r}")
    return normalized


def _plans_dir(session_id: str) -> Path:
    safe_session = _sanitize_segment(session_id, label="session_id")
    path = (_DEFAULT_ROOT / safe_session).resolve()
    root = _DEFAULT_ROOT.resolve()
    if root not in (path, *path.parents):
        raise ValueError("Plan directory escapes configured root")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _plan_path(session_id: str, plan_id: str) -> Path:
    target_dir = _plans_dir(session_id)
    safe_plan_id = _sanitize_plan_id(plan_id)
    path = (target_dir / f"{safe_plan_id}.md").resolve()
    if target_dir not in (path, *path.parents):
        raise ValueError("Plan path escapes session directory")
    return path


def _summarize_markdown(content: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def write_plan_file(*, session_id: str, plan_id: str, content: str) -> PlanPointer:
    path = _plan_path(session_id, plan_id)
    path.write_text(str(content or ""), encoding="utf-8")
    return PlanPointer(
        plan_id=_sanitize_plan_id(plan_id),
        plan_file_ref=f"{_sanitize_segment(session_id, label='session_id')}/{path.name}",
        status="draft",
        summary=_summarize_markdown(content),
        revision=1,
    )


def update_plan_file(*, session_id: str, plan_id: str, content: str) -> PlanPointer:
    path = _plan_path(session_id, plan_id)
    path.write_text(str(content or ""), encoding="utf-8")
    return PlanPointer(
        plan_id=_sanitize_plan_id(plan_id),
        plan_file_ref=f"{_sanitize_segment(session_id, label='session_id')}/{path.name}",
        status="pending_approval",
        summary=_summarize_markdown(content),
        revision=1,
    )


def read_plan_file(*, session_id: str, plan_id: str) -> tuple[PlanPointer, str]:
    path = _plan_path(session_id, plan_id)
    if not path.exists():
        raise FileNotFoundError(f"Plan file not found: {plan_id}")
    content = path.read_text(encoding="utf-8")
    return (
        PlanPointer(
            plan_id=_sanitize_plan_id(plan_id),
            plan_file_ref=f"{_sanitize_segment(session_id, label='session_id')}/{path.name}",
            status="draft",
            summary=_summarize_markdown(content),
            revision=1,
        ),
        content,
    )