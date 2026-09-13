"""
Read a GeM category name into a Category.

A category name packs several things into one string:

    Portable Fire Extinguishers (V3) ISI Marked To IS 15683
    LED Luminaire (Recessed Luminaire) (Ceiling Light) Conforming To
        IS 10322 (Part 5/Section 2) (V4) (Under BIS Scheme - II)

Everything below was driven by real GeM data, not guesswork:

  * "IS", "Is" and "is" all appear. Matching case-insensitively is safe
    here because a category name is a short label - inside a standard's
    prose it would catch the English word "is", which is why the PDF
    extractor keeps its own case-sensitive rule.
  * The (Vn) tag sits before the standard 491 times and after it 62, so
    its position cannot be assumed.
  * Parts and sections appear as "(Part 5/Section 2)", "(Part 3/Sec 403)"
    and "(Part 0/Sec 1)" - part zero is real and is not "no part".
  * One category can cite several standards.
"""

import re
from typing import List, Optional

from backend.gem.models import Category, Standard

STANDARD_RE = re.compile(
    r"(?<![A-Za-z0-9])(IS|SP)\s*[:.]?\s*"
    r"(\d{1,5})"
    r"(?:\s*\(?\s*Part\s*[-ΓÇô]?\s*([0-9]{1,3}|[IVXivx]{1,5}))?"
    r"(?:\s*[/,]?\s*Sec(?:tion)?\s*[-ΓÇô]?\s*([0-9]{1,4}|[IVXivx]{1,5}))?"
    r"\s*\)?"
    r"(?:\s*[:\-]\s*((?:19|20)\d{2}))?",
    re.IGNORECASE,
)

VERSION_RE = re.compile(r"\(\s*V\s*(\d+)\s*\)", re.IGNORECASE)

# The search page appends a (Q2)/(Q3) tag the CSV export does not carry.
# Recorded but not interpreted, and kept out of the product name so it
# never reaches the search index.
LISTING_TAG_RE = re.compile(r"\(\s*Q\s*(\d+)\s*\)", re.IGNORECASE)

BIS_SCHEME_RE = re.compile(r"Under\s+BIS\s+Scheme\s*[-ΓÇô]?\s*([IVX]+)", re.IGNORECASE)
ISI_RE = re.compile(r"ISI\s*[-ΓÇô]?\s*Marked", re.IGNORECASE)

LINK_PHRASES = re.compile(
    r"\b(conforming\s+to|confirming\s+to|as\s+per|ISI\s*[-ΓÇô]?\s*marked\s+to|"
    r"marked\s+to|as\s+per\s+IS|per)\b\s*",
    re.IGNORECASE,
)

# Removing the standard can strand the word that introduced it:
# "ISI Marked to Is 16018" -> "ISI Marked to" -> "to".
TRAILING_CONNECTOR = re.compile(
    r"[\s,;:\-ΓÇô]*\b(to|per|as|and|or|conforming|confirming|marked|of|for)\b\s*$",
    re.IGNORECASE,
)


def _roman_to_int(text: Optional[str]) -> Optional[str]:
    if not text or text.isdigit():
        return text
    values = {"i": 1, "v": 5, "x": 10}
    text = text.lower()
    if any(character not in values for character in text):
        return text
    total, previous = 0, 0
    for character in reversed(text):
        value = values[character]
        total = total - value if value < previous else total + value
        previous = max(previous, value)
    return str(total)


def parse_standards(name: str) -> List[Standard]:
    """Every standard cited in a category name, in order, deduplicated."""
    found, seen = [], set()
    for match in STANDARD_RE.finditer(name or ""):
        standard = Standard(
            doc_type=match.group(1).upper(),
            number=match.group(2),
            part=_roman_to_int(match.group(3)),
            section=_roman_to_int(match.group(4)),
            year=match.group(5),
        )
        if standard.key in seen:
            continue
        seen.add(standard.key)
        found.append(standard)
    return found


def parse_certification(name: str) -> Optional[str]:
    """The certification requirement stated in the name, if any."""
    scheme = BIS_SCHEME_RE.search(name or "")
    if scheme:
        return f"BIS Scheme - {scheme.group(1).upper()}"
    if ISI_RE.search(name or ""):
        return "ISI Marked"
    return None


def parse_product_name(name: str) -> str:
    """
    The name with standard, version, listing tag and certification removed.

    "Sodium Hypochlorite Solution (V3) Conforming To Is 11673"
        -> "Sodium Hypochlorite Solution"

    This is what gets embedded for search, and what sibling categories are
    compared on when working out which question to ask.
    """
    text = name or ""
    for pattern in (BIS_SCHEME_RE, STANDARD_RE, VERSION_RE, LISTING_TAG_RE,
                    ISI_RE, LINK_PHRASES):
        text = pattern.sub(" ", text)
    text = re.sub(r"\(\s*\)", " ", text)               # emptied brackets
    text = re.sub(r"\s{2,}", " ", text).strip()

    previous = None
    while previous != text:                            # "... marked to" -> "..."
        previous = text
        text = TRAILING_CONNECTOR.sub("", text).strip()

    return re.sub(r"\s{2,}", " ", text).strip(" -ΓÇô,;:")


def parse_category(name: str, url: str = None, created_at: str = None) -> Category:
    version = VERSION_RE.search(name or "")
    listing = LISTING_TAG_RE.search(name or "")
    return Category(
        name=(name or "").strip(),
        product_name=parse_product_name(name),
        standards=parse_standards(name),
        version=f"V{version.group(1)}" if version else None,
        listing_tag=f"Q{listing.group(1)}" if listing else None,
        certification=parse_certification(name),
        url=url,
        created_at=created_at,
    )
