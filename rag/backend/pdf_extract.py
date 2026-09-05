"""
Read a PDF page by page, using OCR automatically where it is needed.

How it works, per page:
  1. Try normal text extraction with pdfplumber.
  2. If that page gives back almost nothing, it is almost certainly a
     scanned image. Render the page to a picture with PyMuPDF and read
     it with Tesseract OCR instead.
  3. Keep whichever result has more text.

Nothing is ever rejected. A scanned page becomes text and is stored
exactly like any other page.

OCR is slow (a few seconds per page), so every OCR result is cached to
backend/ocr_cache/. The cache is keyed to the PDF's contents, so if you
replace a PDF with a different file the cache is rebuilt automatically.

Try it on one file:
    python -m backend.pdf_extract data/1001.pdf
"""

import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List

import pdfplumber
import pymupdf
import pytesseract
from PIL import Image

from backend.config import (
    DATA_DIR,
    MIN_CHARS_PER_PAGE,
    OCR_CACHE_DIR,
    OCR_DPI,
    OCR_LANG,
    TESSERACT_CMD,
)


# --- Tesseract setup ------------------------------------------------

_tesseract_ready = False


def configure_tesseract() -> str:
    """
    Point pytesseract at the Tesseract program and return its version.

    Tries TESSERACT_CMD from .env first, then falls back to whatever is on
    the system PATH. The fallback matters because .env holds one machine's
    path - a teammate on a Mac or Linux box should not have to edit it.
    """
    global _tesseract_ready

    attempts = []
    if TESSERACT_CMD:
        attempts.append(TESSERACT_CMD)
    attempts.append("tesseract")          # whatever is on PATH

    last_error = None
    for command in attempts:
        pytesseract.pytesseract.tesseract_cmd = command
        try:
            version = str(pytesseract.get_tesseract_version())
        except Exception as exc:
            last_error = exc
            continue
        _tesseract_ready = True
        return version

    raise RuntimeError(
        "Could not run Tesseract. Install it, then either put it on your "
        "PATH or set TESSERACT_CMD in backend/.env to the full path of the "
        f"tesseract program. Tried: {attempts}. Details: {last_error}"
    )


# --- Boilerplate / watermark removal --------------------------------
#
# BIS PDFs downloaded through the public portal carry a watermark line on
# EVERY page, e.g.
#   "Free Standard provided by BIS via BSB Edge Private Limited to
#    <name>(<email>) <ip address>."
#
# Two reasons to strip it:
#   1. It is noise - repeated hundreds of times it pollutes search results.
#   2. It contains someone's email address and IP address, which should not
#      end up in the vector database or in prompts sent to an LLM.
#
# It also breaks scan detection: a scanned page whose only text is this
# watermark looks like it "has text" when it really has none.

WATERMARK_PATTERNS = [
    # "Free Standard provided by BIS ... 223.233.85.151."
    r"Free Standard provided by BIS[\s\S]{0,300}?\d{1,3}(?:\.\d{1,3}){3}\.?",
    # Common alternative headers seen on BIS/other portal downloads
    r"Licen[cs]ed?\s+to[\s\S]{0,200}?\d{1,3}(?:\.\d{1,3}){3}\.?",
    r"Downloaded\s+by[\s\S]{0,200}?\d{1,3}(?:\.\d{1,3}){3}\.?",
]

_WATERMARK_RES = [re.compile(p, re.IGNORECASE) for p in WATERMARK_PATTERNS]


def clean_page_text(text: str) -> tuple:
    """
    Remove download watermarks and tidy whitespace.

    Returns (cleaned_text, characters_removed).
    """
    if not text:
        return "", 0

    original_length = len(text)
    for pattern in _WATERMARK_RES:
        text = pattern.sub(" ", text)

    # Collapse the blank space left behind
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = text.strip()

    return text, original_length - len(text)


# --- Result types ---------------------------------------------------

@dataclass
class PageText:
    page: int          # 1-based page number
    text: str
    method: str        # "text", "ocr", "ocr-cached" or "empty"
    chars: int
    boilerplate_removed: int = 0


@dataclass
class PdfResult:
    filename: str
    total_pages: int
    pages: List[PageText]

    @property
    def total_chars(self) -> int:
        return sum(p.chars for p in self.pages)

    @property
    def ocr_pages(self) -> int:
        return sum(1 for p in self.pages if p.method.startswith("ocr"))

    @property
    def empty_pages(self) -> int:
        return sum(1 for p in self.pages if p.method == "empty")

    @property
    def boilerplate_removed(self) -> int:
        return sum(p.boilerplate_removed for p in self.pages)

    @property
    def chars_per_page(self) -> float:
        return self.total_chars / self.total_pages if self.total_pages else 0.0

    def summary(self) -> dict:
        return {
            "filename": self.filename,
            "total_pages": self.total_pages,
            "total_chars": self.total_chars,
            "chars_per_page": round(self.chars_per_page, 1),
            "ocr_pages": self.ocr_pages,
            "empty_pages": self.empty_pages,
            "boilerplate_chars_removed": self.boilerplate_removed,
        }


# --- OCR cache ------------------------------------------------------

def _file_hash(path: Path) -> str:
    """SHA-256 of the file's contents, read in blocks so memory stays low."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cache_file(pdf_path: Path) -> Path:
    return OCR_CACHE_DIR / f"{pdf_path.stem}.json"


def _load_cache(pdf_path: Path, file_hash: str) -> Dict[str, str]:
    """Return cached OCR text, or an empty cache if the PDF has changed."""
    cache_path = _cache_file(pdf_path)
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if data.get("file_sha256") != file_hash:
        return {}                      # PDF was replaced - ignore old cache
    return data.get("pages", {})


def _save_cache(pdf_path: Path, file_hash: str, pages: Dict[str, str]) -> None:
    if not pages:
        return
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"file_sha256": file_hash, "pages": pages}
    _cache_file(pdf_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --- OCR ------------------------------------------------------------

def _ocr_page(mu_doc: "pymupdf.Document", page_index: int) -> str:
    """Render one page to an image and read it with Tesseract."""
    if not _tesseract_ready:
        configure_tesseract()
    page = mu_doc[page_index]
    pixmap = page.get_pixmap(dpi=OCR_DPI)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    return pytesseract.image_to_string(image, lang=OCR_LANG).strip()


# --- Main entry point -----------------------------------------------

def extract_pdf(pdf_path: Path, verbose: bool = True, max_pages: int = 0) -> PdfResult:
    """
    Extract text from every page of one PDF, using OCR where needed.

    max_pages=0 means "all pages". Pass a small number to read just the
    cover (used by build_catalog, so we do not OCR a whole document just
    to read its title).
    """
    pdf_path = Path(pdf_path)
    file_hash = _file_hash(pdf_path)
    cache = _load_cache(pdf_path, file_hash)
    cache_changed = False
    pages: List[PageText] = []

    with pdfplumber.open(pdf_path) as plumber_doc, pymupdf.open(pdf_path) as mu_doc:
        total_pages = len(plumber_doc.pages)

        page_limit = total_pages if max_pages <= 0 else min(max_pages, total_pages)

        for index, plumber_page in enumerate(plumber_doc.pages[:page_limit]):
            page_no = index + 1
            try:
                raw_text = (plumber_page.extract_text() or "").strip()
            except Exception:
                raw_text = ""

            # Strip watermarks FIRST, so a page whose only text is a
            # watermark is correctly recognised as a scan.
            text, removed = clean_page_text(raw_text)
            method = "text"

            # Too little text - assume this page is a scan and OCR it.
            if len(text) < MIN_CHARS_PER_PAGE:
                key = str(page_no)
                if key in cache:
                    raw_ocr, ocr_method = cache[key], "ocr-cached"
                else:
                    if verbose:
                        print(f"    page {page_no}/{total_pages}: running OCR...")
                    raw_ocr = _ocr_page(mu_doc, index)
                    cache[key] = raw_ocr      # cache the RAW result
                    cache_changed = True
                    ocr_method = "ocr"

                ocr_text, ocr_removed = clean_page_text(raw_ocr)

                # Only switch to the OCR result if it actually found more.
                if len(ocr_text) > len(text):
                    text, method, removed = ocr_text, ocr_method, ocr_removed

            if not text:
                method = "empty"

            pages.append(
                PageText(
                    page=page_no,
                    text=text,
                    method=method,
                    chars=len(text),
                    boilerplate_removed=removed,
                )
            )

    if cache_changed:
        _save_cache(pdf_path, file_hash, cache)

    return PdfResult(
        filename=pdf_path.name, total_pages=total_pages, pages=pages
    )


# --- Command line test ----------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backend.pdf_extract <file.pdf>")
        print("Example: python -m backend.pdf_extract data/1001.pdf")
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        target = DATA_DIR / Path(sys.argv[1]).name
    if not target.exists():
        print(f"File not found: {sys.argv[1]}")
        print(f"Also looked in: {DATA_DIR}")
        sys.exit(1)

    print(f"Tesseract version: {configure_tesseract()}")
    print(f"Reading {target.name} ...")

    result = extract_pdf(target)

    print(f"\n{'page':>5}  {'chars':>7}  method")
    print("-" * 32)
    for page in result.pages:
        print(f"{page.page:>5}  {page.chars:>7}  {page.method}")

    print("-" * 32)
    print(json.dumps(result.summary(), indent=2))

    first_text = next((p.text for p in result.pages if p.text), "")
    if first_text:
        print("\n--- first 400 characters found ---")
        print(first_text[:400])
