"""
GeM marketplace integration.

    models    Category and Standard
    parse     a category name -> Category
    catalog   the local CSV snapshot (tier 1 of the corpus)
    extract   a search page's HTML -> categories
    client    one polite, cached HTTP request
    search    orchestration: generalise, search, verify, compare

Command line:  python -m backend.gem --help
"""

from backend.gem.catalog import (
    distinguishing_words,
    load_categories,
    siblings,
    stats,
    vocabulary,
)
from backend.gem.client import GemUnavailable
from backend.gem.extract import categories_from_html
from backend.gem.models import Category, Standard
from backend.gem.parse import parse_category
from backend.gem.search import (
    compare_with_snapshot,
    generalise,
    query_for_category,
    search,
    verify,
)

__all__ = [
    "Category", "Standard", "parse_category",
    "load_categories", "siblings", "distinguishing_words", "vocabulary", "stats",
    "categories_from_html",
    "search", "verify", "generalise", "query_for_category",
    "compare_with_snapshot", "GemUnavailable",
]
