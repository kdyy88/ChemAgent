"""Database sub-package – async SQLAlchemy / SQLModel engine and session factory.

TODO: implement this module

Implementation steps
--------------------
1. Add dependencies to ``pyproject.toml``::

       sqlmodel>=0.0.21
       aiosqlite>=0.20        # dev / SQLite async driver
       asyncpg>=0.29          # prod / PostgreSQL async driver
       alembic>=1.13          # migration management

2. Create ``app/infrastructure/database/models.py`` with SQLModel table classes
   (see the "Schema" section below).

3. Implement ``app/infrastructure/database/__init__.py`` with:
   - ``create_engine_from_settings()``  using ``settings.database_url``
   - ``async_session_factory`` (``async_sessionmaker``)
   - ``get_db_session()``  FastAPI Depends generator

4. In ``app/main.py`` lifespan startup, call ``SQLModel.metadata.create_all(engine)``
   when ``settings.auto_create_tables is True``.

5. For production, disable ``auto_create_tables`` and run::

       alembic init infrastructure/database/migrations
       alembic revision --autogenerate -m "initial"
       alembic upgrade head

Schema
------
All tables use ``uuid4`` primary keys stored as VARCHAR(36).
``tenant_id`` is indexed on every child table for isolation queries.

::

    Tenant
    ├── id          UUID PK
    ├── name        str  (display name, e.g. "Acme Pharma")
    ├── slug        str  UNIQUE  (URL-safe, e.g. "acme-pharma")
    ├── plan_tier   str  (e.g. "free" | "pro" | "enterprise")
    └── created_at  datetime

    User
    ├── id           UUID PK
    ├── tenant_id    UUID FK → Tenant.id  INDEX
    ├── external_id  str  NULLABLE  (Microsoft SSO Object ID – reserved for MSAL)
    ├── email        str  UNIQUE per tenant
    ├── role         str  ("admin" | "member" | "viewer")
    └── created_at   datetime

    Workspace
    ├── id          UUID PK
    ├── tenant_id   UUID FK → Tenant.id  INDEX
    ├── name        str
    ├── description str  NULLABLE
    └── created_at  datetime

    Session
    ├── id              UUID PK
    ├── workspace_id    UUID FK → Workspace.id  INDEX
    ├── user_id         UUID FK → User.id
    ├── thread_id       str  UNIQUE
    │       format: "{tenant_id}:{workspace_id}:{session_uuid}"
    │       This is the LangGraph checkpointer thread_id.
    ├── created_at      datetime
    └── last_active_at  datetime

    FileRecord
    ├── id            UUID PK
    ├── workspace_id  UUID FK → Workspace.id  INDEX
    ├── uploader_id   UUID FK → User.id
    ├── filename      str   (original filename, sanitised)
    ├── content_type  str   (MIME type, e.g. "chemical/x-pdb")
    ├── size_bytes    int
    ├── local_path    str   (relative path under UPLOAD_ROOT)
    │       format: "{tenant_id}/{workspace_id}/uploads/{uuid}.ext"
    └── created_at    datetime

    ArtifactRecord
    ├── id               UUID PK
    ├── workspace_id     UUID FK → Workspace.id  INDEX
    ├── session_id       UUID FK → Session.id  NULLABLE
    ├── kind             str   (e.g. "sdf_batch", "docking_result", "report_image")
    ├── size_bytes       int
    ├── storage_backend  str   ("redis" | "local")
    ├── storage_ref      str
    │       redis  → Redis key, e.g. "t1:ws1:artifact:art_abc123"
    │       local  → relative path, e.g. "t1/ws1/artifacts/art_abc123.pdbqt"
    └── created_at       datetime

Dual-mode database URL
----------------------
+------------------+---------------------------------------------+
| Environment      | DATABASE_URL example                        |
+==================+=============================================+
| Development      | sqlite+aiosqlite:///./chemagent.db           |
| CI / Integration | sqlite+aiosqlite:///./test_chemagent.db      |
| Production       | postgresql+asyncpg://user:pw@host:5432/db   |
+------------------+---------------------------------------------+

LangGraph checkpointer selection (in agents/main_agent/runtime.py)
-------------------------------------------------------------------
::

    if "sqlite" in settings.database_url:
        saver = AsyncSqliteSaver.from_conn_string(...)   # current implementation
    else:
        saver = AsyncPostgresSaver.from_conn_string(settings.database_url)
        # requires: langgraph-checkpoint-postgres>=2.0

    # thread_id format must match Session.thread_id
    config = {"configurable": {"thread_id": f"{tenant_id}:{workspace_id}:{session_id}"}}

Row-level isolation strategy
-----------------------------
No PostgreSQL RLS policies are used in v1 (too complex to maintain with
SQLModel).  Isolation is enforced at the application layer:

* Every query that touches child tables filters on ``workspace_id`` which is
  extracted from the current ``TenantContext`` via ``require_context()``.
* ``domain/store/file_store.py`` validates that a requested ``FileRecord.workspace_id``
  matches the current context before returning it.
"""
