"""FileStore – domain facade for user-uploaded attachment metadata.

This store sits between the API layer and the infrastructure layer.
It owns the *metadata* of uploaded files (stored in PostgreSQL via
``FileRecord``), while the raw bytes live in ``infrastructure.local_store``.

Role in the upload flow
-----------------------
::

    api/v1/assets.py (POST /upload)
        │
        │  1. calls LocalFileStore.save() → relative_path
        │
        ▼
    domain/store/file_store.py
        │  2. calls register_upload() → inserts FileRecord into PostgreSQL
        │  3. returns FileRecord with generated file_id
        │
        ▼
    api/v1/assets.py
        │  4. returns FileUploadResponse(file_id=...) to client

Role in the download flow
--------------------------
::

    api/v1/assets.py (GET /assets/{file_id})
        │
        ▼
    domain/store/file_store.py
        │  1. calls get_file(file_id) → loads FileRecord from DB
        │  2. validates FileRecord.workspace_id == TenantContext.workspace_id
        │     (cross-tenant guard – raises 403 if mismatch)
        │
        ▼
    api/v1/assets.py
        │  3. calls LocalFileStore.read_stream(record.local_path)
        │  4. returns StreamingResponse

Public interface
----------------
::

    async def register_upload(
        filename: str,
        content_type: str,
        size_bytes: int,
        local_path: str,
    ) -> FileRecord:
        \"\"\"Insert a FileRecord row.  tenant/workspace from TenantContext.\"\"\"

    async def get_file(file_id: str) -> FileRecord:
        \"\"\"Load FileRecord and assert workspace isolation.  Raises 404 / 403.\"\"\"

    async def list_workspace_files(
        limit: int = 50,
        offset: int = 0,
    ) -> list[FileRecord]:
        \"\"\"Return files belonging to the current workspace.\"\"\"

    async def delete_file(file_id: str) -> str:
        \"\"\"Remove FileRecord from DB. Returns local_path for caller to delete bytes.\"\"\"

TODO: implement this module
    Dependencies needed:
        sqlmodel (for DB access)
        app.core.context.require_context
        app.infrastructure.database.get_db_session
        app.infrastructure.database.models.FileRecord
"""

from __future__ import annotations


async def register_upload(
    filename: str,
    content_type: str,
    size_bytes: int,
    local_path: str,
) -> None:
    """Insert a FileRecord into PostgreSQL.

    Reads tenant_id and workspace_id from the current TenantContext.
    Returns the created FileRecord.
    """
    raise NotImplementedError(
        "file_store.register_upload is not yet implemented. "
        "See domain/store/file_store.py for the full implementation plan."
    )


async def get_file(file_id: str) -> None:
    """Load FileRecord and validate workspace isolation.

    Raises:
        404 HTTPException: if no record with file_id exists.
        403 HTTPException: if record.workspace_id != TenantContext.workspace_id.
    """
    raise NotImplementedError(
        "file_store.get_file is not yet implemented."
    )


async def list_workspace_files(limit: int = 50, offset: int = 0) -> list:
    """Return FileRecords belonging to the current workspace."""
    raise NotImplementedError(
        "file_store.list_workspace_files is not yet implemented."
    )


async def delete_file(file_id: str) -> str:
    """Remove FileRecord from DB. Returns local_path so caller can delete bytes."""
    raise NotImplementedError(
        "file_store.delete_file is not yet implemented."
    )
