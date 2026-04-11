from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path

from app.domain.schemas.workflow import ScratchpadKind, ScratchpadRef

logger = logging.getLogger(__name__)

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_SCRATCHPAD_ID = re.compile(r"^sp_[A-Za-z0-9]{12}$")
_DEFAULT_ROOT = Path(os.getenv("CHEMAGENT_SCRATCHPAD_DIR", Path(__file__).resolve().parents[3] / ".scratchpad"))


def _sanitize_segment(value: str, *, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or not _SAFE_SEGMENT.fullmatch(normalized):
        raise ValueError(f"Unsafe scratchpad {label}: {value!r}")
    return normalized


def _scratchpad_dir(session_id: str, sub_thread_id: str) -> Path:
    safe_session = _sanitize_segment(session_id, label="session_id")
    safe_thread = _sanitize_segment(sub_thread_id, label="sub_thread_id")
    path = (_DEFAULT_ROOT / safe_session / safe_thread).resolve()
    root = _DEFAULT_ROOT.resolve()
    if root not in (path, *path.parents):
        raise ValueError("Scratchpad directory escapes configured root")
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_scratchpad_entry(
    *,
    session_id: str,
    sub_thread_id: str,
    kind: ScratchpadKind,
    content: str,
    created_by: str = "system",
    summary: str = "",
    extension: str = "txt",
) -> ScratchpadRef:
    target_dir = _scratchpad_dir(session_id, sub_thread_id)
    scratchpad_id = f"sp_{uuid.uuid4().hex[:12]}"
    normalized_ext = re.sub(r"[^A-Za-z0-9]", "", extension or "txt") or "txt"
    payload_name = f"{scratchpad_id}.{normalized_ext}"
    meta_name = f"{scratchpad_id}.json"

    payload_path = (target_dir / payload_name).resolve()
    meta_path = (target_dir / meta_name).resolve()
    if target_dir not in (payload_path, *payload_path.parents) or target_dir not in (meta_path, *meta_path.parents):
        raise ValueError("Scratchpad path escapes session directory")

    payload_path.write_text(content, encoding="utf-8")
    ref = ScratchpadRef(
        scratchpad_id=scratchpad_id,
        kind=kind,
        summary=summary.strip(),
        size_bytes=len(content.encode("utf-8")),
        created_by=created_by.strip() or "system",
    )
    meta_path.write_text(
        json.dumps(
            {
                **ref.model_dump(mode="json"),
                "payload_name": payload_name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.debug(
        "scratchpad created: id=%s kind=%s created_by=%s session=%s thread=%s size_bytes=%d path=%s",
        scratchpad_id,
        kind.value,
        created_by,
        session_id,
        sub_thread_id,
        ref.size_bytes,
        str(payload_path),
    )
    return ref


def read_scratchpad_entry(*, session_id: str, sub_thread_id: str, scratchpad_id: str) -> tuple[ScratchpadRef, str]:
    if not _SAFE_SCRATCHPAD_ID.fullmatch(str(scratchpad_id or "").strip()):
        raise ValueError(f"Unsafe scratchpad_id: {scratchpad_id!r}")

    target_dir = _scratchpad_dir(session_id, sub_thread_id)
    meta_path = (target_dir / f"{scratchpad_id}.json").resolve()
    if target_dir not in (meta_path, *meta_path.parents) or not meta_path.exists():
        raise FileNotFoundError(f"Scratchpad entry not found: {scratchpad_id}")

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    payload_name = str(metadata.get("payload_name") or "").strip()
    if not payload_name:
        raise ValueError(f"Scratchpad metadata missing payload_name: {scratchpad_id}")

    payload_path = (target_dir / payload_name).resolve()
    if target_dir not in (payload_path, *payload_path.parents) or not payload_path.exists():
        raise FileNotFoundError(f"Scratchpad payload missing: {scratchpad_id}")

    ref = ScratchpadRef.model_validate({
        "scratchpad_id": metadata.get("scratchpad_id", scratchpad_id),
        "kind": metadata.get("kind", ScratchpadKind.note.value),
        "summary": metadata.get("summary", ""),
        "size_bytes": metadata.get("size_bytes", 0),
        "created_by": metadata.get("created_by", "system"),
    })
    content = payload_path.read_text(encoding="utf-8")
    logger.debug(
        "scratchpad read: id=%s kind=%s session=%s thread=%s size_bytes=%d",
        scratchpad_id,
        ref.kind.value,
        session_id,
        sub_thread_id,
        ref.size_bytes,
    )
    return ref, content