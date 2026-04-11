"""local_store – Local filesystem adapter for large binary assets.

Purpose
-------
Stores files that are too large for Redis and don't belong in a relational
database: user-uploaded PDB/SDF/PDF files, computed docking results (PDBQT),
MD trajectory snapshots, generated report images, etc.

This adapter is the **data-plane counterpart** to the control-plane stored in
PostgreSQL.  The database only ever stores a *pointer* (``FileRecord.local_path``
or ``ArtifactRecord.storage_ref``); the bytes live here.

Path layout
-----------
::

    {UPLOAD_ROOT}/
    └── {tenant_id}/
        └── {workspace_id}/
            ├── uploads/          ← user-uploaded attachments
            │   └── {uuid}.{ext}
            └── artifacts/        ← computed results from Worker jobs
                └── {artifact_id}

``UPLOAD_ROOT`` is configured via ``settings.upload_root`` (default: ``./data/uploads``).
The root directory is created on first use if it does not exist.

Path segment validation (security)
-----------------------------------
Every segment of the path (tenant_id, workspace_id, category, filename) is
validated against ``^[A-Za-z0-9_\\-\\.]{1,128}$`` before being joined.
This prevents **path traversal attacks** (e.g. ``../../etc/passwd``).

Do NOT rely on ``os.path.join`` alone – always validate first.

LocalFileStore interface
------------------------
::

    class LocalFileStore:
        def __init__(self, root: Path) -> None: ...

        async def save(
            self,
            tenant_id: str,
            workspace_id: str,
            category: str,          # e.g. "uploads" or "artifacts"
            filename: str,          # validated, uuid-based
            content: bytes,
        ) -> str:
            \"\"\"Write bytes and return the relative path (stored in DB).\"\"\"

        async def read(self, relative_path: str) -> bytes:
            \"\"\"Read and return the full file content.\"\"\"

        async def read_stream(
            self, relative_path: str, chunk_size: int = 65536
        ) -> AsyncIterator[bytes]:
            \"\"\"Yield file chunks for use with FastAPI StreamingResponse.\"\"\"

        async def delete(self, relative_path: str) -> None:
            \"\"\"Remove a file.  Silent if not found.\"\"\"

        async def exists(self, relative_path: str) -> bool:
            \"\"\"Return True if the file exists.\"\"\"

Implementation notes
--------------------
- Use ``asyncio.to_thread()`` (Python 3.9+) to wrap blocking ``pathlib`` /
  ``open()`` / ``os.unlink()`` calls so the event loop is never blocked.
- ``read_stream()`` should open the file once and yield chunks, not load
  the whole file into memory.
- For ``save()``, call ``parent.mkdir(parents=True, exist_ok=True)`` before
  writing to ensure the directory tree exists.

Future: Migration to S3/MinIO
------------------------------
When the platform is ready for cloud storage, replace ``LocalFileStore``
with ``S3FileStore`` (or ``MinIOFileStore``) that implements the **same
interface**.  No domain code changes – only swap the adapter registration
in ``infrastructure/local_store/__init__.py``::

    # Before
    _store = LocalFileStore(root=settings.upload_root)

    # After
    _store = S3FileStore(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )

Artifact routing (smart router in artifact_store.py)
------------------------------------------------------
``domain/store/artifact_store.py`` decides *where* to write based on size::

    if len(content) <= settings.artifact_size_threshold_bytes:   # default 1 MB
        → store in Redis (hot, TTL-managed)
    else:
        → store via LocalFileStore under artifacts/
        → record ArtifactRecord in PostgreSQL with storage_backend="local"
"""
