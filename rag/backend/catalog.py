"""
Loads standards_catalog.json - the link between a PDF filename and the
real Indian Standard it contains.

Without this, a chunk only knows it came from "33.pdf". With it, the chunk
knows it came from IS 33 : 1992, "Inorganic pigments and extenders for
paints - Methods of sampling and test".

The field names deliberately match the columns the scraper writes to its
SQLite database, so the two halves of the project join cleanly later.
"""

import json
from typing import Dict

from backend.config import CATALOG_PATH

# Fields copied onto every chunk of a document.
CHUNK_FIELDS = (
    "standard_id",
    "title",
    "doc_type",
    "number",
    "part",
    "publication_date",
    "edition",
    "status",
    "reaffirmed_year",
    "confidence",
)


def load_catalog() -> Dict[str, dict]:
    """Read the catalog. Returns an empty dict if it has not been built yet."""
    if not CATALOG_PATH.exists():
        return {}
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{CATALOG_PATH.name} is not valid JSON ({exc}). "
            "Fix it, or delete it and run: python -m backend.build_catalog"
        ) from exc


def metadata_for(filename: str, catalog: Dict[str, dict]) -> dict:
    """
    Build the per-chunk metadata for one source file.

    Chroma rejects None values, so empty fields are dropped rather than
    stored as null.
    """
    entry = catalog.get(filename, {})
    meta = {}
    for field in CHUNK_FIELDS:
        value = entry.get(field)
        if value not in (None, ""):
            meta[field] = str(value)
    if "standard_id" not in meta:
        meta["standard_id"] = filename          # honest fallback
    return meta
