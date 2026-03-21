from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.rdkit_api import router as rdkit_router
from app.api.babel_api import router as babel_router
from app.core.network import get_allowed_origins

app = FastAPI(title="ChemAgent API")

allowed_origins = get_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials="*" not in allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api/chat")
app.include_router(rdkit_router, prefix="/api")
app.include_router(babel_router, prefix="/api")


@app.get("/")
def read_root():
    return JSONResponse(
        {
            "name": "ChemAgent API",
            "status": "ok",
            "websocket": "/api/chat/ws",
            "allowed_origins": allowed_origins,
            "message": "Use the Next.js frontend for the full session-based streaming experience.",
        }
    )