"""
Looking a product up on GeM.

This exists to VERIFY, not to search. GeM's own search is keyword based:
asked for "recess mounted lights" it returned two operating theatre lamps
and a strobe light bar alongside the right answer. Ranking runs against
the local catalogue; this confirms the category we chose still exists and
reports its current version and standard.
"""

import re
from typing import List, Optional

from backend.config import GEM_QUERY_NOISE_WORDS
from backend.gem import catalog
from backend.gem.client import GemUnavailable, fetch_html, now_iso, read_cache, write_cache
from backend.gem.extract import categories_from_html
from backend.gem.models import Category
from backend.gem.parse import parse_category

# Units and sizes make a query too specific for a keyword search.
# "Recess Mnt 230V 36W LED Fixture 600x600m" finds nothing; "LED fixture"
# finds the category.
UNIT_TOKEN = re.compile(
    r"\b\d+(?:\.\d+)?\s*"
    r"(?:w|watt|watts|v|volt|volts|kv|ma|amp|amps|a|hz|mm|cm|m|ft|feet|foot|"
    r"inch|in|kg|gm|g|ml|ltr|l|lm|lux|k|nos|pcs|set|sets)\b",
    re.IGNORECASE,
)
DIMENSION = re.compile(r"\b\d+\s*[x×]\s*\d+(?:\s*[x×]\s*\d+)?\s*[a-z]{0,4}\b",
                       re.IGNORECASE)
BARE_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])")


def generalise(query: str, ladder: int = 3) -> List[str]:
    """
    Turn a specific product description into search terms, broad to narrow.

    Returns several candidates; try them in order and stop at the first
    that returns results, because a very specific string often returns
    nothing at all from a keyword search.

    Words are kept when the catalogue actually uses them, and rarer words
    are preferred: "luminaire" appears in 8 categories and narrows far
    better than "led", which appears in 49.

    This is the FALLBACK. It cannot bridge a vocabulary gap - a tender
    saying "recess mounted downlight" uses two words GeM never uses at
    all. Matching semantically against the local catalogue can, and then
    query_for_category() searches GeM in its own language.
    """
    text = DIMENSION.sub(" ", query or "")
    text = UNIT_TOKEN.sub(" ", text)
    text = BARE_NUMBER.sub(" ", text)
    text = re.sub(r"[^A-Za-z0-9\s/&-]", " ", text)
    words = [w for w in text.split()
             if len(w) > 2 and w.lower() not in GEM_QUERY_NOISE_WORDS]

    candidates = [" ".join(words)] if words else []

    vocabulary = catalog.vocabulary()
    if vocabulary:
        known = [w for w in words if w.lower() in vocabulary]
        if known and known != words:
            candidates.append(" ".join(known))
        ranked = sorted(known, key=lambda w: vocabulary.get(w.lower(), 0))
        if len(ranked) > 2:
            candidates.append(" ".join(sorted(ranked[:2], key=words.index)))
    elif len(words) > 2:
        candidates.append(" ".join(words[-2:]))

    seen, out = set(), []
    for candidate in candidates:
        key = candidate.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(candidate.strip())
    return out[:ladder] or [query]


def query_for_category(category: Category) -> str:
    """
    The search term to send GeM for a category already matched locally.

    This is the accurate path. The tender and the marketplace do not share
    a vocabulary - "downlight" and "recess" appear in no GeM category at
    all, while GeM says "LED Luminaire (Recessed Luminaire) (Ceiling
    Light)". Once the local match is made, we search in GeM's words.
    """
    name = category.product_name or category.name or ""
    # Bracketed qualifiers are how GeM disambiguates; keep the first and
    # drop the rest, which make the query too narrow.
    name = re.sub(r"\)\s*\([^)]*\)+", ")", name)
    return generalise(name, ladder=1)[0]


def search(query: str, use_cache: bool = True) -> dict:
    """Look a product up on GeM. Raises GemUnavailable if it cannot."""
    if use_cache:
        cached = read_cache(query)
        if cached:
            cached["results"] = [
                parse_category(r["name"], r.get("url")) for r in cached["results"]
            ]
            return cached

    results = categories_from_html(fetch_html(query))
    payload = {
        "query": query,
        "fetched_at": now_iso(),
        "results": results,
        "from_cache": False,
    }
    if not results:
        payload["warning"] = (
            "no categories found - the page layout may have changed, or it "
            "may need JavaScript. Re-run with --dump and inspect the HTML."
        )

    write_cache(query, {**payload, "results": [c.as_dict() for c in results]})
    return payload


def compare_with_snapshot(results: List[Category]) -> List[dict]:
    """
    Check live results against the catalogue snapshot.

    This is the reason for scraping at all. GeM and BIS do not watch each
    other, and nobody watches GeM's own catalogue for drift - so a version
    bump or a changed standard is invisible unless something holds an
    older copy and compares.
    """
    snapshot = catalog.by_product_name()
    if not snapshot:
        return []

    changes = []
    for live in results:
        known = snapshot.get((live.product_name or "").lower())
        if not known:
            changes.append({"category": live.product_name,
                            "change": "new since snapshot",
                            "live": live.primary_standard})
            continue

        for field, live_value, snapshot_value in (
            ("version", live.version, known.version),
            ("standard", live.primary_standard, known.primary_standard),
            ("certification", live.certification, known.certification),
        ):
            if live_value != snapshot_value:
                changes.append({"category": live.product_name,
                                "change": f"{field} changed",
                                "snapshot": snapshot_value,
                                "live": live_value})
    return changes


def verify(category_name: str) -> dict:
    """
    Confirm one chosen category against GeM.

    Used after local ranking has picked a category, so this is a single
    request about a single answer - never a search we outsource.
    """
    parsed = parse_category(category_name)
    try:
        live = search(query_for_category(parsed))
    except GemUnavailable as exc:
        return {"verified": False, "reason": str(exc)}

    target = category_name.lower().strip()
    for result in live["results"]:
        if result.name.lower().strip() == target:
            return {
                "verified": True,
                "from_cache": live.get("from_cache", False),
                "checked_at": live["fetched_at"],
                "live_version": result.version,
                "snapshot_version": parsed.version,
                "version_changed": result.version != parsed.version,
                "live_standard": result.primary_standard,
                "standard_changed": result.primary_standard != parsed.primary_standard,
            }

    return {"verified": False,
            "reason": "category not found in the live results",
            "checked_at": live["fetched_at"]}
