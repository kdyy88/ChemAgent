"""SQLModel table definitions for ChemAgent SaaS.

See infrastructure/database/README.md for the full schema rationale.

TODO: implement
    Define one SQLModel class per table listed below.  Every table uses
    uuid4 primary keys.  All child tables have tenant_id indexed.

    Tables to create:
        Tenant, User, Workspace, Session, FileRecord, ArtifactRecord

    Example skeleton::

        from __future__ import annotations
        from datetime import datetime
        from uuid import UUID, uuid4
        from sqlmodel import Field, SQLModel


        class Tenant(SQLModel, table=True):
            __tablename__ = "tenants"

            id: UUID = Field(default_factory=uuid4, primary_key=True)
            name: str
            slug: str = Field(unique=True)
            plan_tier: str = Field(default="free")
            created_at: datetime = Field(default_factory=datetime.utcnow)


        class User(SQLModel, table=True):
            __tablename__ = "users"

            id: UUID = Field(default_factory=uuid4, primary_key=True)
            tenant_id: UUID = Field(foreign_key="tenants.id", index=True)
            external_id: str | None = Field(default=None)  # MS SSO Object ID
            email: str
            role: str = Field(default="member")
            created_at: datetime = Field(default_factory=datetime.utcnow)

        # ... Workspace, Session, FileRecord, ArtifactRecord
"""

from __future__ import annotations
