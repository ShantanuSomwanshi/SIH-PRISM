"""
Command line for the GeM package.

    python -m backend.gem stats
    python -m backend.gem standard 10322
    python -m backend.gem find "recess mounted light"
    python -m backend.gem query "Recess Mounted 18W LED Downlight"
    python -m backend.gem search "fire safety" --compare
    python -m backend.gem search "fire safety" --dump page.html
    python -m backend.gem verify "Portable Fire Extinguishers (V3) ISI Marked To IS 15683"
"""

import argparse
import sys
from pathlib import Path

from backend.gem import catalog, search as search_module
from backend.gem.client import GemUnavailable, fetch_html
from backend.gem.extract import STRATEGY_ORDER, by_strategy, categories_from_html


def _row(category) -> str:
    return (f"  [{(category.group or '-')[:22]:22}] "
            f"{category.primary_standard or '(no standard)':28} "
            f"{category.version or '--':4} {category.certification or '':11} "
            f"{category.product_name[:40]}")


def cmd_stats(_args) -> int:
    if not catalog.load_categories():
        print("No catalogue found. Save the GeM export as "
              "backend/gem_categories.csv")
        return 1
    for key, value in catalog.stats().items():
        print(f"  {key:22} {value:>7,}")
    return 0


def cmd_standard(args) -> int:
    found = catalog.siblings(args.number)
    print(f"{len(found)} categories cite IS {args.number}\n")
    for category, differs in zip(found, catalog.distinguishing_words(found)):
        print(f"  {category.primary_standard:34} {category.product_name[:46]}")
        if differs:
            print(f"  {'':34} differs by: {', '.join(differs[:6])}")
    return 0


def cmd_find(args) -> int:
    needle = args.text.lower()
    hits = [c for c in catalog.load_categories() if needle in c.product_name.lower()]
    print(f"{len(hits)} matches\n")
    for category in hits[:25]:
        print(f"  {category.primary_standard or '(no standard)':30} "
              f"{category.version or '--':4} {category.product_name[:52]}")
    return 0


def cmd_query(args) -> int:
    print(f"  {args.text}\n")
    for index, candidate in enumerate(search_module.generalise(args.text), 1):
        print(f"   {index}. {candidate!r}")
    return 0


def cmd_search(args) -> int:
    if args.dump:
        try:
            html = fetch_html(args.query)
        except GemUnavailable as exc:
            print(f"FAILED: {exc}")
            return 1
        Path(args.dump).write_text(html, encoding="utf-8")
        print(f"saved {len(html):,} bytes to {args.dump}\n")

        breakdown = by_strategy(html)
        print("strategy         found")
        print("-" * 26)
        for name in STRATEGY_ORDER:
            print(f"  {name:14} {len(breakdown[name]):>5}")

        found = categories_from_html(html)
        print(f"\nusing: {found[0].found_by if found else 'none'} "
              f"({len(found)} categories)\n")
        for category in found[:12]:
            print(f"   [{category.group or '-'}] {category.name[:70]}")
        if not found:
            print("   Nothing matched. Send a chunk of the saved HTML.")
        return 0

    try:
        payload = search_module.search(args.query, use_cache=not args.no_cache)
    except GemUnavailable as exc:
        print(f"FAILED: {exc}")
        return 1

    source = "cache" if payload.get("from_cache") else "live"
    print(f"{len(payload['results'])} categories ({source}, "
          f"{payload['fetched_at']})\n")
    if payload.get("warning"):
        print(f"WARNING: {payload['warning']}\n")
    for category in payload["results"]:
        print(_row(category))

    if args.compare:
        changes = search_module.compare_with_snapshot(payload["results"])
        print(f"\n--- against the snapshot: {len(changes)} difference(s) ---")
        for change in changes:
            detail = change["change"]
            if "snapshot" in change:
                detail += f": {change['snapshot']} -> {change['live']}"
            print(f"  {change['category'][:44]:46} {detail}")
        if not changes:
            print("  nothing changed - live matches the snapshot")
    return 0


def cmd_verify(args) -> int:
    result = search_module.verify(args.category)
    for key, value in result.items():
        print(f"  {key:20} {value}")
    return 0 if result.get("verified") else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="backend.gem",
                                     description="GeM catalogue tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="summarise the local catalogue"
                   ).set_defaults(func=cmd_stats)

    p = sub.add_parser("standard", help="categories citing an IS number")
    p.add_argument("number")
    p.set_defaults(func=cmd_standard)

    p = sub.add_parser("find", help="substring search over product names")
    p.add_argument("text")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("query", help="show how a description is generalised")
    p.add_argument("text")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("search", help="live lookup on GeM")
    p.add_argument("query")
    p.add_argument("--compare", action="store_true",
                   help="diff the live results against the snapshot")
    p.add_argument("--dump", help="save the raw HTML and show every strategy")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("verify", help="confirm one category against GeM")
    p.add_argument("category")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
