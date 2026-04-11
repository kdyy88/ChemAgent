"""Unified application settings via Pydantic BaseSettings.

Reserved for migration of scattered ``os.getenv()`` calls into a single
validated ``Settings`` model.

See: https://docs.pydantic.dev/latest/concepts/pydantic_settings/

Current state: placeholder (no runtime code). All config is still read
via direct ``os.environ.get()`` / ``os.getenv()`` in individual modules:
    - app/core/redis_pool.py
    - app/core/network.py
    - app/main.py
    - app/services/task_runner/worker.py

TODO: implement Settings model
--------------------------------
Add ``pydantic-settings>=2.0`` to pyproject.toml, then implement::

    from __future__ import annotations
    from functools import lru_cache
    from pathlib import Path
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", extra="ignore")

        # ── Database ────────────────────────────────────────────────────────
        database_url: str = "sqlite+aiosqlite:///./chemagent.db"
        auto_create_tables: bool = True   # False in prod; use Alembic instead

        # ── Redis ───────────────────────────────────────────────────────────
        redis_url: str = "redis://localhost:6379/0"

        # ── CORS ────────────────────────────────────────────────────────────
        cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

        # ── File storage ────────────────────────────────────────────────────
        upload_root: Path = Path("./data/uploads")
        max_upload_bytes: int = 200 * 1024 * 1024   # 200 MB
        artifact_size_threshold_bytes: int = 1024 * 1024   # 1 MB router threshold

        # ── Artifact TTLs (seconds) ─────────────────────────────────────────
        artifact_temp_ttl_seconds: int = 3600       # 1 hour (temp tier)
        artifact_workspace_ttl_seconds: int = 0     # 0 = no expiry
        artifact_expiry_warning_seconds: int = 1800

        # ── Worker ──────────────────────────────────────────────────────────
        worker_max_jobs: int = 2
        worker_job_timeout: int = 120
        task_poll_interval: float = 0.2

        # ── Auth ────────────────────────────────────────────────────────────
        dev_mode: bool = True    # False → require valid Bearer token

        # ── LangGraph ───────────────────────────────────────────────────────
        checkpoint_db_path: str = ""   # empty = use default SQLite path


    @lru_cache(maxsize=1)
    def get_settings() -> Settings:
        return Settings()

Migration order
---------------
1. Add pydantic-settings to pyproject.toml.
2. Implement the Settings class above.
3. Replace os.getenv() in redis_pool.py → get_settings().redis_url
4. Replace get_allowed_origins() in network.py → get_settings().cors_allowed_origins
5. Replace scattered os.environ in worker.py → get_settings().worker_*
6. Replace _resolve_checkpoint_db_path() in runtime.py → get_settings().checkpoint_db_path
"""
