"""
Build a draft standards catalog: filename -> real standard number and title.

Right now the system only knows a chunk came from "10_1_1990_reff2020.pdf".
It has no idea that means "IS 10 (Part 1) : 1990". This script produces
backend/standards_catalog.json, which supplies that missing link.

Two sources of information, combined:
  * The FILENAME, which encodes number / part / year / reaffirmation.
  * The COVER PAGE text, which gives the real title and edition.

The result is a DRAFT. Every entry starts with "verified": false.
You read through it, fix anything wrong, and set "verified": true.
Re-running this script never overwrites an entry you have verified.

Run from the "rag" folder:
    python -m backend.build_catalog
"""

import json
import re
import sys
from pathlib import Path

from backend.config import CATALOG_PATH, DATA_DIR
from backend.pdf_extract import extract_pdf

# --- Patterns -------------------------------------------------------

# OCR often reads the letters "IS" as "1S", "I5", "lS" and so on.
# The lookbehind stops us matching the "IS" inside "BIS" or "HIS".
IS_TOKEN = r"(?<![A-Za-z])(?:IS|1S|I5|l5|lS|iS)"

# "IS 1001 : 1991" / "IS : 38 - 1976" / "IS 10 ( Part 1 ) : 1990"
COVER_ID_RE = re.compile(
    IS_TOKEN + r"\s*:?\s*(\d{1,5})"
    r"(?:\s*\(\s*Part\s*([0-9IVXivx]+)\s*\))?"
    r"\s*[:\-\u2013]?\s*((?:19|20)\d{2})?",
    re.IGNORECASE,
)

SP_COVER_RE = re.compile(r"(?<![A-Za-z])SP\s*:?\s*(\d{1,3})\b", re.IGNORECASE)

REAFFIRMED_RE = re.compile(r"Reaffirmed\s*[!~]?\s*((?:19|20)\d{2})", re.IGNORECASE)
EDITION_RE = re.compile(
    r"\(\s*((?:First|Second|Third|Fourth|Fifth|Sixth|Seventh)\s+Revision)\s*\)",
    re.IGNORECASE,
)

# Bracketed fragments that are never part of a title:
# "(Reaffirmed 2019)", "(Reaffirmed~013)", "(Degemmed 2022)", "( First Reprint 1990 )"
BRACKET_JUNK_RE = re.compile(
    r"[\(\{\[][^\)\}\]]*(?:\d{3,}|affirm|eprint)[^\)\}\]]*[\)\}\]]?",
    re.IGNORECASE,
)

# Lines that mean "the title has ended"
TITLE_STOP_RE = re.compile(
    r"^\s*(\(|UDC|ICS|\u00a9|BUREAU|MANAK|NEW\s+DELHI|Gr\s*\d|Cr\s*\d|"
    r"Price|Copyright|Copyritht|www\.|BIS\s*\d{4}|HIS\s*\d{4}|"
    r"(?:First|Second|Third)\s+Reprint|\d{4}\s*$)",
    re.IGNORECASE,
)
# Anchored to the start of a line so it does not match the
# "BUREAU OF INDIAN STANDARDS" address block at the foot of the cover.
TITLE_START_RE = re.compile(r"^\s*Indian\s+Standards?\b", re.IGNORECASE)


# --- Filename parsing ------------------------------------------------

def parse_filename(name: str) -> dict:
    """
    Pull what we can out of the filename.

    10_1_1990_reff2020.pdf -> IS 10, Part 1, 1990, reaffirmed 2020
    1863_1979_reff2019.pdf -> IS 1863, 1979, reaffirmed 2019
    sp42_2008_reff2021.pdf -> SP 42, 2008, reaffirmed 2021
    1001.pdf               -> IS 1001
    """
    stem = Path(name).stem
    out = {"doc_type": "IS", "number": None, "part": None,
           "year": None, "reaffirmed": None}

    reaff = re.search(r"reff?(\d{4})", stem, re.IGNORECASE)
    if reaff:
        out["reaffirmed"] = reaff.group(1)
        stem = stem[: reaff.start()].rstrip("_-")

    if re.match(r"^sp", stem, re.IGNORECASE):
        out["doc_type"] = "SP"
        stem = re.sub(r"^sp[_\-]?", "", stem, flags=re.IGNORECASE)

    parts = [p for p in re.split(r"[_\-]", stem) if p.isdigit()]
    if not parts:
        return out

    out["number"] = parts[0]

    def is_year(value: str) -> bool:
        return len(value) == 4 and 1900 <= int(value) <= 2100

    if len(parts) >= 2:
        if is_year(parts[1]):
            out["year"] = parts[1]
        else:
            out["part"] = parts[1]
            if len(parts) >= 3 and is_year(parts[2]):
                out["year"] = parts[2]
    return out


# --- Cover page parsing ----------------------------------------------

def _head(text: str, lines: int = 15) -> str:
    """The top of the cover page - the only place identity info is reliable."""
    return "\n".join(text.splitlines()[:lines])


def _year_beside_number(text: str, number: str):
    """
    Find the year printed next to the standard number, e.g. "33: 1992"
    or "SP: 14 . 1976". Used when OCR mangled the "IS" prefix itself.
    """
    if not number:
        return None
    match = re.search(
        re.escape(number) + r"\s*[:\-\u2013\u00b7.]\s*((?:19|20)\d{2})", text
    )
    return match.group(1) if match else None


def parse_cover(text: str, name_info: dict) -> dict:
    """Pull the number, title, edition and reaffirmation year off the cover."""
    out = {"number": None, "part": None, "year": None,
           "title": None, "edition": None, "reaffirmed": None,
           "doc_type": None}

    # Trust the filename about which family this is, so an "SP" cover is
    # never parsed with the "IS" pattern.
    head = _head(text)

    if name_info.get("doc_type") == "SP":
        sp_match = SP_COVER_RE.search(head)
        if sp_match:
            out["doc_type"] = "SP"
            out["number"] = sp_match.group(1)
    else:
        match = COVER_ID_RE.search(head)
        if match:
            out["doc_type"] = "IS"
            out["number"] = match.group(1)
            out["part"] = match.group(2)
            out["year"] = match.group(3)

    if not out["year"]:
        out["year"] = _year_beside_number(head, name_info.get("number"))

    years = REAFFIRMED_RE.findall(text)
    if years:
        out["reaffirmed"] = max(years)

    edition = EDITION_RE.search(text)
    if edition:
        out["edition"] = edition.group(1).title()

    out["title"] = _extract_title(text)
    return out


def _clean_line(line: str) -> str:
    """Remove bracketed junk such as "(Reaffirmed 2019)" from a title line."""
    line = BRACKET_JUNK_RE.sub(" ", line)
    return re.sub(r"\s+", " ", line).strip()


def _latin_ratio(line: str) -> float:
    """How much of this line is ordinary A-Z text (vs Devanagari)?"""
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isascii()) / len(letters)


def _looks_like_id_line(line: str) -> bool:
    """A line that is mostly digits is a standard number, not a title."""
    if not line:
        return True
    digits = sum(1 for c in line if c.isdigit())
    return digits / len(line) > 0.3


def _extract_title(text: str):
    """
    Take the block of lines that follows the words 'Indian Standard'.

    Handles both old covers (ALL CAPITALS) and modern ones (Title Case),
    skips the Devanagari title, and ignores blank lines rather than
    stopping at them.
    """
    lines = [line.strip() for line in text.splitlines()]

    start = 0
    for i, line in enumerate(lines):
        if TITLE_START_RE.search(line):
            start = i + 1
            break

    collected = []
    for raw in lines[start:start + 40]:
        line = _clean_line(raw)

        if not line:
            continue                       # blank lines are not a boundary

        if TITLE_STOP_RE.match(line):
            if collected:
                break
            continue

        if _latin_ratio(line) < 0.5:       # Devanagari title block
            if collected:
                break
            continue

        if len([c for c in line if c.isalpha()]) < 2:
            continue

        if _looks_like_id_line(line):
            continue

        collected.append(line)
        if len(collected) >= 6:
            break

    title = " ".join(collected)
    title = re.sub(r"\s+", " ", title).strip(" -\u2013\u2014,")
    return title or None


# --- Combining --------------------------------------------------------

def score_entry(entry: dict, from_name: dict, from_cover: dict,
                ocr_used: bool) -> tuple:
    """
    Work out how much to trust this entry, with no human in the loop.

    The filename and the cover page are two independent sources. Where they
    agree, the entry verifies itself. Where they disagree - or a title fails
    a sanity check - confidence drops and the entry is flagged for review.

    Returns (level, score, reasons).
    """
    score = 100
    reasons = []

    # --- standard number ---
    name_num, cover_num = from_name.get("number"), from_cover.get("number")
    if name_num and cover_num:
        if name_num == cover_num:
            reasons.append("number agreed by filename and cover")
        else:
            score -= 50
            reasons.append(f"number DISAGREES: filename {name_num}, cover {cover_num}")
    elif name_num or cover_num:
        score -= 15
        reasons.append("number from only one source")
    else:
        score -= 60
        reasons.append("no standard number found at all")

    # --- year ---
    name_year, cover_year = from_name.get("year"), from_cover.get("year")
    if name_year and cover_year:
        if name_year == cover_year:
            reasons.append("year agreed by filename and cover")
        else:
            score -= 30
            reasons.append(f"year DISAGREES: filename {name_year}, cover {cover_year}")
    elif not entry.get("publication_date"):
        score -= 20
        reasons.append("no publication year found")

    # --- title sanity ---
    title = entry.get("title") or ""
    if not title:
        score -= 50
        reasons.append("no title found")
    else:
        if len(title) < 12:
            score -= 30
            reasons.append("title suspiciously short")
        if re.search(r"\bBIS\b|BUREAU|MANAK|DELHI|UDC|ICS|Price", title, re.IGNORECASE):
            score -= 40
            reasons.append("title contains cover boilerplate")
        digits = sum(1 for c in title if c.isdigit())
        if digits / len(title) > 0.2:
            score -= 20
            reasons.append("title is mostly digits")

    if ocr_used:
        score -= 15
        reasons.append("cover was read by OCR - spelling may be imperfect")

    score = max(0, min(100, score))
    level = "high" if score >= 80 else "medium" if score >= 55 else "low"
    return level, score, reasons


def build_entry(pdf_path: Path) -> dict:
    """Read one PDF's cover and merge it with what the filename says."""
    result = extract_pdf(pdf_path, verbose=True, max_pages=2)
    page_texts = [page.text for page in result.pages]
    from_name = parse_filename(pdf_path.name)

    # Identity and title come from page 1. Later pages contain body text
    # that looks deceptively like standard numbers and years.
    cover_text = page_texts[0] if page_texts else ""
    from_cover = parse_cover(cover_text, from_name)

    # Only if page 1 gave us no title at all, try page 2 as well.
    if not from_cover["title"] and len(page_texts) > 1:
        retry = parse_cover(page_texts[1], from_name)
        if retry["title"]:
            from_cover["title"] = retry["title"]
    # Filename wins for the number (OCR mangles digits); cover fills gaps.
    doc_type = from_name["doc_type"] or from_cover["doc_type"] or "IS"
    number = from_name["number"] or from_cover["number"]
    part = from_name["part"] or from_cover["part"]
    year = from_name["year"] or from_cover["year"]
    reaffirmed = from_name["reaffirmed"] or from_cover["reaffirmed"]

    # Assemble the human-readable standard id
    standard_id = f"{doc_type} {number}" if number else f"{doc_type} ?"
    if part:
        standard_id += f" (Part {part})"
    if year:
        standard_id += f" : {year}"

    entry = {
        # --- fields that match the scraper's SQLite columns ---
        "standard_id": standard_id,
        "title": from_cover["title"],
        "status": "Unknown",
        "publication_date": year,
        "edition": from_cover["edition"],
        "last_amendment_date": None,
        # --- extra fields useful for search ---
        "doc_type": doc_type,
        "number": number,
        "part": part,
        "reaffirmed_year": reaffirmed,
    }

    level, score, reasons = score_entry(
        entry, from_name, from_cover, bool(result.ocr_pages)
    )
    entry["confidence"] = level          # high / medium / low
    entry["confidence_score"] = score
    entry["needs_review"] = level != "high"
    entry["verified"] = False            # set true once a person or the
    entry["notes"] = reasons             # scraper has confirmed the entry
    return entry


def main() -> int:
    if not DATA_DIR.exists():
        print(f"Data folder not found: {DATA_DIR}")
        return 1

    pdfs = sorted(p for p in DATA_DIR.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"No PDFs found in {DATA_DIR}")
        return 1

    existing = {}
    if CATALOG_PATH.exists():
        try:
            existing = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("Existing catalog is not valid JSON - starting fresh.")

    catalog, kept, built = {}, 0, 0
    for pdf in pdfs:
        prior = existing.get(pdf.name)
        if prior and prior.get("verified"):
            catalog[pdf.name] = prior          # never touch verified entries
            kept += 1
            print(f"  {pdf.name}: keeping your verified entry")
            continue
        print(f"  {pdf.name}: reading cover...")
        catalog[pdf.name] = build_entry(pdf)
        built += 1

    CATALOG_PATH.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nWrote {CATALOG_PATH}")
    print(f"  {built} drafted, {kept} already verified\n")

    print(f"{'file':30} {'standard_id':26} title")
    print("-" * 100)
    for name, entry in catalog.items():
        flag = "OK " if entry.get("verified") else "-- "
        title = (entry.get("title") or "(none)")[:40]
        print(f"{flag}{name:27.27} {entry['standard_id']:26.26} {title}")

    by_level = {"high": [], "medium": [], "low": []}
    for name, entry in catalog.items():
        by_level.get(entry.get("confidence", "low"), []).append(name)

    print(f"\nConfidence: {len(by_level['high'])} high, "
          f"{len(by_level['medium'])} medium, {len(by_level['low'])} low")

    review = by_level["medium"] + by_level["low"]
    if review:
        print("\nEntries worth a look (everything else verified itself):")
        for name in review:
            entry = catalog[name]
            print(f"  {name}  [{entry['confidence']} {entry['confidence_score']}]")
            for note in entry.get("notes", []):
                if note.isupper() or "DISAGREE" in note or "no " in note or "suspicious" in note:
                    print(f"      - {note}")
    else:
        print("\nNothing needs review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
