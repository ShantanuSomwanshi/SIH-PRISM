"""
Central configuration for the PRISM backend.

Every other backend module imports its paths and settings from here,
so there is exactly one place to change them.

Run all backend commands from the "rag" folder, e.g.:
    python -m backend.pdf_extract data/1001.pdf
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# --- Folder layout -------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent

# Load backend/.env no matter which folder the command was run from
load_dotenv(BACKEND_DIR / ".env")


def _path_from_env(var_name: str, default: Path) -> Path:
    """
    Use the .env value if it is set and non-empty, otherwise the default.

    A relative value (like "./data") is resolved against the backend folder
    where .env lives - NOT against whatever folder you ran the command from.
    That way the same setting works no matter where you start Python.
    """
    value = os.getenv(var_name, "").strip()
    if not value:
        return default
    path = Path(value)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return path.resolve()


# Source PDFs and the vector database (overridable from .env)
DATA_DIR = _path_from_env("DOCUMENTS_DIR", BACKEND_DIR / "data")
CHROMA_DIR = _path_from_env("CHROMA_PERSIST_DIR", BACKEND_DIR / "chroma_db")

# Generated files
OCR_CACHE_DIR = BACKEND_DIR / "ocr_cache"
CATALOG_PATH = BACKEND_DIR / "standards_catalog.json"
MANIFEST_PATH = BACKEND_DIR / "processed_files.json"
REPORT_PATH = BACKEND_DIR / "ingestion_report.json"

# --- Vector store / embeddings -------------------------------------
COLLECTION_NAME = "prism_standards"
EMBEDDING_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# --- GeM marketplace -------------------------------------------------
# Tier 1 of the corpus: the category catalogue export. Short names for the
# whole marketplace, cheap to embed. A standard's PDF is tier 2, fetched
# only once a category has been chosen.
GEM_CATALOG_CSV = BACKEND_DIR / "gem_categories.csv"
GEM_CACHE_DIR = BACKEND_DIR / "gem_cache"

GEM_SEARCH_URL = os.getenv("GEM_SEARCH_URL", "https://mkp.gem.gov.in/search")

# Live lookups are off by default: a demo must never depend on the network,
# and this calls a government portal.
GEM_LIVE_ENABLED = os.getenv("GEM_LIVE_ENABLED", "false").lower() == "true"
GEM_TIMEOUT_SECONDS = float(os.getenv("GEM_TIMEOUT_SECONDS", "12"))
GEM_CACHE_TTL_HOURS = float(os.getenv("GEM_CACHE_TTL_HOURS", "24"))
GEM_REQUEST_DELAY_SECONDS = float(os.getenv("GEM_REQUEST_DELAY_SECONDS", "2"))
GEM_USER_AGENT = os.getenv(
    "GEM_USER_AGENT",
    "PRISM/0.1 (SIH 2026 student project; standards research)",
)

# Words that carry no product information, dropped when turning a tender
# description into a search term.
GEM_QUERY_NOISE_WORDS = {
    "mnt", "mounted", "type", "supply", "make", "model", "qty", "quantity",
    "nos", "with", "and", "for", "the", "of", "as", "per", "conforming",
    "required", "item", "approx",
}

# --- API security ---------------------------------------------------
# Which front-end addresses may call the API from a browser.
# "*" is deliberately NOT the default: it would let any website on the
# internet make requests to this server from a visitor's browser.
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",") if o.strip()
]

# --- Who may call the read routes ---------------------------------
# A key for /api/recommend and friends. Leave it EMPTY and the routes are
# open, which is convenient for local development. Set it and every
# request must carry the same value in an X-API-Key header.
#
# This is a shared secret, not a login: it identifies a calling SYSTEM
# (a procurement portal), not a person.
API_KEY = os.getenv("API_KEY", "").strip()
REQUIRE_API_KEY = bool(API_KEY)

# POST /ingest writes straight into the vector store, and whatever is
# written there is later fed to the LLM as trusted source material.
# So it is off unless switched on, and needs its OWN key - a portal that
# may ask for recommendations should not also be able to add documents.
INGEST_ENABLED = os.getenv("INGEST_ENABLED", "false").lower() == "true"
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "").strip()

# Size limits - stop one request from costing a fortune or exhausting memory.
# A pasted tender section routinely runs past a few thousand characters.
# 4000 rejected real specifications outright.
MAX_QUERY_CHARS = int(os.getenv("MAX_QUERY_CHARS", "40000"))
MAX_INGEST_DOCS = int(os.getenv("MAX_INGEST_DOCS", "100"))
MAX_INGEST_CHARS = int(os.getenv("MAX_INGEST_CHARS", "50000"))

# --- Uploaded documents ---------------------------------------------
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
# Cap OCR work - a 200-page scanned tender would take many minutes.
MAX_DOC_PAGES = int(os.getenv("MAX_DOC_PAGES", "40"))
# A long document is searched in pieces; this caps how many.
MAX_DOC_PASSAGES = int(os.getenv("MAX_DOC_PASSAGES", "15"))
DOC_PASSAGE_CHARS = int(os.getenv("DOC_PASSAGE_CHARS", "900"))

# Simple per-IP rate limit.
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# --- OCR settings ---------------------------------------------------
# Full path to the Tesseract program. Empty means "find it on PATH".
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()

# Language pack(s) Tesseract should use. "eng" ships with every install.
OCR_LANG = os.getenv("OCR_LANG", "eng")

# Resolution used when turning a scanned page into a picture.
# 300 is the usual sweet spot for printed documents.
OCR_DPI = int(os.getenv("OCR_DPI", "300"))

# A page with fewer characters than this is assumed to be a scan,
# and gets sent to OCR.
MIN_CHARS_PER_PAGE = int(os.getenv("MIN_CHARS_PER_PAGE", "200"))
