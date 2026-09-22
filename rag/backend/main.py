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

import hmac
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Deque, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import (
    Depends, FastAPI, File, Header, HTTPException, Request, UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.config import (
    ALLOWED_ORIGINS,
    API_KEY,
    AUDIO_INPUT_ENABLED,
    AUDIO_MAX_FILE_MB,
    BACKEND_DIR,
    COLLECTION_NAME,
    INGEST_API_KEY,
    INGEST_ENABLED,
    MAX_INGEST_CHARS,
    MAX_INGEST_DOCS,
    RATE_LIMIT_REQUESTS,
    MAX_QUERY_CHARS,
    QUERY_TRANSLATION_ENABLED,
    REQUIRE_API_KEY,
    RATE_LIMIT_WINDOW_SECONDS,
)
from backend.documents import UnsupportedDocument, extract_upload
from backend.recommend import (
    RecommendResponse, recommend, recommend_from_document,
)

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

    if QUERY_TRANSLATION_ENABLED:
        logger.info("Loading IndicLID and distilled IndicTrans2 models...")
        from backend.query_language import load_models
        load_models()

    if os.getenv("GROQ_API_KEY"):
        from langchain_groq import ChatGroq
        state["llm"] = ChatGroq(model="openai/gpt-oss-120b", temperature=0.1)
        logger.info("Ready.")
    else:
        logger.warning("GROQ_API_KEY is not set - /api/recommend will "
                       "return 503 until it is added to backend/.env")
    if REQUIRE_API_KEY:
        logger.info("API key required on /api/ routes.")
    else:
        logger.warning(
            "No API_KEY set - /api/ routes are OPEN to anyone who can reach "
            "this server. Fine locally; set API_KEY before exposing it."
        )
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

def _keys_match(supplied: Optional[str], expected: str) -> bool:
    """
    Compare two keys without leaking timing information.

    A plain `a == b` stops at the first differing character, so how long
    it takes hints at how much of the key was right. compare_digest always
    takes the same time. It matters little at this scale, but it costs
    nothing to do properly.
    """
    if not supplied or not expected:
        return False
    return hmac.compare_digest(supplied, expected)


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """
    Guard for the read routes.

    When API_KEY is empty the routes stay open, which keeps local
    development and demos frictionless. Setting API_KEY in .env turns the
    check on for every /api/ route at once.
    """
    if not REQUIRE_API_KEY:
        return
    if not _keys_match(x_api_key, API_KEY):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key. Send it in an X-API-Key header.",
        )


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
    if not _keys_match(x_api_key, INGEST_API_KEY):
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
        "api_key_required": REQUIRE_API_KEY,
    }


class ClarifyAnswer(BaseModel):
    """One answer to one clarifying question, echoed back by the client."""
    label: str = Field(default="", max_length=200)
    # The standard ids this answer keeps. Server-side this can only NARROW
    # candidates that retrieval returned on this request's own evidence, so
    # a client cannot use it to introduce a standard of its own choosing.
    select: List[str] = Field(default_factory=list, max_length=20)


class RecommendRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    # Cross-questioning is stateless: the client returns the answers it was
    # given and the dimensions already covered, rather than the server
    # holding a session. Nothing here is trusted beyond narrowing.
    answers: List[ClarifyAnswer] = Field(default_factory=list, max_length=8)
    asked: List[str] = Field(default_factory=list, max_length=8)
    include_tender: bool = True
    include_gem: bool = True


@app.post("/api/recommend", response_model=RecommendResponse,
          dependencies=[Depends(require_api_key)])
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
        return recommend(
            query, retriever, llm,
            answers=[a.model_dump() for a in request.answers],
            asked=request.asked,
            include_tender=request.include_tender,
            include_gem=request.include_gem,
        )
    except Exception:
        logger.exception("Recommendation failed for query %r", query[:100])
        raise HTTPException(
            status_code=500,
            detail="Could not produce a recommendation. Please try again.",
        )


@app.post("/api/recommend/upload", response_model=RecommendResponse,
          dependencies=[Depends(require_api_key)])
async def recommend_from_uploaded_document(file: UploadFile = File(...)):
    """
    Recommend standards for an uploaded tender document.

    Accepts .pdf, .docx, .txt and .md. Scanned PDFs are OCR'd with the
    same extractor used for the standards corpus.

    The document is searched in passages rather than as one long query:
    embedding a whole tender at once averages everything in it into a
    vague vector, and a tender covering several products should be able
    to surface several standards.
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

    data = await file.read()

    try:
        text, info = extract_upload(file.filename, data)
    except UnsupportedDocument as exc:
        # These messages are written for the user, so pass them through.
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Failed to read upload %r", file.filename)
        raise HTTPException(status_code=400, detail="Could not read that file.")

    logger.info("Upload %r: %s", file.filename, info)

    try:
        return recommend_from_document(text, retriever, llm)
    except Exception:
        logger.exception("Recommendation failed for upload %r", file.filename)
        raise HTTPException(
            status_code=500,
            detail="Could not produce a recommendation from that document.",
        )


# --- voice input ---------------------------------------------------------

class AudioQuality(BaseModel):
    """How sure Whisper was about what it heard."""
    avg_logprob: Optional[float] = None
    no_speech_prob: Optional[float] = None


class AudioRecommendResponse(RecommendResponse):
    """
    A normal recommendation, plus what was heard.

    Defined here rather than on RecommendResponse so the text and upload
    routes return exactly what they did before. `transcript` is set only
    when the recording was accepted; the frontend uses that to decide
    whether to put the text in the search box.
    """
    transcript: Optional[str] = None
    audio_quality: Optional[AudioQuality] = None


AUDIO_RETRY_MESSAGE = (
    "I couldn't hear that clearly enough to search on it. Please try again, "
    "speaking close to the microphone, or type your query instead."
)
AUDIO_UNAVAILABLE_MESSAGE = (
    "Voice input isn't available right now. Please try again in a moment, "
    "or type your query instead."
)


@app.post("/api/recommend/audio", response_model=AudioRecommendResponse,
          dependencies=[Depends(require_api_key)])
async def recommend_from_audio(file: UploadFile = File(...)):
    """
    Recommend standards for a spoken query.

    The recording goes to Groq's Whisper, which returns English text in one
    step whatever language was spoken. That text is then recommended on
    exactly as a typed query is.

    Fail-safe: if the audio was unclear, silent, or the transcription call
    failed, this returns a clarification asking the user to repeat or type,
    and never searches on a guess.
    """
    from backend.audio_input import (
        SUPPORTED_AUDIO_SUFFIXES, rejection_reason, transcribe_to_english,
    )

    if not AUDIO_INPUT_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Voice input is disabled. Set AUDIO_INPUT_ENABLED=true in .env.",
        )

    retriever = state.get("retriever")
    llm = state.get("llm")

    if retriever is None:
        raise HTTPException(status_code=503, detail="Search index is not ready.")
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="Language model is not configured. Set GROQ_API_KEY in .env.",
        )

    # The extension, not the content type: browsers label the same webm
    # recording as audio/webm, video/webm or audio/webm;codecs=opus.
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot read '{suffix or 'that file type'}' audio. Supported "
                   "types: " + ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES)),
        )

    # Read at most one byte past the limit, so an oversized upload is
    # refused without holding all of it in memory.
    limit = int(AUDIO_MAX_FILE_MB * 1024 * 1024)
    data = await file.read(limit + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The recording is empty.")
    if len(data) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"Recording is too large. The limit is {AUDIO_MAX_FILE_MB:g} MB.",
        )

    # Transcription is a network call of a few seconds. Running it in the
    # thread pool keeps the server answering other requests meanwhile.
    try:
        heard = await run_in_threadpool(
            transcribe_to_english, data, f"recording{suffix}"
        )
    except Exception:
        logger.exception("Transcription failed for %r (%d bytes)",
                         file.filename, len(data))
        return AudioRecommendResponse(
            clarification_needed=True, message=AUDIO_UNAVAILABLE_MESSAGE,
        )

    quality = AudioQuality(
        avg_logprob=heard.get("avg_logprob"),
        no_speech_prob=heard.get("no_speech_prob"),
    )
    reason = rejection_reason(heard)
    if reason:
        logger.info("Audio not searched: %s", reason)
        return AudioRecommendResponse(
            clarification_needed=True, message=AUDIO_RETRY_MESSAGE,
            audio_quality=quality,
        )

    query = heard["text"][:MAX_QUERY_CHARS]
    logger.info("Audio heard (%d chars, avg_logprob %.2f, no_speech %.2f)",
                len(query), quality.avg_logprob, quality.no_speech_prob)

    try:
        result = recommend(query, retriever, llm)
    except Exception:
        logger.exception("Recommendation failed for spoken query %r", query[:100])
        raise HTTPException(
            status_code=500,
            detail="Could not produce a recommendation. Please try again.",
        )

    return AudioRecommendResponse(
        **result.model_dump(), transcript=query, audio_quality=quality,
    )


@app.get("/api/standards/references",
         dependencies=[Depends(require_api_key)])
async def standard_references(standard_id: str, depth: int = 2):
    """
    The citation chain for a standard: what it cites, and what those cite.

    Depth is limited by the corpus - a cited standard we do not hold is a
    leaf, because we cannot read its own references until it is indexed.
    """
    from backend.references import chain, graph_stats

    stats = graph_stats()
    if not stats["edges"]:
        raise HTTPException(
            status_code=503,
            detail="The reference graph has not been built. Run: "
                   "python -m backend.build_reference_graph",
        )

    depth = max(1, min(depth, 4))
    return {"stats": stats, "chain": chain(standard_id.strip(), depth=depth)}


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
