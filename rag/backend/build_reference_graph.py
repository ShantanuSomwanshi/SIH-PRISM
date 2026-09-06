"""
Build the reference graph: which standard cites which.

Reads every PDF in the corpus, pulls out the standards it cites, and
writes backend/reference_graph.json.

Run from the "rag" folder:
    python -m backend.build_reference_graph
    python -m backend.build_reference_graph --verbose
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from backend.catalog import load_catalog
from backend.config import BACKEND_DIR, DATA_DIR
from backend.pdf_extract import extract_pdf
from backend.reference_extract import extract_references

GRAPH_PATH = BACKEND_DIR / "reference_graph.json"


def _corpus_index(catalog: dict) -> dict:
    """Map (number, part) -> the catalog entry we hold for it."""
    index = {}
    for entry in catalog.values():
        number = str(entry.get("number") or "").strip()
        if number:
            index[(number, str(entry.get("part") or ""))] = entry
    return index


def build(verbose: bool = False) -> int:
    catalog = load_catalog()
    if not catalog:
        print("No standards_catalog.json. Run: python -m backend.build_catalog")
        return 1

    held = _corpus_index(catalog)
    edges = []

    for filename, entry in sorted(catalog.items()):
        path = DATA_DIR / filename
        if not path.exists():
            print(f"  {filename}: file missing, skipped")
            continue

        print(f"  {filename} ({entry.get('standard_id')})")
        result = extract_pdf(path, verbose=False)
        pages = [(page.page, page.text) for page in result.pages]

        refs = extract_references(
            pages,
            self_number=str(entry.get("number") or ""),
            self_part=entry.get("part"),
        )

        for ref in refs:
            key = (ref["number"], ref["part"] or "")
            target = held.get(key)

            edge = {
                "from": entry.get("standard_id"),
                "from_file": filename,
                "to_number": ref["number"],
                "to_part": ref["part"],
                "cited_year": ref["cited_year"],
                "cited_title": ref["cited_title"],
                "role": ref["role"],
                "page": ref["page"],
                "confidence": ref["confidence"],
                "source": ref["source"],
                "context": ref["context"],
                "in_corpus": target is not None,
                "resolved_id": target.get("standard_id") if target else None,
            }

            # A standard citing an older edition of something we hold is
            # exactly the outdated-reference problem procurement suffers
            # from, so record it rather than quietly resolving it.
            if target and ref["cited_year"]:
                held_year = str(target.get("publication_date") or "")
                if held_year and held_year != ref["cited_year"]:
                    edge["edition_note"] = (
                        f"cites the {ref['cited_year']} edition; "
                        f"the indexed copy is {held_year}"
                    )

            edges.append(edge)
            if verbose:
                mark = "*" if edge["in_corpus"] else " "
                print(f"      {mark} IS {ref['number']}"
                      f"{' (Part ' + ref['part'] + ')' if ref['part'] else ''}"
                      f"  [{ref['role']}]  {ref['confidence']}")

    graph = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents": len(catalog),
        "edges": edges,
    }
    GRAPH_PATH.write_text(
        json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    by_conf = {}
    for edge in edges:
        by_conf[edge["confidence"]] = by_conf.get(edge["confidence"], 0) + 1
    resolved = sum(1 for e in edges if e["in_corpus"])
    outdated = sum(1 for e in edges if e.get("edition_note"))

    print(f"\n{len(edges)} references from {len(catalog)} documents")
    print(f"  confidence: " + ", ".join(f"{k} {v}" for k, v in sorted(by_conf.items())))
    print(f"  {resolved} point at standards we hold; "
          f"{len(edges) - resolved} are not in the corpus")
    if outdated:
        print(f"  {outdated} cite an older edition than the one indexed")
    print(f"\nWritten to {GRAPH_PATH.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the reference graph.")
    parser.add_argument("--verbose", action="store_true",
                        help="list every reference as it is found")
    args = parser.parse_args()
    return build(verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
