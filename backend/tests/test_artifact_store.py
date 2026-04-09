from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core import artifact_store
from app.core.artifact_store import (
    get_engine_artifact,
    get_engine_artifact_metadata,
    get_engine_artifact_warning,
    promote_artifact,
    store_engine_artifact,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        self.ttls[key] = ex

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def exists(self, key: str) -> int:
        return 1 if key in self.data else 0

    async def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        ttl = self.ttls.get(key)
        return -1 if ttl is None else ttl

    async def persist(self, key: str) -> int:
        if key not in self.data:
            return 0
        self.ttls[key] = None
        return 1


@pytest.mark.asyncio
async def test_temp_artifact_warning_and_expiry_signal() -> None:
    redis = _FakeRedis()
    artifact_id = "temp_art_test"
    key = artifact_store._artifact_key(artifact_id)

    with patch("app.core.artifact_store.get_redis_pool", new=AsyncMock(return_value=redis)), \
         patch.object(artifact_store, "_EXPIRY_WARNING_SECONDS", 5):
        await store_engine_artifact(artifact_id, {"payload": "x"}, tier="temp", ttl=5)
        metadata = await get_engine_artifact_metadata(artifact_id)
        assert metadata is not None
        assert metadata["tier"] == "temp"
        assert metadata["ttl_seconds"] == 5

        redis.ttls[key] = 3
        warning = await get_engine_artifact_warning(artifact_id)
        assert warning is not None
        assert "nearing expiration" in warning

        del redis.data[key]
        expired_warning = await get_engine_artifact_warning(artifact_id)
        assert expired_warning is not None
        assert "unavailable or has expired" in expired_warning


@pytest.mark.asyncio
async def test_promote_artifact_clears_ttl_and_preserves_payload() -> None:
    redis = _FakeRedis()
    artifact_id = "temp_art_promote"
    key = artifact_store._artifact_key(artifact_id)

    with patch("app.core.artifact_store.get_redis_pool", new=AsyncMock(return_value=redis)):
        await store_engine_artifact(artifact_id, {"canonical_smiles": "CCO"}, tier="temp", ttl=5)
        assert await promote_artifact(artifact_id) is True

        metadata = await get_engine_artifact_metadata(artifact_id)
        assert metadata is not None
        assert metadata["tier"] == "workspace"
        assert "ttl_seconds" not in metadata
        assert await redis.ttl(key) == -1
        assert await get_engine_artifact(artifact_id) == {"canonical_smiles": "CCO"}