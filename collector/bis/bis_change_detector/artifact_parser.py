"""
Turn a downloaded BIS artifact into structured standard records.

Three things this version gets right that the first one did not:

1. IT FINDS THE HEADER ROW. BIS exports are reports, not data files. The
   first three rows are a letterhead - "Bureau of Indian Standards", a
   blank, "The National Standards Body of India" - and the real column
   headings sit lower down. Reading row 1 as the header produced the
   column names ['', '', 'bureau_of_indian_standards', ''] and therefore
   zero records from every file, silently.

2. IT SAYS WHEN IT FOUND NOTHING, AND WHY. An empty list looks identical
   to "there was nothing to report", and the caller logged SUCCESS with 0
   records either way. Each sheet now reports which header row it used,
   what columns it saw, and whether a standard identifier was among them.

3. IT DOES NOT COPY PERSONAL DATA. The committee exports carry 80+ named
   individuals with Organization, Designation, Email and Mobile columns.
   The old code JSON-dumped whole rows into `raw_text_excerpt`, which
   would have put every one of those in the database. This is the same
   reason the engine strips the BIS download watermark before indexing: an
   email address and a phone number have no place in a standards
   catalogue.

WHAT THE CURRENT ARTIFACTS ACTUALLY CONTAIN. The legacy scraper downloads
"Committee Details" reports: committee metadata and a member roster, with
no IS numbers anywhere in them. Fixing the header row does not change that
and cannot - the data is not in the file. This parser now says so per
sheet instead of failing silently. Pointing the scraper at a per-standard
page is a separate decision, and the one that actually unblocks the
collector.
"""

from pathlib import Path
import json
import logging
import re
import sys

from openpyxl import load_workbook

from .config import ROOT

log = logging.getLogger(__name__)

# How far down to look for the real header row.
HEADER_SCAN_ROWS = 25

# Column names that identify a standard. Any one of these makes a row
# worth keeping.
ID_COLUMNS = (
    "is_number", "is_no", "is_num", "standard_id", "standard_no",
    "standard_number", "standard", "isnumber",
)

# Columns whose contents must never reach the database. A future BIS export
# that actually populates Email and Mobile should not quietly start storing
# them.
PRIVATE_COLUMN_RE = re.compile(
    r"e[\s_-]?mail|mobile|phone|contact|address", re.IGNORECASE)

# Defence in depth. Filtering on the column NAME is not enough: in a
# key/value sheet the label becomes a value, and a "Remarks" column can
# hold anything. Testing found a real leak this way - an address under a
# label the name filter did not recognise. Anything matching here is
# redacted wherever it appears.
VALUE_PII_RE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]{2,}"              # email
    r"|(?:\+?91[\s-]?)?\b[6-9]\d{9}\b",        # Indian mobile number
)


def redact(text: str) -> str:
    return VALUE_PII_RE.sub("[redacted]", text)

IS_NUMBER_RE = re.compile(
    r"\bIS\s+[0-9]{1,6}(?:\s*\([^)]*\))?(?:\s*:\s*\d{4})?", re.IGNORECASE)


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _key(name) -> str:
    """Normalise a column heading into a lookup key."""
    return re.sub(r"[^a-z0-9]+", "_", clean(name).lower()).strip("_")


# --- header row detection ------------------------------------------------

def find_header_row(rows) -> int:
    """
    Index (0-based) of the row that looks like column headings.

    The rule: near the top, prefer the row with the most short label-like
    cells, and strongly prefer one containing a recognised identifier
    column. That is enough for BIS reports, where letterhead rows carry a
    single filled cell and the real heading row carries six to eight.

    Returns -1 when no row has at least two filled cells, i.e. this is a
    key/value sheet rather than a table.
    """
    best, best_score = -1, 0
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [clean(c) for c in row]
        filled = sum(1 for c in cells if c)
        if filled < 2:
            continue
        # Headings are short labels, not sentences or bare numbers.
        labelish = sum(1 for c in cells if c and len(c) <= 40 and not c.isdigit())
        known = sum(1 for c in cells if _key(c) in ID_COLUMNS)
        score = known * 100 + labelish * 2 + filled
        if score > best_score:
            best, best_score = index, score
    return best


def _row_dict(headers, row) -> dict:
    out = {}
    for index, value in enumerate(row):
        if index >= len(headers):
            break
        name = headers[index]
        if not name or PRIVATE_COLUMN_RE.search(name):
            continue                      # unnamed, or personal - skip
        text = redact(clean(value))
        if text:
            out[name] = text
    return out


def _record_from(data: dict, source):
    sid = next((data[c] for c in ID_COLUMNS if data.get(c)), None)
    if not sid:
        return None
    return {
        "standard_id": clean(sid).upper(),
        "title": data.get("title") or data.get("subject") or clean(sid),
        "status": data.get("status") or "UNKNOWN",
        "last_amendment_date": (data.get("last_amendment_date")
                                or data.get("amendment_date")),
        "publication_date": data.get("publication_date"),
        "edition": data.get("edition") or data.get("revision"),
        "scope": data.get("scope"),
        "source_artifact": str(source),
        # Personal columns were dropped before this point.
        "raw_text_excerpt": json.dumps(data, ensure_ascii=False)[:5000],
        "extraction_warnings": [],
    }


def _is_table(rows) -> bool:
    """
    Is this a table, or a column of label/value pairs?

    Without this check the table parser claims key/value sheets: every row
    has two filled cells, so "Standard No:" is read as a column heading and
    "Title:", "Status:", "Email:" become three bogus records - one of which
    carried an email address into the database. A real table has rows wider
    than two cells.
    """
    return any(sum(1 for c in row if clean(c)) > 2 for row in rows)


def _parse_table(ws, source):
    """Records from a sheet laid out as a table."""
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    if not rows:
        return [], "empty sheet"
    if not _is_table(rows):
        return [], "not a table (label/value layout)"

    header_index = find_header_row(rows)
    if header_index < 0:
        return [], "no header row found (not a table)"

    headers = [_key(c) for c in rows[header_index]]
    id_columns = [h for h in headers if h in ID_COLUMNS]
    shown = ", ".join(h for h in headers if h) or "(none)"

    if not id_columns:
        return [], (f"header row {header_index + 1} has no standard "
                    f"identifier column; columns were: {shown}")

    records = []
    for row in rows[header_index + 1:]:
        record = _record_from(_row_dict(headers, row), source)
        if record:
            records.append(record)
    return records, f"header row {header_index + 1}; {len(records)} record(s)"


def _parse_key_value(ws, source):
    """
    Records from a sheet laid out as label/value pairs.

    BIS report headers use this shape ("Report Title:", "Generated On:"),
    and a per-standard export plausibly would too, so it is worth trying
    before giving up on a sheet.
    """
    data = {}
    for row in ws.iter_rows(values_only=True):
        cells = [clean(c) for c in row]
        filled = [c for c in cells if c]
        if len(filled) < 2:
            continue
        name = _key(filled[0].rstrip(":"))
        if name and not PRIVATE_COLUMN_RE.search(name):
            data.setdefault(name, redact(filled[1]))

    record = _record_from(data, source)
    if record:
        return [record], "key/value sheet"
    return [], "key/value sheet with no standard identifier"


def _parse_workbook(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    records = []
    for ws in workbook.worksheets:
        found, note = _parse_table(ws, path)
        if not found:
            found, kv_note = _parse_key_value(ws, path)
            if found:
                note = kv_note
        records.extend(found)
        (log.info if found else log.warning)(
            "%s [%s]: %s", Path(path).name, ws.title, note)
    return records


# --- PDF ------------------------------------------------------------------

def _pdf_text(path):
    """
    Read a PDF, preferring the engine's extractor.

    backend/pdf_extract.py already does per-page OCR, watermark stripping
    and caching. pypdf does none of that, so a scanned BIS artifact yields
    an empty string and the record is lost without a sound.

    The import only succeeds where the engine's dependencies are installed
    (pdfplumber, pymupdf, pytesseract). The collector has its own smaller
    requirements, so this falls back rather than failing - but the log says
    which path was taken, because "no text found" means very different
    things in the two cases.
    """
    engine = ROOT.parent.parent / "rag"
    if engine.is_dir() and str(engine) not in sys.path:
        sys.path.insert(0, str(engine))

    try:
        from backend.pdf_extract import extract_pdf
        result = extract_pdf(Path(path), verbose=False)
        log.info("%s: read with the engine extractor (%d page(s), %d via OCR)",
                 Path(path).name, result.total_pages, result.ocr_pages)
        return "\n\n".join(p.text for p in result.pages if p.text)
    except ImportError as exc:
        log.warning("%s: engine extractor unavailable (%s) - falling back to "
                    "pypdf, which cannot read scanned pages",
                    Path(path).name, exc)
    except Exception:
        log.exception("%s: engine extractor failed - falling back to pypdf",
                      Path(path).name)

    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def parse_text(text, source):
    text = clean(text)
    ids = IS_NUMBER_RE.findall(text)
    sid = clean(ids[0]).upper() if ids else Path(source).stem.upper()

    def grab(pattern):
        match = re.search(pattern, text, re.IGNORECASE)
        return clean(match.group(1)) if match else None

    title = grab(r"(?:Title|Subject|Name)\s*[:\-]\s*(.{5,200}?)"
                 r"(?:\s{2,}|Status|Edition|Amendment|Publication|Scope|$)")
    warnings = []
    if not ids:
        warnings.append("No IS number found")
    if not title:
        warnings.append("Title not confidently extracted")

    return {
        "standard_id": sid,
        "title": title or sid,
        "status": grab(r"Status\s*[:\-]\s*([A-Za-z ]{2,40})") or "UNKNOWN",
        "last_amendment_date": grab(
            r"(?:Last\s+)?Amendment(?:\s+Date)?\s*[:\-]\s*([0-9A-Za-z./ -]{4,30})"),
        "publication_date": grab(
            r"(?:Publication\s+Date|Published\s+on)\s*[:\-]\s*([0-9A-Za-z./ -]{4,30})"),
        "edition": grab(r"(?:Edition|Revision)\s*[:\-]\s*([A-Za-z0-9./ -]{1,40})"),
        "scope": grab(r"Scope\s*[:\-]\s*(.{10,500}?)(?:\s{2,}|Committee|Status|$)"),
        "source_artifact": str(source),
        "raw_text_excerpt": text[:5000],
        "extraction_warnings": warnings,
    }


def parse_artifact(p):
    p = Path(p)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return [parse_text(_pdf_text(p), p)]
    if suffix in {".xlsx", ".xlsm"}:
        return _parse_workbook(p)
    log.warning("%s: unsupported artifact type %r", p.name, suffix)
    return []


# --- inspector ------------------------------------------------------------

if __name__ == "__main__":
    # Run this on a downloaded artifact to see exactly what the parser makes
    # of it. Written because "why did the collector store nothing?" had no
    # visible answer:
    #     python -m bis_change_detector.artifact_parser <artifact>
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    if len(sys.argv) < 2:
        print("Usage: python -m bis_change_detector.artifact_parser <artifact>")
        raise SystemExit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"Not found: {target}")
        raise SystemExit(1)

    found = parse_artifact(target)
    print(f"\n{len(found)} record(s) from {target.name}")
    for record in found:
        print(json.dumps(record, indent=2, ensure_ascii=False)[:1200])
