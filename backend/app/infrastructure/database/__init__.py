"""Database infrastructure sub-package.

See README.md in this directory for the full schema design, dual-mode URL
strategy, and implementation steps.

TODO: implement
    - async engine creation from settings.database_url
    - async_sessionmaker / get_db_session() FastAPI Depends
    - Import all SQLModel models here to ensure they are registered with
      SQLModel.metadata before create_all() is called in main.py lifespan.
"""

from __future__ import annotations

# TODO: uncomment after adding sqlmodel + aiosqlite/asyncpg to pyproject.toml
#
# from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
# from sqlmodel import SQLModel
# from app.core.config import get_settings
#
# _engine: create_async_engine | None = None
# _session_factory: async_sessionmaker[AsyncSession] | None = None
#
#
# def get_engine():
#     global _engine
#     if _engine is None:
#         settings = get_settings()
#         _engine = create_async_engine(
#             settings.database_url,
#             echo=settings.dev_mode,
#             pool_pre_ping=True,
#         )
#     return _engine
#
#
# def get_session_factory() -> async_sessionmaker[AsyncSession]:
#     global _session_factory
#     if _session_factory is None:
#         _session_factory = async_sessionmaker(
#             get_engine(), expire_on_commit=False, class_=AsyncSession
#         )
#     return _session_factory
#
#
# async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
#     """FastAPI Depends generator – yields one session per request."""
#     async with get_session_factory()() as session:
#         yield session
#
#
# async def create_all_tables() -> None:
#     """Create all SQLModel tables.  Called from main.py lifespan when auto_create_tables=True."""
#     async with get_engine().begin() as conn:
#         await conn.run_sync(SQLModel.metadata.create_all)
