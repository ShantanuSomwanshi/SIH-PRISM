"""
Measure how often PRISM finds the right standard.

Without this, changing a setting is guesswork: nobody can say whether it
helped. This runs a fixed set of queries with known answers and reports
the numbers.

    python -m backend.evaluate              # retrieval only, no LLM calls
    python -m backend.evaluate --with-llm   # also check the final answer
    python -m backend.evaluate --failures   # show only what went wrong

What the numbers mean:
  recall@1  the right standard was ranked first
  recall@3  it was in the top three
  recall@5  it was in the top five
  MRR       mean reciprocal rank - 1.0 if always first, 0.5 if always
            second, and so on. Rewards ranking it higher, not just
            including it somewhere.
"""

import argparse
import json
import sys
from pathlib import Path

from backend.config import BACKEND_DIR

EVAL_SET_PATH = BACKEND_DIR / "eval_set.json"
RESULTS_PATH = BACKEND_DIR / "eval_results.json"


def normalise(standard_id: str) -> str:
    """Compare ids without tripping over spacing differences."""
    return " ".join(str(standard_id or "").split()).lower()


def load_cases() -> list:
    if not EVAL_SET_PATH.exists():
        print(f"No eval set at {EVAL_SET_PATH}")
        sys.exit(1)
    return json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))["cases"]


def evaluate(with_llm: bool = False, failures_only: bool = False) -> int:
    cases = load_cases()

    from backend.retriever import PrismHybridRetriever
    retriever = PrismHybridRetriever(verbose=False)

    llm = None
    if with_llm:
        import os
        if not os.getenv("GROQ_API_KEY"):
            print("GROQ_API_KEY is not set - cannot run --with-llm")
            return 1
        from langchain_groq import ChatGroq
        llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.1)

    results = []
    print(f"Running {len(cases)} cases...\n")

    for index, case in enumerate(cases, start=1):
        query, expected = case["query"], case["expected"]
        groups = retriever.search_standards(query, max_standards=5)
        ranked = [normalise(g["standard_id"]) for g in groups]
        target = normalise(expected)

        rank = ranked.index(target) + 1 if target in ranked else None

        record = {
            "query": query,
            "expected": expected,
            "rank": rank,
            "returned": [g["standard_id"] for g in groups[:5]],
        }

        if llm is not None:
            from backend.recommend import recommend
            response = recommend(query, retriever, llm)
            record["llm_primary"] = response.primary_standard
            record["llm_correct"] = (
                normalise(response.primary_standard) == target
            )
            record["clarification"] = response.clarification_needed

        results.append(record)

        failed = rank is None or rank > 1
        if not failures_only or failed:
            mark = "ok  " if rank == 1 else ("~   " if rank else "MISS")
            position = f"#{rank}" if rank else "-"
            print(f"{index:>3} {mark} {position:>3}  {query[:52]:52} "
                  f"expected {expected}")
            if failed:
                print(f"           got: {', '.join(record['returned'][:3])}")

    total = len(results)
    ranks = [r["rank"] for r in results]
    found = [r for r in ranks if r]

    summary = {
        "cases": total,
        "recall@1": sum(1 for r in ranks if r == 1) / total,
        "recall@3": sum(1 for r in ranks if r and r <= 3) / total,
        "recall@5": sum(1 for r in ranks if r and r <= 5) / total,
        "mrr": sum(1 / r for r in found) / total if total else 0.0,
        "not_found": sum(1 for r in ranks if r is None),
    }
    if llm is not None:
        answered = [r for r in results if not r.get("clarification")]
        summary["llm_primary_correct"] = (
            sum(1 for r in results if r.get("llm_correct")) / total
        )
        summary["clarifications"] = total - len(answered)

    print("\n" + "=" * 58)
    print("RESULTS")
    print("=" * 58)
    print(f"  cases            {summary['cases']}")
    print(f"  recall@1         {summary['recall@1']:.1%}   right standard ranked first")
    print(f"  recall@3         {summary['recall@3']:.1%}   in the top three")
    print(f"  recall@5         {summary['recall@5']:.1%}   in the top five")
    print(f"  MRR              {summary['mrr']:.3f}")
    print(f"  never found      {summary['not_found']}")
    if llm is not None:
        print(f"  final answer     {summary['llm_primary_correct']:.1%}   "
              f"correct primary standard")
        print(f"  clarifications   {summary['clarifications']}")

    RESULTS_PATH.write_text(
        json.dumps({"summary": summary, "results": results},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWritten to {RESULTS_PATH.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure PRISM retrieval accuracy.")
    parser.add_argument("--with-llm", action="store_true",
                        help="also run the full recommendation (uses Groq credits)")
    parser.add_argument("--failures", action="store_true",
                        help="print only the cases that did not rank first")
    args = parser.parse_args()
    return evaluate(with_llm=args.with_llm, failures_only=args.failures)


if __name__ == "__main__":
    sys.exit(main())
