import warnings
warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agents.main_agent.runtime import initialize_graph_runtime, shutdown_graph_runtime
from app.api.v1.chat import router as v1_chat_router
from app.api.v1.rdkit import router as v1_rdkit_router
from app.api.v1.babel import router as v1_babel_router
from app.api.v1.artifacts import router as v1_artifacts_router
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

# v1 versioned routes
app.include_router(v1_chat_router, prefix="/api/v1/chat")
app.include_router(v1_rdkit_router, prefix="/api/v1")
app.include_router(v1_babel_router, prefix="/api/v1")
app.include_router(v1_artifacts_router, prefix="/api/v1")


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