"""Local filesystem adapter for large binary assets.

This is the data-plane storage for all files that are too large for Redis
and too unstructured for PostgreSQL.

See README.md in this directory for the path layout, security constraints,
and S3 migration strategy.

TODO: implement
    Create class LocalFileStore with the interface described in README.md.
    Import and instantiate it as a module-level singleton::

        _store = LocalFileStore(root=get_settings().upload_root)

        async def get_local_store() -> LocalFileStore:
            return _store
"""

from __future__ import annotations

# TODO: implement LocalFileStore
#
# Required methods (all async):
#   save(tenant_id, workspace_id, category, filename, content: bytes) -> str
#   read(relative_path: str) -> bytes
#   delete(relative_path: str) -> None
#   read_stream(relative_path: str) -> AsyncIterator[bytes]  (for StreamingResponse)
#   exists(relative_path: str) -> bool
#
# Path layout:
#   {upload_root}/{tenant_id}/{workspace_id}/{category}/{filename}
#
# Security: validate every path segment with:
#   re.match(r'^[A-Za-z0-9_\-\.]{1,128}$', segment)
# before joining to prevent path traversal attacks.
#
# Concurrency: use asyncio.to_thread() to wrap blocking file I/O.
