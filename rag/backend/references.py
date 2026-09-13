"""
Query the reference graph.

Answers two questions:
  * Which standards does this one cite, and in what role?
  * What does the chain look like if you follow those citations onward?

The chain is only as deep as the corpus. A cited standard we do not hold
is a leaf: we know IS 1001 needs IS 7016, but not what IS 7016 needs
until that file is indexed.
"""

import json
from functools import lru_cache
from typing import List, Optional

from backend.config import BACKEND_DIR

GRAPH_PATH = BACKEND_DIR / "reference_graph.json"

CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

# The categories the problem statement asks allied standards to be grouped
# by, in the order they are most useful to a procurement officer.
ROLE_ORDER = [
    "product specification",
    "test method",
    "sampling",
    "terminology",
    "safety",
    "installation",
    "normative reference",
    "general convention",
]


@lru_cache(maxsize=1)
def load_graph() -> dict:
    if not GRAPH_PATH.exists():
        return {"edges": [], "documents": 0}
    try:
        return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"edges": [], "documents": 0}


def _label(edge: dict) -> str:
    """How to display the cited standard."""
    if edge.get("resolved_id"):
        return edge["resolved_id"]
    label = f"IS {edge['to_number']}"
    if edge.get("to_part"):
        label += f" (Part {edge['to_part']})"
    if edge.get("cited_year"):
        label += f" : {edge['cited_year']}"
    return label


def outgoing(standard_id: str, min_confidence: str = "medium") -> List[dict]:
    """Every standard cited by this one, best first."""
    if not standard_id:
        return []
    floor = CONFIDENCE_ORDER.get(min_confidence, 1)
    edges = [
        edge for edge in load_graph().get("edges", [])
        if edge.get("from") == standard_id
        and CONFIDENCE_ORDER.get(edge.get("confidence", "low"), 0) >= floor
    ]
    edges.sort(key=lambda e: (
        ROLE_ORDER.index(e["role"]) if e["role"] in ROLE_ORDER else 99,
        -CONFIDENCE_ORDER.get(e.get("confidence", "low"), 0),
    ))
    return edges


def allied_standards(standard_id: str, limit: int = 8,
                     min_confidence: str = "medium") -> List[dict]:
    """Cited standards in the shape the API returns them."""
    out = []
    for edge in outgoing(standard_id, min_confidence)[:limit]:
        role = edge["role"]
        if edge.get("cited_title"):
            role = f"{role} - {edge['cited_title']}"
        out.append({
            "code": _label(edge),
            "role": role,
            "in_corpus": bool(edge.get("in_corpus")),
            "cited_on_page": edge.get("page"),
            "edition_note": edge.get("edition_note"),
        })
    return out


def chain(standard_id: str, depth: int = 2, limit: int = 6,
          _seen: Optional[set] = None) -> dict:
    """
    Follow citations onward: IS 1001 needs IS 7016, which needs ...

    Cycles are possible - two standards can cite each other - so visited
    ids are tracked and not expanded twice.
    """
    seen = _seen if _seen is not None else set()
    seen.add(standard_id)

    node = {"standard_id": standard_id, "references": []}
    if depth <= 0:
        return node

    for edge in outgoing(standard_id)[:limit]:
        label = _label(edge)
        child = {
            "standard_id": label,
            "role": edge["role"],
            "in_corpus": bool(edge.get("in_corpus")),
            "cited_on_page": edge.get("page"),
            "edition_note": edge.get("edition_note"),
            "references": [],
        }
        # Only a standard we actually hold can be expanded further.
        target = edge.get("resolved_id")
        if target and target not in seen and depth > 1:
            child["references"] = chain(target, depth - 1, limit, seen)["references"]
        node["references"].append(child)

    return node


def graph_stats() -> dict:
    edges = load_graph().get("edges", [])
    return {
        "edges": len(edges),
        "resolved": sum(1 for e in edges if e.get("in_corpus")),
        "outdated_citations": sum(1 for e in edges if e.get("edition_note")),
    }
