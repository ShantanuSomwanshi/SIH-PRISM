"""
Find the standards that a standard cites.

Every Indian Standard depends on others - test methods, terminology,
sampling procedures. Older BIS documents (1976-1992) have no References
clause at all: citations sit inline in the prose with footnote markers,
like "rounded off in accordance with IS : 2-1960*". Modern ones (2024)
carry a proper "2 REFERENCES" table of IS numbers and titles. This reads
both.

Extracting these gives allied standards that can be pointed at a specific
page, rather than read out of retrieved text by a language model.
"""

import re

# Case-SENSITIVE on the prefix. Using IGNORECASE here is what made an
# earlier parser read the word "is" in "...is 2 mm..." as a standard
# number. The lookbehind stops us matching inside BIS or HIS.
REF_RE = re.compile(
    r"(?<![A-Za-z0-9])(IS|1S|SP)\s*[:.]?\s*"
    r"(\d{1,5})"
    r"(?:\s*\(\s*Part\s*([0-9IVXivx]+)\s*\))?"
    r"(?:\s*[-:.~•‐–—]\s*|\s+)?"
    r"((?:19|20)\d{2})?"
)

REFERENCES_HEADING_RE = re.compile(
    r"^\s*\d?\s*(NORMATIVE\s+)?REFERENCES?\b", re.IGNORECASE)

ROLE_RULES = [
    (r"rounding\s+off|significant\s+places", "general convention"),
    (r"method[s]?\s+of\s+test|methods?\s+of\s+sampling|test\s+method|"
     r"determination|assay|analysis", "test method"),
    (r"sampling", "sampling"),
    (r"glossary|terminolog|definitions|terms\s+relating", "terminology"),
    (r"safety|hazard|protective\s+equipment", "safety"),
    (r"code\s+of\s+practice|installation|erection|laying", "installation"),
    (r"specification|shall\s+conform|conforming\s+to", "product specification"),
]


def infer_role(title, context):
    """Classify a reference into the categories the problem statement lists."""
    for haystack in (title or "", context or ""):
        low = haystack.lower()
        for pattern, role in ROLE_RULES:
            if re.search(pattern, low):
                return role
    return "normative reference"


# Words that begin a continuing sentence, not a title. Without this the
# body text after an inline citation gets captured as the standard's name,
# producing entries like "* are given in col 4 of Table 1."
CONTINUATION_WORDS = {
    "are", "is", "was", "shall", "should", "and", "or", "of", "the", "in",
    "for", "with", "by", "to", "as", "at", "on", "from", "that", "which",
    "this", "these", "may", "must", "can", "will", "given", "specified",
}


def _title_after(line, end_pos):
    """In modern standards the title follows the number on the same line."""
    tail = line[end_pos:].strip(" \u2015\u2014\u2013-:|")
    # Footnote markers and punctuation mean this is body text, not a title.
    if not tail or not tail[0].isalpha():
        return None
    if len(tail) < 6:
        return None
    words = [w for w in re.split(r"\s+", tail) if w]
    if len(words) < 2:
        return None
    if words[0].lower() in CONTINUATION_WORDS:
        return None
    return " ".join(words[:14])


def _has_prose(window):
    """
    Does this text look like sentences rather than a numeric table?

    OCR of a data table produces lines like "'10 0'21 ~[O O~I ~Ol 0'01410",
    where any "IS 0" match is meaningless. Real references sit in prose or
    in a reference table, both of which contain actual words.
    """
    return len(re.findall(r"[A-Za-z]{4,}", window)) >= 2


def extract_references(pages, self_number, self_part=None):
    """
    pages: list of (page_number, text)
    Returns a list of reference dicts, deduplicated by (number, part).
    """
    found = {}

    for page_no, text in pages:
        if not text:
            continue
        lines = text.splitlines()
        # Modern standards are printed in two columns, and text extraction
        # interleaves them - so a heading like "6 QUALITY OF COATING" can
        # appear in the middle of the references table. Rather than ending
        # the clause at the first heading, stay inside it for a window of
        # lines after the REFERENCES heading.
        clause_lines_left = 0

        for index, line in enumerate(lines):
            if REFERENCES_HEADING_RE.match(line):
                clause_lines_left = 40
            in_clause = clause_lines_left > 0
            if clause_lines_left:
                clause_lines_left -= 1

            previous = lines[index - 1] if index else ""
            window = (previous + " " + line).strip()

            for match in REF_RE.finditer(line):
                number = match.group(2)
                part = match.group(3)
                year = match.group(4)

                # Skip the document citing itself - it appears in the page
                # header of nearly every page of older standards.
                if number == self_number and (part or None) == (self_part or None):
                    continue
                if len(number) > 5 or number.startswith("0"):
                    continue
                if not _has_prose(window):
                    continue          # numeric table noise, not a reference

                # Only trust a title inside the references table. Elsewhere
                # the text after a citation is ordinary body prose, which
                # produced "titles" like "*. The number of significant
                # places retained".
                title = _title_after(line, match.end()) if in_clause else None
                key = (number, part or "")
                candidate = {
                    "number": number,
                    "part": part,
                    "cited_year": year,
                    "cited_title": title,
                    "page": page_no,
                    "context": window[:200],
                    "source": "references_clause" if in_clause else "inline",
                }
                existing = found.get(key)
                # Prefer a hit inside the references clause, then one that
                # came with a title.
                better = (
                    existing is None
                    or (candidate["source"] == "references_clause"
                        and existing["source"] != "references_clause")
                    or (candidate["cited_title"] and not existing["cited_title"])
                )
                if better:
                    found[key] = candidate

    out = []
    for ref in found.values():
        ref["role"] = infer_role(ref["cited_title"], ref["context"])
        # How much to trust this edge.
        if ref["source"] == "references_clause" and ref["cited_title"]:
            ref["confidence"] = "high"
        elif ref["source"] == "references_clause" or ref["cited_year"]:
            ref["confidence"] = "medium"
        else:
            ref["confidence"] = "low"
        out.append(ref)
    out.sort(key=lambda r: (int(r["number"]), r["part"] or ""))
    return out
