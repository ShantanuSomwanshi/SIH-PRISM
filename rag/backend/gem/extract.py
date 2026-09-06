"""
Pull categories out of a GeM search page.

Five strategies, ordered by how much page structure they rely on. They
exist because the markup is not ours and can change without notice, and
because a JavaScript-rendered page ships no category HTML at all.

The safety net is that a GeM category name is recognisable on sight: it
carries a version tag, or names a standard, or says ISI Marked. That
shape lets us find categories on markup we have never seen.
"""

import re
from typing import List, Tuple

from backend.gem.models import Category
from backend.gem.parse import parse_category

# (text, href, group)
RawResult = Tuple[str, str, str]

CATEGORY_SHAPE = re.compile(
    r"\(\s*V\s*\d+\s*\)"                            # (V3)
    r"|(?<![A-Za-z0-9])[IiSs]{2}\s*[:.]?\s*\d{2,5}"  # IS 1234 / Is 1234
    r"|ISI\s*[-–]?\s*Marked"
    r"|Conforming\s+To|Confirming\s+To",
    re.IGNORECASE,
)

ATTRIBUTE_KEYS = ("title", "aria-label", "data-category", "data-name",
                  "data-title", "data-product", "alt")

CONTAINER_HINT = re.compile(r"categor|product|result|item|card|tile", re.IGNORECASE)

STRATEGY_ORDER = ("links", "attributes", "containers", "embedded_json", "text_shape")


class ParserUnavailable(Exception):
    """BeautifulSoup is not installed."""


def _looks_like_category(text: str) -> bool:
    return bool(text) and 4 < len(text) < 220 and bool(CATEGORY_SHAPE.search(text))


def _soup(html: str):
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise ParserUnavailable(
            "beautifulsoup4 is not installed (pip install beautifulsoup4)"
        ) from exc
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["style", "nav", "footer", "header"]):
        tag.decompose()
    return soup


def _is_category_link(tag) -> bool:
    """A link to a category page, not the search box's own form action."""
    href = (tag.get("href") or "").strip()
    if "/search" not in href:
        return False
    if href.rstrip("/") in {"/search", "search"}:
        return False
    return 3 < len(tag.get_text(" ", strip=True)) < 220


def _card_heading(anchor):
    """
    The heading of the card this link sits in.

    GeM does not use heading tags for card titles - they are styled divs -
    so searching for <h3> returns the page <h1> instead.

    Taking the first text inside an ancestor is wrong too: when a row
    wrapper holds several cards, that gives every link the first card's
    title. The card title is the nearest text BEFORE the link, so we walk
    forward and keep the last one seen.

    Text inside a link is skipped by checking its ancestry rather than by
    comparing strings - a card titled "Safety Footwear" holding a link
    called "Safety Footwear (V3) ISI Marked..." is common, and a substring
    test throws the correct heading away.
    """
    node = anchor
    for _ in range(6):
        node = node.parent
        if node is None:
            return None
        if not any(_is_category_link(a) for a in node.find_all("a")):
            continue

        heading, reached = None, False
        for descendant in node.descendants:
            if descendant is anchor:
                reached = True
                break
            if getattr(descendant, "name", None) is not None:
                continue                       # tags carry no text of their own
            if descendant.find_parent("a") is not None:
                continue                       # this is a link's own label
            text = str(descendant).strip()
            if text and 2 < len(text) < 90:
                heading = text
        if reached and heading:
            return heading
    return None


def _from_links(soup) -> List[RawResult]:
    """Anchors pointing at a category page. The normal case."""
    return [
        (anchor.get_text(" ", strip=True), anchor.get("href"), _card_heading(anchor))
        for anchor in soup.find_all("a")
        if _is_category_link(anchor)
    ]


def _from_attributes(soup) -> List[RawResult]:
    """Names carried in title, aria-label or data-* rather than in text."""
    found = []
    for element in soup.find_all(True):
        for key in ATTRIBUTE_KEYS:
            value = element.get(key)
            if isinstance(value, str) and _looks_like_category(value.strip()):
                found.append((value.strip(), element.get("href"), None))
                break
    return found


def _from_containers(soup) -> List[RawResult]:
    """Elements whose id or class mentions category/product/result/card."""
    found = []
    for element in soup.find_all(["div", "li", "span", "button", "p", "td"]):
        marker = " ".join(filter(None, [
            element.get("id") or "",
            " ".join(element.get("class") or []),
        ]))
        if not CONTAINER_HINT.search(marker):
            continue
        if element.find(["div", "li", "ul", "table"]):
            continue                           # leaf-ish nodes only
        text = element.get_text(" ", strip=True)
        if _looks_like_category(text):
            link = element.find("a")
            found.append((text, link.get("href") if link else None, None))
    return found


def _from_embedded_json(html: str) -> List[RawResult]:
    """
    Data embedded in a <script> tag - __NEXT_DATA__ and friends.

    This is what a JavaScript-rendered page ships instead of HTML, so it
    is often the only place the categories exist.
    """
    found = []
    for block in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I):
        if "{" not in block:
            continue
        for value in re.findall(r'"([^"\\]{6,220})"', block):
            if _looks_like_category(value):
                found.append((value.strip(), None, None))
    return found


def _from_text_shape(soup) -> List[RawResult]:
    """Last resort: any visible line that looks like a category name."""
    return [
        (line.strip(), None, None)
        for line in soup.get_text("\n", strip=True).splitlines()
        if _looks_like_category(line.strip())
    ]


def by_strategy(html: str) -> dict:
    """Run every strategy and report what each found. Used for diagnosis."""
    soup = _soup(html)
    return {
        "links": _from_links(soup),
        "attributes": _from_attributes(soup),
        "containers": _from_containers(soup),
        "embedded_json": _from_embedded_json(html),
        "text_shape": _from_text_shape(soup),
    }


def categories_from_html(html: str) -> List[Category]:
    """
    Extract categories, keeping the best strategy's result.

    Links win when present because they also carry a URL and a parent
    heading. A weaker strategy finding far more is treated as a sign the
    page has changed shape, and takes over.
    """
    found = by_strategy(html)

    chosen, chosen_by = [], "none"
    for name in STRATEGY_ORDER:
        if found[name]:
            chosen, chosen_by = found[name], name
            break
    for name in STRATEGY_ORDER:
        if len(found[name]) > max(len(chosen) * 3, len(chosen) + 5):
            chosen, chosen_by = found[name], name

    results, seen = [], set()
    for text, href, group in chosen:
        key = text.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        category = parse_category(text, href)
        category.group = group
        category.found_by = chosen_by
        results.append(category)
    return results
