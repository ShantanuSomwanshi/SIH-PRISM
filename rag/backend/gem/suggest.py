"""
Which GeM category should this be bought under?

A recommendation that ends at "cite IS 9246" leaves the officer holding
half a job. GeM is where the purchase actually happens, and its categories
are not named after standards - they are named after products, in GeM's own
vocabulary. Bridging that gap is the last step.

Two tiers, deliberately unequal in confidence:

  EXACT - the category's own name cites the standard. GeM writes standards
      into category names ("Chapati Making Machine as per IS 9246"), so
      this is not a guess: the marketplace has already made the link and we
      are only reading it back. These are ranked first and labelled as
      matched on the standard.

  KEYWORD - no category cites the standard, so we fall back to matching
      words. Rare words are worth more than common ones, which is not a
      refinement but the whole trick: "luminaire" appears in 8 of 9,761
      category names and "led" in 49, so "led" is nearly useless for
      telling categories apart while "luminaire" almost picks one out.

And one honest signal that matters more than either. Some words simply do
not exist in GeM's vocabulary: "downlight" and "recess" occur ZERO times
across all 9,761 categories. When an officer's words are absent, keyword
matching cannot bridge the gap and no amount of ranking will fix it - so
the result says so plainly rather than returning a confident-looking list
of near-misses. That absence is itself the finding: it is the argument for
semantic matching over the keyword search GeM gives you today.
"""

import math
import re
from typing import Dict, List, Optional

from backend.gem.catalog import by_standard_number, load_categories, vocabulary
from backend.gem.models import Category

# Below this, a keyword match is noise rather than a suggestion.
# Score is coverage x (1 + concentration), so it sits in roughly 0..2
# regardless of query length. Below this a match is noise.
MIN_KEYWORD_SCORE = 0.10

# Two characters, because "DC", "AC", "EV", "HT" and "LT" are often the
# entire specification. Dropping them ranked "AC EV Charging Station" above
# "DC EV Charging Station" for a query that said "dc fast charging".
WORD_RE = re.compile(r"[a-z0-9]{2,}")

# Words that appear in queries but say nothing about which category.
QUERY_NOISE = {
    "of", "in", "to", "by", "at", "as", "is", "be", "on", "or", "an", "it",
    "we", "us", "no", "do", "if", "so", "up", "my",
    "the", "and", "for", "with", "from", "that", "this", "shall", "any",
    "per", "our", "your", "are", "was", "were", "has", "have", "had",
    "standard", "standards", "specification", "specifications", "tender",
    "procurement", "purchase", "supply", "quality", "requirement",
    "requirements", "product", "item", "material", "type", "used", "use",
    "make", "made", "grade", "part", "section", "indian",
}


def _terms(text: str) -> List[str]:
    return [w for w in WORD_RE.findall((text or "").lower())
            if w not in QUERY_NOISE]


def _standard_number(standard_id: str) -> Optional[str]:
    match = re.search(r"\b(?:IS|SP)\s*(\d{1,5})", standard_id or "", re.IGNORECASE)
    return match.group(1) if match else None


def _as_result(category: Category, match: str, why: str, score: float) -> dict:
    return {
        "name": category.name,
        "product_name": category.product_name,
        "url": category.url,
        "primary_standard": category.primary_standard,
        "version": category.version,
        "certification": category.certification,
        "match": match,          # "standard" or "keywords"
        "why": why,
        "score": round(score, 2),
    }


def _keyword_matches(terms: List[str], limit: int) -> List[dict]:
    """
    Score every category by the rarity of the query words it contains.

    The weight is IDF - log(total categories / categories using this word).
    The obvious alternative, "one minus the fraction of categories using
    it", looks like a rarity weight and is not one: across 9,761 categories
    a word used once scores 1.00 and a word used two hundred times scores
    0.96, so the weighting is effectively flat and the result is decided by
    how MANY words matched. That ranked "Hand Rivet Tool" (two ordinary
    words) above the single category containing "bevel" - a word GeM uses
    exactly once, and the one word in the query that actually identifies
    the item. IDF gives that word roughly 9 and "hand" roughly 3.

    The score is then expressed as the FRACTION of the query's total
    information that this category accounts for, so it means the same thing
    across queries of different lengths and a threshold can be set on it.
    """
    counts = vocabulary()
    total = max(len(load_categories()), 1)
    if not terms:
        return []

    # A term GeM has never used scores 0 - it cannot help, however rare.
    weights: Dict[str, float] = {}
    for term in set(terms):
        seen = counts.get(term, 0)
        weights[term] = math.log(total / seen) if seen else 0.0

    available = sum(w for w in weights.values() if w > 0)
    if available <= 0:
        return []

    scored = []
    for category in load_categories():
        words = set(WORD_RE.findall(category.product_name.lower()))
        hits = [t for t in weights if t in words and weights[t] > 0]
        if not hits:
            continue
        # How much of what the query was asking for did this account for...
        coverage = sum(weights[t] for t in hits) / available
        # ...and how much of the category name is the match, so a short
        # exact name beats a long one that merely contains the words.
        concentration = len(hits) / max(len(words), 1)
        score = coverage * (1.0 + concentration)
        if score >= MIN_KEYWORD_SCORE:
            scored.append((score, hits, category))

    scored.sort(key=lambda row: row[0], reverse=True)
    return [
        _as_result(category, "keywords",
                   "matched on " + ", ".join(sorted(hits)[:4]), score)
        for score, hits, category in scored[:limit]
    ]


def suggest(standard_id: str, query: str = "", title: str = "",
            limit: int = 5) -> dict:
    """
    GeM categories to buy this under.

    Returns the suggestions plus an honest account of how they were found
    and what could not be matched.
    """
    # "No category matched" and "no catalogue is loaded" look identical
    # downstream and mean opposite things. Without this guard a missing CSV
    # produces the confident claim that the officer's words appear nowhere
    # in GeM - a finding invented out of absent data.
    if not load_categories():
        return {
            "standard_id": standard_id,
            "suggestions": [],
            "matched_on_standard": False,
            "unknown_terms": [],
            "note": ("The GeM category catalogue is not loaded, so no "
                     "marketplace suggestion can be made. Check "
                     "GEM_CATALOG_CSV in the configuration."),
            "caveat": "",
            "available": False,
        }

    number = _standard_number(standard_id)
    exact = list(by_standard_number().get(number, [])) if number else []

    results = [
        _as_result(c, "standard",
                   f"this GeM category cites IS {number} in its own name", 100.0)
        for c in exact[:limit]
    ]

    # Only fall back to words when the marketplace itself has not made the
    # link, and never let keyword guesses crowd out an exact citation.
    query_terms = _terms(query) + _terms(title)
    remaining = limit - len(results)
    keyword_results = []
    if remaining > 0:
        already = {r["name"] for r in results}
        keyword_results = [r for r in _keyword_matches(query_terms, limit * 3)
                           if r["name"] not in already][:remaining]
        results.extend(keyword_results)

    counts = vocabulary()
    unknown = sorted({t for t in _terms(query) if counts.get(t, 0) == 0})

    # A weak best match is worth saying out loud. Three plausible-looking
    # category names with nothing behind them is worse than an admission
    # that nothing fits, because the officer cannot tell them apart.
    best_keyword = max((r["score"] for r in keyword_results), default=0.0)
    weak = bool(keyword_results) and not exact and best_keyword < 0.45

    note = None
    if not results:
        note = ("No GeM category matches this standard or these words. "
                "The item may be bought as a custom bid rather than from "
                "the catalogue.")
    elif unknown and not exact:
        note = (
            "These are word matches, not a marketplace link - no GeM "
            "category cites this standard. Note that "
            + ", ".join(f'"{w}"' for w in unknown[:5])
            + (" do not" if len(unknown) > 1 else " does not")
            + " appear anywhere in GeM's 9,761 category names, so keyword "
              "search on GeM itself would not find these either."
        )
    elif weak:
        note = ("No GeM category is a close match. These share only common "
                "words with the description - treat them as places to start "
                "looking, not as the category to bid under.")
    elif unknown:
        note = (
            ", ".join(f'"{w}"' for w in unknown[:5])
            + (" do not" if len(unknown) > 1 else " does not")
            + " appear in any GeM category name - searching GeM directly "
              "with those words would return nothing."
        )

    return {
        "standard_id": standard_id,
        "suggestions": results,
        "matched_on_standard": bool(exact),
        "unknown_terms": unknown,
        "note": note,
        "weak": weak,
        "available": True,
        "caveat": ("GeM categories are suggestions for where to look. "
                   "Confirm the category's own specification version and "
                   "certification requirement on GeM before bidding."),
    }
