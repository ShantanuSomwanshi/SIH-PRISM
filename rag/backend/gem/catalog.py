"""
The GeM category catalogue, loaded from the CSV export.

Tier 1 of the corpus: 9,761 short category names covering the whole
marketplace. Cheap to hold in memory and to embed, and it is what search
runs against. A standard's full PDF is tier 2 - fetched only once a
category has been chosen.
"""

import csv
import re
from collections import defaultdict
from functools import lru_cache
from typing import Dict, List, Tuple

from backend.config import GEM_CATALOG_CSV, GEM_QUERY_NOISE_WORDS
from backend.gem.models import Category
from backend.gem.parse import parse_category


@lru_cache(maxsize=1)
def load_categories() -> Tuple[Category, ...]:
    """Every category, parsed. Cached - the file does not change at runtime."""
    if not GEM_CATALOG_CSV.exists():
        return ()
    with open(GEM_CATALOG_CSV, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return tuple(
        parse_category(row.get("Name"), row.get("URL"), row.get("Created At"))
        for row in rows
    )


@lru_cache(maxsize=1)
def by_standard_number() -> Dict[str, List[Category]]:
    """Standard number -> the categories citing it."""
    index = defaultdict(list)
    for category in load_categories():
        for standard in category.standards:
            index[standard.number].append(category)
    return dict(index)


@lru_cache(maxsize=1)
def by_product_name() -> Dict[str, Category]:
    """Lower-cased product name -> category, for snapshot comparison."""
    return {c.product_name.lower(): c for c in load_categories()}


@lru_cache(maxsize=1)
def vocabulary() -> Dict[str, int]:
    """
    Word -> how many categories use it.

    Used to phrase a search in GeM's own words. A term from a tender that
    appears in no category name will not help a keyword search: "downlight"
    occurs zero times, while "luminaire" occurs eight.
    """
    counts: Dict[str, int] = {}
    for category in load_categories():
        for word in set(re.findall(r"[a-z0-9]{3,}", category.product_name.lower())):
            counts[word] = counts.get(word, 0) + 1
    return counts


def siblings(number: str) -> List[Category]:
    """
    Other categories citing the same base standard.

    This is what makes a useful clarifying question possible. IS 10322
    Part 5 covers Section 2 (recessed), 3 (road and street), 5 (floodlight)
    and 9 (rope light): four categories, one standard family, separated by
    an application that is written in the name.
    """
    return by_standard_number().get(str(number), [])


def distinguishing_words(categories: List[Category]) -> List[List[str]]:
    """
    What differs between sibling categories - the basis of the question.

    Words shared by all of them are dropped, so "LED Luminaire (Recessed)
    (Ceiling)" and "LED Luminaire For Road And Street" reduce to
    "ceiling recessed" and "road street".
    """
    def words(text: str) -> set:
        return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
                if len(w) > 2 and w not in GEM_QUERY_NOISE_WORDS}

    sets = [words(c.product_name) for c in categories]
    if not sets:
        return []
    shared = set.intersection(*sets) if len(sets) > 1 else set()

    # A word shared by most of them describes the family, not the
    # difference. "Luminaire" appears in three of the four IS 10322
    # categories and only muddies the question.
    if len(sets) > 2:
        counts = {}
        for group in sets:
            for word in group:
                counts[word] = counts.get(word, 0) + 1
        shared |= {w for w, n in counts.items() if n > len(sets) / 2}

    return [sorted(s - shared) for s in sets]


def stats() -> dict:
    categories = load_categories()
    with_standard = [c for c in categories if c.standards]
    return {
        "categories": len(categories),
        "with_standard": len(with_standard),
        "without_standard": len(categories) - len(with_standard),
        "with_certification": sum(1 for c in categories if c.certification),
        "with_version": sum(1 for c in categories if c.version),
        "distinct_standards": len(by_standard_number()),
    }
