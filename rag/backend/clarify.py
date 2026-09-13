"""
Cross-questioning: work out what to ask, from what the candidates disagree
about.

The old behaviour asked one generic question - "which of these three is
closest?" - and listed the top standards. That is better than guessing, but
it puts the whole burden on the officer: it assumes they can already tell
IS 15449 (Part 2) from (Part 3) by reading two truncated titles.

The useful question is not "which standard" but "which DIMENSION of your
requirement have you not told me". So the questions here are derived from
the retrieved candidates, in this order:

  1. PART - several candidates are parts of the SAME standard. They differ
     by aspect, and the aspect is written in their titles. IS 15449 splits
     into General / Accuracy / Sewing / Durability requirements: four
     documents, one product, and no amount of describing the sewing machine
     will separate them. Only saying which aspect you are specifying will.

  2. ROLE - candidates differ by what KIND of document they are. Buying a
     product, testing it, and maintaining it are three different standards
     for the same object. "Paint" matches a specification, a test method
     and a code of practice equally well.

  3. PRODUCT - candidates are genuinely different products. This is the old
     behaviour and remains the fallback.

The rule that keeps this from becoming an interrogation: never ask a
question whose answer cannot change the outcome. Every question here is
built from a real disagreement between candidates, and a dimension on which
they all agree is never raised.

Answers narrow the candidate set directly rather than only being appended
to the query text. Appending "accuracy requirements" and hoping the
embedding notices is weaker than simply keeping the candidates that answer
describes - and the officer has just told us the answer, so there is no
reason to re-infer it.
"""

import re
from typing import Dict, List, Optional

# Two rounds. A third question buys very little and starts to feel like a
# form; if two answers have not separated the candidates, the corpus
# probably does not hold the right standard.
MAX_ROUNDS = 2

# Words too common in BIS titles to distinguish anything.
TITLE_NOISE = {
    "the", "and", "for", "of", "in", "on", "to", "with", "part", "section",
    "specification", "specifications", "indian", "standard", "standards",
    "requirements", "requirement", "method", "methods", "general",
    "determination", "code", "practice", "guidelines", "revision",
}

# What kind of document is this? Ordered - the first match wins, because a
# title like "Methods of sampling and test" is both, and the test aspect is
# the more useful discriminator.
ROLES = [
    ("test method",
     r"method[s]?\s+(?:of|for)\s+test|test\s+method|method\s+for\s+determination|"
     r"determination\s+of|methods?\s+of\s+(?:chemical|physical)",
     "how the product must be TESTED"),
    ("sampling",
     r"\bsampling\b",
     "how the product must be SAMPLED for inspection"),
    ("terminology",
     r"\bglossary\b|\bterminology\b|\bdefinitions\b|\bnomenclature\b",
     "what the TERMS mean"),
    ("code of practice",
     r"code\s+of\s+practice|\bguidelines?\b|recommendations?\s+for|"
     r"care\s+and\s+maintenance|installation|handling|storage",
     "how the product must be USED, installed or maintained"),
    ("product specification",
     r"specification|\bspec\b",
     "what the product must BE - dimensions, material, performance"),
]

_ID_RE = re.compile(
    r"(?P<type>IS|SP)\s*(?P<number>\d{1,5})"
    r"(?:\s*\(\s*Part\s*(?P<part>[0-9A-Za-z]+)"
    r"(?:\s*/\s*Section\s*(?P<section>[0-9A-Za-z]+))?"
    r"(?:\s*to\s*[0-9A-Za-z]+)?\s*\))?",
    re.IGNORECASE,
)


def parse_id(standard_id: str) -> dict:
    """Break 'IS 15449 (Part 2) : 2024' into its pieces."""
    match = _ID_RE.search(standard_id or "")
    if not match:
        return {"type": None, "number": None, "part": None, "section": None}
    return {
        "type": (match.group("type") or "").upper(),
        "number": match.group("number"),
        "part": match.group("part"),
        "section": match.group("section"),
    }


def role_of(title: str) -> tuple:
    """(role name, plain-English description) for a standard's title."""
    text = (title or "").lower()
    for name, pattern, description in ROLES:
        if re.search(pattern, text):
            return name, description
    return "product specification", ROLES[-1][2]


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in TITLE_NOISE}


def distinguishing_words(titles: List[str]) -> List[List[str]]:
    """
    What each title says that the others do not.

    Words shared by more than half the titles describe the family, not the
    difference: in the four parts of IS 15449, "sewing", "machine",
    "household" and "zig-zag" appear in all four and carry no information.
    What is left is "accuracy", "durability", "stitch".
    """
    sets = [_words(t) for t in titles]
    if not sets:
        return []
    counts: Dict[str, int] = {}
    for group in sets:
        for word in group:
            counts[word] = counts.get(word, 0) + 1
    common = {w for w, n in counts.items() if n > len(sets) / 2}
    return [sorted(s - common) for s in sets]


def _phrase(words: List[str], title: str, limit: int = 4) -> str:
    """
    A short human label for what makes this candidate different.

    The title tail comes first, because BIS has already written the aspect
    there: "... Machine/Head Part 2 Accuracy Requirements". Deriving the
    words instead produced a mixed list - "Part 2 - accuracy" beside
    "Part 1 - General Requirements" - because "general" and "requirements"
    are too common across titles to survive the distinguishing filter, so
    Part 1 fell through to the tail while Part 2 did not. Reading the tail
    for every option keeps them phrased alike.
    """
    tail = re.split(r"\bpart\s+[0-9A-Za-z]+\b", title or "", flags=re.IGNORECASE)
    aspect = re.sub(r"\s+", " ", (tail[-1] if len(tail) > 1 else "")).strip(" -ΓÇôΓÇö:,/")
    if 0 < len(aspect) <= 60:
        return aspect
    if words:
        return " / ".join(w.capitalize() for w in words[:limit])
    return (title or "").strip(" -ΓÇôΓÇö:,") or "this one"


# --- question building --------------------------------------------------

def _option(label: str, detail: str, standard_ids: List[str]) -> dict:
    return {"label": label, "detail": detail, "select": sorted(set(standard_ids))}


def _part_question(groups: List[dict]) -> Optional[dict]:
    """
    Several candidates are parts of the same standard.

    This is the strongest question available, because the officer's own
    words genuinely cannot resolve it - the parts describe one product.
    """
    families: Dict[str, List[dict]] = {}
    for group in groups:
        info = parse_id(group.get("standard_id", ""))
        if not info["number"] or info["part"] is None:
            continue
        families.setdefault(info["number"], []).append(group)

    family = max(
        (members for members in families.values() if len(members) > 1),
        key=len, default=None,
    )
    if not family:
        return None

    titles = [g.get("title") or "" for g in family]
    marks = distinguishing_words(titles)
    options = []
    for group, words in zip(family, marks):
        info = parse_id(group["standard_id"])
        label = f"Part {info['part']}"
        if info["section"]:
            label += f" / Section {info['section']}"
        options.append(_option(
            label=f"{label} - {_phrase(words, group.get('title') or '')}",
            detail=group.get("title") or "",
            standard_ids=[group["standard_id"]],
        ))

    if len(options) < 2:
        return None

    number = parse_id(family[0]["standard_id"])["number"]
    return {
        "id": "part",
        "question": (
            f"IS {number} is split into parts that cover different aspects of "
            "the same product. Which aspect are you specifying?"
        ),
        "why": ("The parts describe one product, so no description of the "
                "product itself can separate them."),
        "options": options,
        "allow_multiple": True,
    }


def _role_question(groups: List[dict]) -> Optional[dict]:
    """Candidates differ by what kind of document they are."""
    by_role: Dict[str, List[dict]] = {}
    descriptions: Dict[str, str] = {}
    for group in groups:
        role, description = role_of(group.get("title"))
        by_role.setdefault(role, []).append(group)
        descriptions[role] = description

    if len(by_role) < 2:
        return None

    options = [
        _option(
            label=role,
            detail=descriptions[role],
            standard_ids=[g["standard_id"] for g in members],
        )
        for role, members in sorted(by_role.items(), key=lambda kv: -len(kv[1]))
    ]
    return {
        "id": "role",
        "question": "What do you need the standard FOR?",
        "why": ("Buying a product, testing it and maintaining it are covered "
                "by different standards for the same object."),
        "options": options,
        "allow_multiple": True,
    }


def _product_question(groups: List[dict], label_for) -> Optional[dict]:
    """The fallback: candidates are genuinely different products."""
    if len(groups) < 2:
        return None
    return {
        "id": "product",
        "question": "Which of these is closest to what you are procuring?",
        "why": "These candidates describe different products.",
        "options": [
            _option(label=label_for(g), detail=g.get("title") or "",
                    standard_ids=[g["standard_id"]])
            for g in groups[:4]
        ],
        "allow_multiple": False,
    }


def next_question(groups: List[dict], already_asked: List[str],
                  label_for) -> Optional[dict]:
    """
    The most informative question still worth asking, or None.

    Order matters: a Part split is a harder ambiguity than a role split,
    and both are more specific than "which product did you mean".
    """
    asked = set(already_asked or [])
    for dimension, builder in (("part", _part_question), ("role", _role_question)):
        if dimension in asked:
            continue
        question = builder(groups)
        if question:
            return question
    if "product" not in asked:
        return _product_question(groups, label_for)
    return None


# --- applying the answers ------------------------------------------------

def apply_answers(groups: List[dict], answers: List[dict]) -> List[dict]:
    """
    Narrow the candidates to those the officer's answers point at.

    `answers` are the option objects handed out by next_question and echoed
    back by the client. Only their `select` lists are trusted, and only as
    an INTERSECTION with what retrieval just returned - so a client can
    narrow the candidate set but never introduce a standard that was not
    retrieved on this request's own evidence.

    If an answer would eliminate everything, it is ignored rather than
    obeyed: an officer answering "test method" when the corpus holds no
    test method should get the best available answer plus an honest note,
    not an empty screen.
    """
    if not answers:
        return groups

    for answer in answers:
        keep = {str(s) for s in (answer or {}).get("select") or []}
        if not keep:
            continue
        narrowed = [g for g in groups if g.get("standard_id") in keep]
        if narrowed:
            groups = narrowed
    return groups


def answers_as_text(answers: List[dict]) -> str:
    """
    The answers as a phrase to append to the query.

    Narrowing handles WHICH standards survive; this helps the language
    model explain the choice in the officer's own terms, and helps
    retrieval when an answer names a word the original query lacked.
    """
    parts = []
    for answer in answers or []:
        label = str((answer or {}).get("label") or "").strip()
        if label:
            parts.append(re.sub(r"^Part\s+[0-9A-Za-z/ ]*-\s*", "", label))
    return "; ".join(p for p in parts if p)
