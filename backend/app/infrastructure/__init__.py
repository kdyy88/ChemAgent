"""Infrastructure layer – Anti-Corruption Layer (ACL) between domain logic and external systems.

This package isolates all I/O adapters so that the rest of the application
(agents, services, domain stores) never imports from ``redis``, ``sqlalchemy``,
``boto3``, or any other infrastructure SDK directly.

Sub-packages
------------
cache/
    Redis connection pool.  Hot data only – locks, rate-limit counters,
    transient artifact payloads (<1 MB).  Never stores user assets persistently.

database/
    Async SQLAlchemy + SQLModel engine and session factory.  Stores relational
    data: Tenant, User, Workspace, Session, FileRecord, ArtifactRecord.

local_store/
    Local filesystem adapter for large binary assets (PDB, SDF, PDBQT, PDF).
    Path layout enforces tenant/workspace isolation.  Drop-in replaceable with
    an S3/MinIO adapter in the future without touching any domain code.

message_queue/
    ARQ task queue wrapper.  Exposes ``enqueue_task()`` so callers never import
    ARQ directly; also responsible for serialising TenantContext into task payloads.

Dependency rule
---------------
Infrastructure modules MAY import from ``app.core`` (config, context, exceptions).
They MUST NOT import from ``app.agents``, ``app.services``, or ``app.domain``.
The domain layer imports from infrastructure – never the other way around.
"""
