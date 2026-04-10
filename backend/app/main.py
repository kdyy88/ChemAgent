import logging
import logging.config
import os
import warnings

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
)

_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LOG_FILE = os.environ.get("LOG_FILE", "")  # empty → stdout only

_handlers: dict = {
    "console": {
        "class": "logging.StreamHandler",
        "formatter": "verbose",
        "stream": "ext://sys.stderr",
    }
}
if _LOG_FILE:
    _handlers["file"] = {
        "class": "logging.FileHandler",
        "formatter": "verbose",
        "filename": _LOG_FILE,
        "encoding": "utf-8",
    }

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": _handlers,
        "root": {
            "level": _LOG_LEVEL,
            "handlers": list(_handlers.keys()),
        },
        "loggers": {
            # Keep noisy libraries at WARNING unless debug mode
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
            "openai": {"level": "WARNING"},
            "langchain": {"level": "WARNING"},
            "langgraph": {"level": "WARNING"},
            # SQLite checkpoint I/O — always suppress, not useful for LLM debugging
            "aiosqlite": {"level": "WARNING"},
            # Our own code always at configured level
            "app": {"level": _LOG_LEVEL, "propagate": True},
        },
    }
)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agents.runtime import initialize_graph_runtime, shutdown_graph_runtime
from app.api.sse.chat import router as sse_chat_router
from app.api.rest.rdkit import router as rdkit_router
from app.api.rest.babel import router as babel_router
from app.api.rest.scratchpad import router as scratchpad_router
from app.core.network import get_allowed_origins


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await initialize_graph_runtime()
    try:
        yield
    finally:
        await shutdown_graph_runtime()


app = FastAPI(title="ChemAgent API", lifespan=lifespan)

allowed_origins = get_allowed_origins()

# Credentials cannot be combined with a wildcard origin (CORS spec violation).
# When '*' is in the list the browser would reject the preflight response anyway,
# so we explicitly disable credentials in that case.
_allow_credentials = "*" not in allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sse_chat_router, prefix="/api/chat")
app.include_router(rdkit_router, prefix="/api")
app.include_router(babel_router, prefix="/api")
app.include_router(scratchpad_router, prefix="/api/scratchpad")


@app.get("/")
def read_root():
    return JSONResponse(
        {
            "name": "ChemAgent API",
            "status": "ok",
            "websocket": "/api/chat/ws",
            "sse_stream": "/api/chat/stream",
            "allowed_origins": allowed_origins,
            "message": "Use /api/chat/stream (POST, SSE) for the LangGraph-powered experience.",
        }
    )
@app.get("/health")
def health():
    return {"status": "ok"}