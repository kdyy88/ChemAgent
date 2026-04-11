"""
api/v1/artifacts.py — Binary artifact download endpoint.

GET /api/v1/artifacts/{result_id}
Returns the binary artifact (ZIP, SDF, etc.) stored by the worker.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import io

from app.domain.store.artifact_store import read_artifact

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{result_id}")
async def download_artifact(result_id: str) -> StreamingResponse:
    """Download a binary artifact by its result_id."""
    artifact = await read_artifact(result_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found or expired")
    content, meta = artifact
    return StreamingResponse(
        io.BytesIO(content),
        media_type=meta.get("media_type", "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{meta.get("filename", result_id)}"',
        },
    )
