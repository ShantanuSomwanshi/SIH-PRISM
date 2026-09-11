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
# "(Part 5/Section 2)" must be matched as a whole. Without a Section group
# the bracket never closes, the optional Part group fails, and the YEAR is
# lost with it: "IS 10322 (Part 5/Section 2) : 2012" parsed as bare
# "IS 10322", and Part 5/Section 1 and Section 2 became one standard.
COVER_ID_RE = re.compile(
    IS_TOKEN + r"\s*:?\s*(\d{1,5})"
    r"(?:\s*\(\s*Part\s*([0-9IVXivx]+)"
    r"(?:\s*[/,]?\s*Sec(?:tion)?\s*([0-9IVXivx]+))?"
    r"\s*\))?"
    r"\s*[:\-\u2013]?\s*((?:19|20)\d{2})?",
    re.IGNORECASE,
)

SP_COVER_RE = re.compile(r"(?<![A-Za-z])SP\s*:?\s*(\d{1,3})\b", re.IGNORECASE)

# On a bilingual cover the "IS" sits in a line of Devanagari, and OCR
# regularly returns it as "15" - "भारतीय मानक IS 10262 : 2019" comes back
# as "भारतीय सानक 15 10262 : 2019".
#
# "15" cannot go in IS_TOKEN above, because it is also an ordinary number:
# the pattern would happily read "15 2019" somewhere on a cover as standard
# number 2019, contradict the filename, and cost the entry 50 points. Wrong
# is worse than missing.
#
# So this token is CONFIRM-ONLY. It is used solely to ask "does the cover
# show the number the filename already gave us?", and it runs only after
# the strict pattern has found nothing. It can never introduce a number of
# its own, and it can never hide a genuine disagreement.
IS_TOKEN_OCR = r"(?<![A-Za-z0-9])(?:IS|1S|I5|l5|lS|iS|15|I8)"

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
# Older BIS PDFs carry Devanagari in a legacy font mapped onto Latin
# codepoints, so "भारतीय मानक" extracts as "Hkkjrh; ekud" and the Hindi
# title as "oaQØhV feJ vuqikru". Those are Latin characters, so a script
# check passes them; the giveaway is the punctuation and symbols that
# real English titles do not contain.
# Typographic quotes, the degree sign and the prime marks belong here.
# Real BIS titles contain them - "CARPENTER'S BEVELS - SPECIFICATION" uses
# a curly apostrophe (U+2019). Leaving it out cost that entry its title:
# one odd character in 34 is 2.9%, over the 2% threshold below, so the
# correct title was discarded and the scanner walked on to collect
# "August 1992 Price Group 2" from the foot of the cover instead.
TITLE_SAFE_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "0123456789 .,()/&:;'-\u2013\u2014\u2015"
    "\u2018\u2019\u201c\u201d\u00b0\u2032\u2033"
)
VOWELS = set("aeiouAEIOU")

# Glyphs a legacy Devanagari font uses that never appear in an English
# standard's title, so a single one is proof enough. Note what is absent:
# brackets, pipes and carets were tried here and are ordinary English
# punctuation, and the degree sign is real ("25 °C"). Ø is a diameter mark
# on engineering DRAWINGS, but a title is not a drawing.
LEGACY_TITLE_GLYPHS = set("¼½¾ØðþýÞ¡¿ªº§¶†‡")

# Headings and cover furniture that are not the standard's title.
TITLE_BOILERPLATE = {
    "indianstandard", "indianstandards", "bureauofindianstandards",
    "hindi", "draft", "foreword", "contents", "scope",
}

# A licence circular is not a standard. These files exist in real
# corpora - "AIF" in a filename means All India First licence - and
# ingesting one lets the system recommend a licence notice as a standard.
NOT_A_STANDARD_RE = re.compile(
    r"CENTRAL\s+MARKS\s+DEPARTMENT|Grant\s+of\s+All\s+India\s+First|"
    r"All\s+India\s+First\s+Licence|Licence\s+No\.?\s*:",
    re.IGNORECASE,
)


def _garbled(text: str) -> bool:
    """
    Does this look like legacy-font Devanagari rather than English?

    This is now only a backstop. Legacy-font pages are detected by their
    FONT during extraction and sent to OCR before this ever sees them; it
    still matters when the Hindi language pack is absent, or when a font
    family is not in pdf_extract's list.

    Two guards against over-firing, both learned the hard way: a single
    odd character is never enough on its own (a curly apostrophe in a
    35-character title is 2.9%), and a title made of vowelless words is
    caught even when it contains no odd characters at all ("Hkkjrh; ekud").
    """
    if not text:
        return True

    if any(c in LEGACY_TITLE_GLYPHS for c in text):
        return True

    unusual = sum(1 for c in text if c not in TITLE_SAFE_CHARS)
    if unusual >= 2 and unusual / len(text) > 0.02:
        return True

    words = [w for w in re.split(r"\s+", text) if any(c.isalpha() for c in w)]
    if len(words) >= 2:
        vowelless = sum(
            1 for w in words
            if len([c for c in w if c.isalpha()]) >= 4
            and not any(c in VOWELS for c in w)
        )
        if vowelless / len(words) > 0.4:
            return True
    return False


def _is_boilerplate(text: str) -> bool:
    squashed = re.sub(r"[^a-z]", "", (text or "").lower())
    return squashed in TITLE_BOILERPLATE


TITLE_START_RE = re.compile(r"^\s*Indian\s+Standards?\b", re.IGNORECASE)


# --- Filename parsing ------------------------------------------------

# Filenames seen in real corpora, all of which must parse:
#   10202_2025.pdf                     IS 10202 : 2025
#   3451_1_2024.pdf                    IS 3451 (Part 1) : 2024
#   13345_1992_reff2020.pdf            IS 13345 : 1992, reaffirmed 2020
#   IS 10306_2025.pdf                  prefix with a space
#   IS 15449 (Part 1)_2024.pdf         part in brackets
#   IS 15500 (Part 1 to 8)_2021.pdf    a part RANGE
#   IS 17017 (Part 23)_2026.pdf        two-digit part
#   IS-18930-AIF.pdf                   hyphenated, with a suffix
#   ... any of the above with " (1)" appended by a second download
#
# Splitting on separators and keeping numeric pieces - the previous
# approach - reads "IS 10306_2025" as standard 2025, because "IS 10306"
# is not a bare number. Six of twenty-two files in one corpus parsed the
# YEAR as the standard number that way, and all four parts of IS 15449
# collapsed into a single identity.

DUPLICATE_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")
FILE_REAFFIRMED_RE = re.compile(r"[_\-\s]*reff?[\s_\-]*(\d{4})", re.IGNORECASE)
FILE_PART_RE = re.compile(
    r"\(\s*Part\s*(\d+)"                       # Part 5
    r"(?:\s*(?:to|through|[-–])\s*(\d+))?"      # ... to 8
    r"(?:\s*[/,]?\s*Sec(?:tion)?\s*(\d+))?"    # /Section 2
    r"\s*\)",
    re.IGNORECASE,
)
FILE_TYPE_RE = re.compile(r"^\s*(IS|SP)\b[\s\-_]*", re.IGNORECASE)


def _is_year(value: str) -> bool:
    return len(value) == 4 and 1900 <= int(value) <= 2100


def parse_filename(name: str) -> dict:
    """
    Pull what we can out of the filename.

    The filename is trusted over the cover page for the NUMBER, because
    OCR mangles digits: one cover's text layer reads "IS 10 ( Part 1 ):
    1910" for a standard published in 1990.
    """
    stem = Path(name).stem
    out = {"doc_type": "IS", "number": None, "part": None, "part_to": None,
           "section": None, "year": None, "reaffirmed": None,
           "duplicate_marker": False}

    # " (1)" appended when the same file is downloaded twice.
    if DUPLICATE_SUFFIX_RE.search(stem):
        out["duplicate_marker"] = True
        stem = DUPLICATE_SUFFIX_RE.sub("", stem)

    reaffirmed = FILE_REAFFIRMED_RE.search(stem)
    if reaffirmed:
        out["reaffirmed"] = reaffirmed.group(1)
        stem = stem[:reaffirmed.start()] + stem[reaffirmed.end():]

    part = FILE_PART_RE.search(stem)
    if part:
        out["part"] = part.group(1)
        out["part_to"] = part.group(2)
        out["section"] = part.group(3)
        stem = stem[:part.start()] + " " + stem[part.end():]

    doc_type = FILE_TYPE_RE.match(stem)
    if doc_type:
        out["doc_type"] = doc_type.group(1).upper()
        stem = stem[doc_type.end():]
    elif re.match(r"^\s*sp[\s\-_]*\d", stem, re.IGNORECASE):
        out["doc_type"] = "SP"
        stem = re.sub(r"^\s*sp[\s\-_]*", "", stem, flags=re.IGNORECASE)

    numbers = re.findall(r"\d+", stem)
    if not numbers:
        return out

    # The year is the LAST year-shaped number; the standard number is the
    # first number that is not it. A single number is always the standard.
    year_index = None
    for index in range(len(numbers) - 1, -1, -1):
        if _is_year(numbers[index]) and index > 0:
            year_index = index
            break
    if year_index is not None:
        out["year"] = numbers[year_index]

    remaining = [n for i, n in enumerate(numbers) if i != year_index]
    if remaining:
        out["number"] = remaining[0]
        # A bare middle number is a part: "3451_1_2024" -> Part 1.
        if out["part"] is None and len(remaining) > 1 and len(remaining[1]) <= 2:
            out["part"] = remaining[1]

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


def _cover_confirms_number(head: str, number) -> bool:
    """
    Does the cover show the number the filename already gave us?

    Deliberately narrow: the digits must equal the filename's number
    exactly. That is what makes the loose "15" spelling of IS safe here -
    the worst it can do is agree with a number we had already chosen.
    """
    if not number:
        return False
    pattern = IS_TOKEN_OCR + r"\s*:?\s*" + re.escape(str(number)) + r"(?!\d)"
    return re.search(pattern, head, re.IGNORECASE) is not None


def parse_cover(text: str, name_info: dict) -> dict:
    """Pull the number, title, edition and reaffirmation year off the cover."""
    out = {"number": None, "part": None, "section": None, "year": None,
           "title": None, "edition": None, "reaffirmed": None,
           "doc_type": None, "number_confirmed_loosely": False}

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
            out["section"] = match.group(3)
            out["year"] = match.group(4)
        elif _cover_confirms_number(head, name_info.get("number")):
            # The strict pattern found nothing, but the cover does show
            # this exact number after a mangled "IS". Count it as the
            # second source it is.
            out["doc_type"] = "IS"
            out["number"] = name_info["number"]
            out["number_confirmed_loosely"] = True

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

        # Keep scanning past a bad candidate rather than accepting it.
        # The real English title usually sits a few lines below the
        # legacy-font Hindi one.
        if not collected and (_garbled(line) or _is_boilerplate(line)):
            continue

        collected.append(line)
        if len(collected) >= 6:
            break

    title = " ".join(collected)
    title = re.sub(r"\s+", " ", title).strip(" -\u2013\u2014,")
    return title or None


# --- Combining --------------------------------------------------------

def score_entry(entry: dict, from_name: dict, from_cover: dict,
                ocr_used: bool, cover_text: str = "") -> tuple:
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
            if from_cover.get("number_confirmed_loosely"):
                reasons.append("number agreed by filename and cover (cover's "
                               "'IS' was OCR'd from a bilingual line)")
            else:
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
        if _garbled(title):
            score -= 45
            reasons.append("title is not readable English - probably a "
                           "legacy-font Hindi line")
        if _is_boilerplate(title):
            score -= 45
            reasons.append("title is cover boilerplate, not the standard's name")

    if ocr_used:
        score -= 15
        reasons.append("cover was read by OCR - spelling may be imperfect")

    if entry.get("part_to"):
        score -= 10
        reasons.append(
            f"covers Parts {entry.get('part')} to {entry['part_to']} in one "
            "file - a citation cannot say which part a passage came from"
        )

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
    part_to = from_name.get("part_to")
    section = from_name.get("section") or from_cover.get("section")
    year = from_name["year"] or from_cover["year"]
    reaffirmed = from_name["reaffirmed"] or from_cover["reaffirmed"]

    # Assemble the human-readable standard id
    standard_id = f"{doc_type} {number}" if number else f"{doc_type} ?"
    if part:
        label = f"Part {part}"
        if part_to:                       # "IS 15500 (Part 1 to 8)"
            label += f" to {part_to}"
        if section:
            label += f"/Section {section}"
        standard_id += f" ({label})"
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
        "part_to": part_to,
        "section": section,
        "reaffirmed_year": reaffirmed,
    }

    level, score, reasons = score_entry(
        entry, from_name, from_cover, bool(result.ocr_pages), cover_text
    )
    if NOT_A_STANDARD_RE.search(cover_text or ""):
        score -= 70
        reasons.append("NOT A STANDARD: this reads like a BIS licence "
                       "circular. Move it out of the corpus - it belongs "
                       "with certification data.")

    if from_name.get("duplicate_marker"):
        reasons.append("filename ends in a download marker like (1) - check "
                       "whether it duplicates another file")

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
