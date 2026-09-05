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

# POST /ingest writes straight into the vector store, and whatever is
# written there is later fed to the LLM as trusted source material.
# So it is off unless switched on, and needs a key when it is on.
INGEST_ENABLED = os.getenv("INGEST_ENABLED", "false").lower() == "true"
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "").strip()

# Size limits - stop one request from costing a fortune or exhausting memory.
MAX_QUERY_CHARS = int(os.getenv("MAX_QUERY_CHARS", "4000"))
MAX_INGEST_DOCS = int(os.getenv("MAX_INGEST_DOCS", "100"))
MAX_INGEST_CHARS = int(os.getenv("MAX_INGEST_CHARS", "50000"))

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
