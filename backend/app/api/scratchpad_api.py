"""GET /api/scratchpad/{scratchpad_id}

Read a scratchpad entry written by a sub-agent.

Security
--------
* ``scratchpad_id`` is validated against ``^sp_[A-Za-z0-9]{12}$`` inside
  ``read_scratchpad_entry``; anything that doesn't match returns a 400.
* ``session_id`` and ``sub_thread_id`` are sanitised by ``_scratchpad_dir``
  (allow-list regex + resolved-path escape check).  They act as a two-factor
  capability token: a caller must know *both* to retrieve any entry.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.scratchpad_store import read_scratchpad_entry

logger = logging.getLogger(__name__)

router = APIRouter()


class ScratchpadResponse(BaseModel):
    scratchpad_id: str
    kind: str
    summary: str
    size_bytes: int
    created_by: str
    content: str


@router.get("/{scratchpad_id}", response_model=ScratchpadResponse)
async def get_scratchpad(
    scratchpad_id: str,
    session_id: str = Query(..., description="Parent session / thread ID that owns this scratchpad"),
    sub_thread_id: str = Query(..., description="Sub-agent thread ID the entry was written under"),
) -> ScratchpadResponse:
    """Return the raw content and metadata for a scratchpad entry."""
    try:
        ref, content = read_scratchpad_entry(
            session_id=session_id,
            sub_thread_id=sub_thread_id,
            scratchpad_id=scratchpad_id,
        )
        logger.debug(
            "scratchpad API: served id=%s session=%s thread=%s size_bytes=%d",
            scratchpad_id,
            session_id,
            sub_thread_id,
            ref.size_bytes,
        )
        return ScratchpadResponse(
            scratchpad_id=ref.scratchpad_id,
            kind=ref.kind.value,
            summary=ref.summary,
            size_bytes=ref.size_bytes,
            created_by=ref.created_by,
            content=content,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
