"""Assets API – file upload, download, and listing endpoints.

This router handles user-uploaded attachments (PDB, SDF, PDF, etc.) and
provides access to computed artifact files stored on the local filesystem.

⚠️  NOT registered in main.py yet.
    All route handlers raise NotImplementedError to ensure any accidental
    invocation fails loudly rather than silently.
    Register this router only after the full implementation is complete:

        In main.py:
            from app.api.v1.assets import router as assets_router
            app.include_router(assets_router, prefix="/api/v1/assets")

Endpoints
---------
POST   /api/v1/assets/upload
    Upload a file (multipart/form-data).
    Max size: settings.max_upload_bytes (default 200 MB).
    Flow:
        1. Validate TenantContext (require_context()).
        2. Validate file size and MIME type whitelist.
        3. Generate a UUID-based filename, sanitise the original name.
        4. Write bytes via LocalFileStore.save(tenant_id, workspace_id, "uploads", ...).
        5. Insert FileRecord into PostgreSQL via domain/store/file_store.py.
        6. Return FileUploadResponse(file_id, filename, size_bytes, content_type).

GET    /api/v1/assets/{file_id}
    Stream a file back to the client.
    Flow:
        1. Validate TenantContext.
        2. Load FileRecord from DB via file_store.get_file(file_id).
        3. Assert FileRecord.workspace_id == ctx.workspace_id (cross-tenant guard).
        4. Stream bytes via LocalFileStore.read_stream(local_path).
        5. Return StreamingResponse with correct Content-Type and Content-Disposition.

GET    /api/v1/assets/
    List files in the current workspace.
    Returns: list of FileListItem(file_id, filename, size_bytes, created_at).
    Supports pagination via ?limit=&offset= query params.

Security notes
--------------
- All file IDs are UUID strings validated with regex before DB lookup.
- ``workspace_id`` from FileRecord is compared to TenantContext before streaming.
  This prevents tenant A from fetching tenant B's files even if they guess a UUID.
- MIME type whitelist restricts uploads to chemistry/science file types:
  chemical/x-pdb, chemical/x-mdl-sdfile, application/pdf, text/plain,
  chemical/x-xyz, application/zip (for batch SDF archives).

TODO: implement
    Dependencies to add to pyproject.toml:
        python-multipart>=0.0.22  (already present, confirm version)

    Imports needed:
        from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
        from fastapi.responses import StreamingResponse
        from app.core.context import require_context
        from app.domain.store.file_store import FileStore
        from app.infrastructure.local_store import get_local_store
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["assets"])


@router.post("/upload")
async def upload_file() -> None:
    """Upload an attachment to the current workspace."""
    raise NotImplementedError(
        "assets.upload_file is not yet implemented. "
        "See api/v1/assets.py for the full implementation plan."
    )


@router.get("/{file_id}")
async def download_file(file_id: str) -> None:
    """Stream a workspace file back to the client."""
    raise NotImplementedError(
        "assets.download_file is not yet implemented. "
        "See api/v1/assets.py for the full implementation plan."
    )


@router.get("/")
async def list_files() -> None:
    """List files in the current workspace."""
    raise NotImplementedError(
        "assets.list_files is not yet implemented. "
        "See api/v1/assets.py for the full implementation plan."
    )
