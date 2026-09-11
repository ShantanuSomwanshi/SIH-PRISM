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

OCR is slow (a few seconds per page), so OCR results for corpus files
(PDFs inside DATA_DIR) are cached to backend/ocr_cache/. The cache is keyed
to the PDF's contents, so if you replace a PDF with a different file the
cache is rebuilt automatically. Uploaded documents are never cached - see
extract_pdf_bytes().

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
from typing import Dict, List, Optional

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
    OCR_LEGACY_FONTS,
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


# --- Legacy-font Hindi detection ------------------------------------
#
# Older BIS PDFs set their Hindi text in a legacy font - Krutidev, Chanakya
# and relatives - from before Unicode was standard. These fonts paint
# Devanagari glyphs onto ordinary Latin codepoints. On screen the page is
# perfect Hindi; pulled out as text it reads
#
#     भारतीय मानक   ->   Hkkjrh; ekud
#
# So the text is not MISSING, it is MIS-ENCODED. The page has plenty of
# characters, so the "too little text" rule above never fires, and every
# one of those characters is garbage. There is no model that can undo this
# reliably, because the mapping differs per font. The rendered page is
# correct though, so OCR reads it perfectly well.
#
# Detecting it by looking at the CHARACTERS is a trap, and this code tried
# that first. Two rules were tested against real files and both failed:
#
#   "unusual characters on the page"  flagged 9 of 44 pages of IS 10262 -
#       8 of them clean English mix-design pages full of = x + - ≈
#   "substitute glyphs inside words"  flagged a committee-membership page
#       ("[REPRESENTING", "(Ex-officio)]" - square brackets are ordinary
#       English punctuation) and eleven engineering drawings in IS 15500
#       (where Ø means diameter, not a Devanagari glyph)
#
# The character frequencies of legacy Devanagari and of technical English
# genuinely overlap, so no threshold separates them cleanly.
#
# The PDF, however, records which font drew each page, and these legacy
# fonts identify themselves by name. Asking the file is exact rather than
# statistical: across 201 pages of the corpus it flags one page - the one
# that is actually Krutidev-style Hindi - in 0.04 seconds.
#
# Note what is deliberately NOT here: Mangal, Kokila, Nirmala, Aparajita
# and Noto are UNICODE Devanagari fonts. Pages using those already extract
# as proper Devanagari and must never be sent to OCR. IS 15500's cover is
# exactly that case.
LEGACY_DEVANAGARI_FONTS = re.compile(
    r"kruti|chanakya|dev[\s_-]?lys|shusha|shivaji|(?<![a-z])agra|"
    r"shree[\s_-]?(?:dev|lipi)|amarujala|jagran|naidunia|yogesh|kundli|"
    r"aps[\s_-]?dv|bhasha|millennium|x[\s_-]?dvng|isfoc|gist[\s_-]?dv|"
    r"sanskrit[\s_-]?99|preeti|kantipur|akruti",
    re.IGNORECASE,
)


def has_devanagari(text: str) -> bool:
    """True if the text contains real Devanagari characters."""
    return any("ऀ" <= c <= "ॿ" for c in text or "")


def page_uses_legacy_font(mu_page) -> bool:
    """
    Does this page draw text with a pre-Unicode Devanagari font?

    get_fonts() returns tuples whose fourth item is the base font name,
    e.g. "GBGGJG+WalkmanChanakya901Bold". An unknown font is never
    flagged, so a font family missing from the list above costs us
    nothing beyond the status quo.
    """
    try:
        return any(
            LEGACY_DEVANAGARI_FONTS.search(font[3] or "")
            for font in mu_page.get_fonts(full=False)
        )
    except Exception:
        return False


# --- Result types ---------------------------------------------------

@dataclass
class PageText:
    page: int          # 1-based page number
    text: str
    method: str        # "text", "ocr", "ocr-cached", "legacy-font" or "empty"
    chars: int
    boilerplate_removed: int = 0
    legacy_font: bool = False   # page was set in a legacy Devanagari font


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
    def legacy_font_pages(self) -> int:
        return sum(1 for p in self.pages if p.legacy_font)

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
            "legacy_font_pages": self.legacy_font_pages,
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
    # Cached text also depends on which language packs Tesseract used.
    # Without this, adding OCR_LANG=eng+hin would silently keep serving the
    # old English-only reading of every Hindi page. Older cache files have
    # no ocr_lang key; those were all written with "eng".
    if data.get("ocr_lang", "eng") != OCR_LANG:
        return {}
    return data.get("pages", {})


def _save_cache(pdf_path: Path, file_hash: str, pages: Dict[str, str]) -> None:
    if not pages:
        return
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"file_sha256": file_hash, "ocr_lang": OCR_LANG, "pages": pages}
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
#
# Two ways in, one extraction loop:
#
#   extract_pdf(path)        the corpus. OCR results are cached, because
#                            re-OCRing 63 pages costs minutes.
#   extract_pdf_bytes(data)  an uploaded tender. Read entirely in memory
#                            and NEVER cached.
#
# Why uploads must not touch the cache: the cache file is named after the
# PDF's stem. The upload route used to write every tender to a temp file
# called "upload.pdf", so each tender's OCR text landed in
# ocr_cache/upload.json - kept on the server after the request ended,
# overwritten by the next upload, and shared by two uploads running at the
# same time. A tender is the buyer's document, not part of the corpus, and
# nothing about it should outlive the request.


def _is_corpus_file(pdf_path: Path) -> bool:
    """True if the PDF lives inside DATA_DIR, i.e. it is part of the corpus."""
    try:
        Path(pdf_path).resolve().relative_to(DATA_DIR.resolve())
        return True
    except (ValueError, OSError):
        return False


def _read_pages(plumber_doc, mu_doc, max_pages: int,
                cache: Optional[Dict[str, str]], verbose: bool) -> tuple:
    """
    The per-page extraction loop, shared by both entry points.

    cache is the page -> raw OCR text dict for this file, or None to
    disable caching entirely (nothing read, nothing recorded).

    Returns (total_pages, pages, cache_changed).
    """
    cache_changed = False
    pages: List[PageText] = []
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
        legacy = False

        # Two reasons to OCR a page:
        #   1. it has almost no text        -> it is a scan
        #   2. it has plenty of unreadable text -> legacy Hindi font
        scanned = len(text) < MIN_CHARS_PER_PAGE
        if not scanned and OCR_LEGACY_FONTS and not has_devanagari(text):
            # has_devanagari() first: a page that already yields real
            # Devanagari has a healthy Unicode text layer, whatever
            # fonts it also uses. Nothing to rescue.
            legacy = page_uses_legacy_font(mu_doc[index])

        if scanned or legacy:
            key = str(page_no)
            if cache is not None and key in cache:
                raw_ocr, ocr_method = cache[key], "ocr-cached"
            else:
                if verbose:
                    reason = "legacy Hindi font" if legacy else "scan"
                    print(f"    page {page_no}/{total_pages}: OCR ({reason})...")
                raw_ocr = _ocr_page(mu_doc, index)
                if cache is not None:
                    cache[key] = raw_ocr  # cache the RAW result
                    cache_changed = True
                ocr_method = "ocr"

            ocr_text, ocr_removed = clean_page_text(raw_ocr)

            if legacy:
                # The existing text is long but meaningless, so "more
                # text wins" is the wrong test here - it would always
                # keep the garbage. Take the OCR result only if it came
                # back in real Devanagari.
                if has_devanagari(ocr_text):
                    text, method, removed = ocr_text, ocr_method, ocr_removed
                elif "hin" in OCR_LANG.lower():
                    # We HAD the Hindi pack and OCR still found no
                    # Devanagari on this page. That is not a Hindi page
                    # at all - looks_like_legacy_font() was wrong about
                    # it. Un-flag it and keep the original text.
                    #
                    # This branch exists because the alternative is
                    # destructive: marking it "legacy-font" drops the
                    # page from the index entirely, so one bad guess by
                    # the detector would silently delete a good English
                    # page from the corpus.
                    legacy = False
                else:
                    # No Hindi pack installed, so we cannot tell a real
                    # Hindi page from a mistake. Leave the page as it
                    # is and flag it; ingestion keeps it out of the
                    # index rather than indexing gibberish.
                    method = "legacy-font"
            # Otherwise: only switch if OCR actually found more.
            elif len(ocr_text) > len(text):
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
                legacy_font=legacy,
            )
        )

    return total_pages, pages, cache_changed


def extract_pdf(pdf_path: Path, verbose: bool = True, max_pages: int = 0,
                use_cache: Optional[bool] = None) -> PdfResult:
    """
    Extract text from every page of one PDF on disk, using OCR where needed.

    max_pages=0 means "all pages". Pass a small number to read just the
    cover (used by build_catalog, so we do not OCR a whole document just
    to read its title).

    use_cache=None (the default) caches OCR only for files inside DATA_DIR.
    Anything else - a file handed to the command-line test, a temp file
    from some future caller - is read without leaving a cache entry behind.
    """
    pdf_path = Path(pdf_path)
    if use_cache is None:
        use_cache = _is_corpus_file(pdf_path)

    file_hash = _file_hash(pdf_path) if use_cache else None
    cache = _load_cache(pdf_path, file_hash) if use_cache else None

    with pdfplumber.open(pdf_path) as plumber_doc, pymupdf.open(pdf_path) as mu_doc:
        total_pages, pages, cache_changed = _read_pages(
            plumber_doc, mu_doc, max_pages, cache, verbose
        )

    if use_cache and cache_changed:
        _save_cache(pdf_path, file_hash, cache)

    return PdfResult(
        filename=pdf_path.name, total_pages=total_pages, pages=pages
    )


def extract_pdf_bytes(data: bytes, filename: str = "upload.pdf",
                      verbose: bool = False, max_pages: int = 0) -> PdfResult:
    """
    Extract text from a PDF held in memory - an uploaded tender.

    Nothing is written anywhere: no temp file, no OCR cache. Both PDF
    libraries open the bytes directly.
    """
    with pdfplumber.open(io.BytesIO(data)) as plumber_doc, \
            pymupdf.open(stream=data, filetype="pdf") as mu_doc:
        total_pages, pages, _ = _read_pages(
            plumber_doc, mu_doc, max_pages, cache=None, verbose=verbose
        )

    return PdfResult(filename=filename, total_pages=total_pages, pages=pages)


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
    print("-" * 44)
    for page in result.pages:
        note = "   <- legacy Hindi font" if page.legacy_font else ""
        print(f"{page.page:>5}  {page.chars:>7}  {page.method}{note}")

    print("-" * 44)
    if result.legacy_font_pages and "hin" not in OCR_LANG:
        print(
            f"NOTE: {result.legacy_font_pages} page(s) are Hindi in a legacy "
            "font and were left unreadable.\n"
            "      Install the Tesseract Hindi pack and set OCR_LANG=eng+hin "
            "to read them."
        )
    print(json.dumps(result.summary(), indent=2))

    first_text = next((p.text for p in result.pages if p.text), "")
    if first_text:
        print("\n--- first 400 characters found ---")
        print(first_text[:400])
