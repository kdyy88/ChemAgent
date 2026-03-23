"""
ChemAgent FastAPI application — v2 concurrent architecture.

Startup:
  - Initialises async Redis connection pool (max_connections=100)
  - Loads built-in tool registry
  - Registers slowapi rate limiter

Shutdown:
  - Closes Redis connection pool
  - Shuts down shared IO_POOL (non-blocking, drain in background)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.chat import router as chat_router
from app.api.rdkit_api import router as rdkit_router
from app.api.babel_api import router as babel_router
from app.api.health import router as health_router
from app.core.limiter import limiter
from app.core.network import get_allowed_origins
from app.core.redis_client import close_redis, init_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    await init_redis()

    # Load all built-in tool specs so the catalog is ready before accepting
    # WebSocket connections. This is a fast pass (only imports, no I/O).
    from app.core.tooling import tool_registry
    tool_registry.load_builtin_tools()

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await close_redis()

    # Drain IO_POOL without blocking the event loop — remaining futures will
    # complete naturally; only new submissions are rejected.
    from app.core.executor import IO_POOL
    IO_POOL.shutdown(wait=False)


app = FastAPI(title="ChemAgent API", lifespan=lifespan)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


# ── CORS ──────────────────────────────────────────────────────────────────────
allowed_origins = get_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials="*" not in allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(chat_router, prefix="/api/chat")
app.include_router(rdkit_router, prefix="/api")
app.include_router(babel_router, prefix="/api")
app.include_router(health_router, prefix="/api/health")


@app.get("/")
def read_root():
    return JSONResponse(
        {
            "name": "ChemAgent API",
            "status": "ok",
            "websocket": "/api/chat/ws",
            "health": "/api/health",
            "queue_health": "/api/health/queue",
            "allowed_origins": allowed_origins,
            "message": "Use the Next.js frontend for the full session-based streaming experience.",
        }
    )
