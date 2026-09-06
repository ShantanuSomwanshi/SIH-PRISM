"""
Turn an uploaded tender document into searchable text.

The problem statement asks for "product descriptions, technical
specifications, or tender documents" as input. Typing into a box covers
the first two; this covers the third.

PDFs go through the same extractor the corpus uses, so a scanned tender
is OCR'd automatically - exactly as a scanned standard is.
"""

import io
import tempfile
from pathlib import Path

from backend.config import MAX_DOC_PAGES, MAX_UPLOAD_BYTES

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


class UnsupportedDocument(Exception):
    """Raised when the file cannot be read. The message is shown to the user."""


def _read_txt(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise UnsupportedDocument(
            "Reading .docx files needs the python-docx package. "
            "Install it with: pip install python-docx"
        ) from exc

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text.strip()]

    # Tender requirements live in tables at least as often as in paragraphs.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    return "\n".join(parts)


def _read_pdf(data: bytes) -> tuple:
    """Write to a temp file so the normal extractor can open it."""
    from backend.pdf_extract import extract_pdf

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "upload.pdf"
        path.write_bytes(data)
        result = extract_pdf(path, verbose=False, max_pages=MAX_DOC_PAGES)

    text = "\n\n".join(page.text for page in result.pages if page.text)
    return text, {
        "pages_read": len(result.pages),
        "total_pages": result.total_pages,
        "ocr_pages": result.ocr_pages,
    }


def extract_upload(filename: str, data: bytes) -> tuple:
    """Read an uploaded file and return (text, info)."""
    if not data:
        raise UnsupportedDocument("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UnsupportedDocument(
            f"File is too large. The limit is "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocument(
            f"Cannot read '{suffix or 'that file type'}'. Supported types: "
            + ", ".join(sorted(SUPPORTED_SUFFIXES))
        )

    info = {"filename": filename, "type": suffix}

    if suffix == ".pdf":
        text, pdf_info = _read_pdf(data)
        info.update(pdf_info)
    elif suffix == ".docx":
        text = _read_docx(data)
    else:
        text = _read_txt(data)

    text = text.strip()
    if not text:
        raise UnsupportedDocument(
            "No readable text was found in that file. If it is a scan, the "
            "pages may be too poor for OCR."
        )

    info["characters"] = len(text)
    return text, info
