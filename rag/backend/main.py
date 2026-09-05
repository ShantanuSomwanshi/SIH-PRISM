"""
PRISM API.

Security in this version:
  * CORS is restricted to a named list of front-end addresses, never "*".
  * POST /ingest is OFF by default and needs an API key when switched on.
    Anything written there is later fed to the LLM as trusted source
    material, so an open ingest route is a way to poison the answers.
  * Request sizes are capped, so one call cannot exhaust memory or run up
    a large embedding bill.
  * A simple per-IP rate limit.
  * Errors are logged in full on the server but returned as generic
    messages - the previous version sent raw Python errors, including
    file paths, straight to the browser.

Includes POST /api/recommend, the main recommendation route.

Run from the "rag" folder:
    uvicorn backend.main:app --reload
"""

import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Deque, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.config import (
    ALLOWED_ORIGINS,
    BACKEND_DIR,
    COLLECTION_NAME,
    INGEST_API_KEY,
    INGEST_ENABLED,
    MAX_INGEST_CHARS,
    MAX_INGEST_DOCS,
    RATE_LIMIT_REQUESTS,
    MAX_QUERY_CHARS,
    RATE_LIMIT_WINDOW_SECONDS,
)
from backend.recommend import RecommendResponse, recommend

load_dotenv(BACKEND_DIR / ".env")

logger = logging.getLogger("prism")
logging.basicConfig(level=logging.INFO)

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup and once at shutdown.

    The embedding model loads here rather than at import time, so
    uvicorn --reload does not reload 2.2 GB of weights on every edit.
    """
    logger.info("Loading embedding model and opening the index...")
    from backend.embeddings import collection_size, get_vector_store

    store = get_vector_store()
    state["vector_store"] = store
    logger.info("%s chunks in collection '%s'.",
                collection_size(store), COLLECTION_NAME)

    # The retriever loads the reranker and the keyword index. Doing it here
    # means the first user request is fast instead of taking a minute.
    logger.info("Building the retriever...")
    from backend.retriever import PrismHybridRetriever
    state["retriever"] = PrismHybridRetriever(verbose=False)

    if os.getenv("GROQ_API_KEY"):
        from langchain_groq import ChatGroq
        state["llm"] = ChatGroq(model="openai/gpt-oss-120b", temperature=0.1)
        logger.info("Ready.")
    else:
        logger.warning("GROQ_API_KEY is not set - /api/recommend will "
                       "return 503 until it is added to backend/.env")
    if INGEST_ENABLED and not INGEST_API_KEY:
        logger.warning(
            "INGEST_ENABLED is true but INGEST_API_KEY is empty - "
            "/ingest will refuse every request until a key is set."
        )
    yield
    state.clear()
    logger.info("Shut down.")


app = FastAPI(title="PRISM RAG Pipeline", lifespan=lifespan)

# Only these origins may call the API from a browser. Using "*" here would
# let any website make requests to this server using a visitor's browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


# --- rate limiting ----------------------------------------------------
# Deliberately dependency-free and in-memory: it resets when the server
# restarts and does not work across multiple server processes. That is
# fine for a prototype. A real deployment would use Redis or a gateway.

_hits: Dict[str, Deque[float]] = {}


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _hits.setdefault(client, deque())

    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()

    if len(window) >= RATE_LIMIT_REQUESTS:
        logger.warning("Rate limit hit by %s", client)
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please slow down."},
        )

    window.append(now)
    return await call_next(request)


# --- auth --------------------------------------------------------------

def require_ingest_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Guard for the ingest route."""
    if not INGEST_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Ingestion is disabled. Set INGEST_ENABLED=true in .env.",
        )
    if not INGEST_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Ingestion is not configured.",
        )
    if x_api_key != INGEST_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


# --- models ------------------------------------------------------------

class DocumentIngest(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_INGEST_CHARS)
    metadata: Optional[dict] = None


# --- routes ------------------------------------------------------------

@app.get("/")
async def health_check():
    from backend.embeddings import collection_size
    store = state.get("vector_store")
    return {
        "status": "ok",
        "collection": COLLECTION_NAME,
        "chunks": collection_size(store) if store else 0,
        "ingest_enabled": INGEST_ENABLED,
    }


class RecommendRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)


@app.post("/api/recommend", response_model=RecommendResponse)
async def recommend_standards(request: RecommendRequest):
    """
    Recommend the most relevant Indian Standard for a product description
    or tender specification.

    Returns either a recommendation, or a clarifying question when the
    description is too vague to separate the candidates.
    """
    retriever = state.get("retriever")
    llm = state.get("llm")

    if retriever is None:
        raise HTTPException(status_code=503, detail="Search index is not ready.")
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="Language model is not configured. Set GROQ_API_KEY in .env.",
        )

    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is empty.")

    try:
        return recommend(query, retriever, llm)
    except Exception:
        logger.exception("Recommendation failed for query %r", query[:100])
        raise HTTPException(
            status_code=500,
            detail="Could not produce a recommendation. Please try again.",
        )


@app.post("/ingest", dependencies=[Depends(require_ingest_key)])
async def ingest_documents(docs: List[DocumentIngest]):
    """
    Add documents to the index directly.

    Requires INGEST_ENABLED=true and a matching X-API-Key header.
    """
    from langchain_core.documents import Document

    if not docs:
        raise HTTPException(status_code=400, detail="No documents supplied.")
    if len(docs) > MAX_INGEST_DOCS:
        raise HTTPException(
            status_code=413,
            detail=f"Too many documents in one request (max {MAX_INGEST_DOCS}).",
        )

    store = state.get("vector_store")
    if store is None:
        raise HTTPException(status_code=503, detail="Index is not ready yet.")

    try:
        store.add_documents(
            documents=[
                Document(page_content=d.content, metadata=d.metadata or {})
                for d in docs
            ],
            ids=[d.id for d in docs],
        )
    except Exception:
        # Full detail to the server log; nothing internal to the caller.
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail="Could not ingest documents.")

    logger.info("Ingested %d documents", len(docs))
    return {"status": "success", "ingested": len(docs)}
