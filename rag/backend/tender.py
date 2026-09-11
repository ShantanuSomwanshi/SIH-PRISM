"""
Draft tender clauses from a recommendation.

The point of this module, stated plainly: PRISM is not writing the tender.
It is giving the procurement officer a starting draft in roughly the right
shape, which they then edit, complete and take responsibility for. Every
clause is written so that an officer can see what came from a published
standard and what is theirs to fill in.

Three rules follow from that, and they are why this is TEMPLATES AND DATA
rather than a second call to the language model:

  1. A clause is either grounded in a retrieved page or it is a blank to be
     filled. There is no third category. A model asked to "write a testing
     clause" will produce something fluent about sampling plans and
     acceptance criteria that reads exactly like the grounded clauses and
     is entirely invented. In a document that becomes a contract, that is
     the worst possible failure, and it is not detectable by reading.

  2. Anything the system does not know appears as a visible placeholder in
     square brackets. An officer scanning for [ ] finds every gap. Prose
     that quietly omits the delivery period looks finished when it is not.

  3. Certification and current-edition status are never asserted, because
     the system has no source for either. They appear as explicit
     verification steps addressed to the officer.

The wording aims to be close to how BIS-referencing tenders are usually
phrased, without pretending to be any particular buyer's house style.
"""

import re
from typing import List, Optional

from pydantic import BaseModel, Field

# Roles that mean "this standard tells you how to test or inspect", used to
# decide which allied standards belong in the inspection clause rather than
# the general references clause.
TEST_ROLE_RE = re.compile(
    r"test|sampling|inspect|determination|method", re.IGNORECASE)


class TenderClause(BaseModel):
    heading: str
    text: str
    # True when every factual claim in the text came from the recommendation
    # or the catalogue. False means the clause is a shape to fill in.
    grounded: bool = False
    # Where the facts came from, for an officer who wants to check.
    basis: Optional[str] = None
    # The [BRACKETED] blanks in this clause.
    placeholders: List[str] = Field(default_factory=list)


class TenderDraft(BaseModel):
    clauses: List[TenderClause] = Field(default_factory=list)
    caveat: str = ""
    placeholders: List[str] = Field(default_factory=list)


CAVEAT = (
    "This is a DRAFT for editing, not tender-ready text. Every item in "
    "square brackets is a blank PRISM cannot fill. Clauses marked as not "
    "grounded are shapes to complete, not statements of fact. The edition "
    "and certification status of every standard cited here must be verified "
    "against the current BIS listing before this goes out."
)


def _placeholders_in(text: str) -> List[str]:
    return sorted(set(re.findall(r"\[([A-Z][A-Z /'’\-]+)\]", text)))


def _clause(heading: str, text: str, grounded: bool = False,
            basis: Optional[str] = None) -> TenderClause:
    text = re.sub(r"[ \t]+", " ", text).strip()
    return TenderClause(
        heading=heading, text=text, grounded=grounded, basis=basis,
        placeholders=_placeholders_in(text),
    )


def _title_phrase(title: str) -> str:
    """A title that reads inside a sentence rather than shouting."""
    title = (title or "").strip().rstrip(".")
    if title.isupper():
        title = title.title()
    return title


def build_draft(response, item_name: Optional[str] = None) -> TenderDraft:
    """
    Turn a finished RecommendResponse into draft clauses.

    `item_name` is what the officer called the thing they are buying; it is
    used verbatim where the clause needs to name the item, because their
    words are the ones the rest of their tender will use.
    """
    if not response.primary_standard:
        return TenderDraft(clauses=[], caveat=CAVEAT)

    # The officer's own words name the item - but only if they are short
    # enough to read as a noun phrase. A recommendation made from an
    # uploaded tender passes several thousand characters of document here,
    # and "The <entire tender> shall conform to..." is worse than a blank.
    item = " ".join((item_name or "").split())
    if not item or len(item) > 80:
        item = "[ITEM DESCRIPTION]"
    standard = response.primary_standard
    title = _title_phrase(response.title or "")

    clauses: List[TenderClause] = []

    # 1. The standard itself - the one clause that is fully grounded.
    named = f"{standard}" + (f" - {title}" if title else "")
    clauses.append(_clause(
        "Applicable standard",
        f"The {item} shall conform in all respects to {named}. "
        f"The edition applicable shall be the one current on the date of "
        f"opening of tenders. [CONFIRM CURRENT EDITION WITH BIS].",
        grounded=True,
        basis=f"Recommended by PRISM from the indexed text of {standard}.",
    ))

    # 2. Allied standards, split by what they are for. Only those the
    #    reference graph found inside the standard's own text are described
    #    as required by it; anything the model added is offered as a
    #    suggestion, in its own clause, so the distinction survives being
    #    pasted into a document.
    from_text = [a for a in response.allied_standards
                 if a.source == "reference clause"]
    from_model = [a for a in response.allied_standards
                  if a.source != "reference clause"]

    testing = [a for a in from_text if TEST_ROLE_RE.search(a.role or "")]
    other = [a for a in from_text if a not in testing]

    if other:
        listed = "; ".join(f"{a.code} ({a.role})" for a in other)
        clauses.append(_clause(
            "Referenced standards",
            f"The following standards are referenced normatively by "
            f"{standard} and shall apply to the extent specified therein: "
            f"{listed}.",
            grounded=True,
            basis=f"Extracted from the references clause of {standard}.",
        ))

    # 3. Testing and inspection.
    if testing:
        listed = "; ".join(f"{a.code} ({a.role})" for a in testing)
        clauses.append(_clause(
            "Testing and inspection",
            f"Testing shall be carried out in accordance with {listed}, as "
            f"referenced by {standard}. Sampling and the criteria for "
            f"conformity shall be as specified in the applicable standard. "
            f"[NAME OF INSPECTING AUTHORITY] shall witness the tests. Test "
            f"certificates shall be furnished for [NUMBER OF SAMPLES] "
            f"samples per lot.",
            grounded=True,
            basis=f"Test and sampling standards cited by {standard}.",
        ))
    else:
        clauses.append(_clause(
            "Testing and inspection",
            f"Testing shall be carried out in accordance with the methods "
            f"specified in {standard}. [PRISM HOLDS NO SEPARATE TEST STANDARD "
            f"FOR THIS ITEM - CHECK THE STANDARD'S OWN TEST CLAUSES]. "
            f"[NAME OF INSPECTING AUTHORITY] shall witness the tests.",
            grounded=False,
            basis="No test-method reference was found in the indexed text.",
        ))

    if from_model:
        listed = "; ".join(f"{a.code} ({a.role})" for a in from_model)
        clauses.append(_clause(
            "Further standards to consider",
            f"The following may also be relevant and should be checked "
            f"before inclusion: {listed}. [VERIFY EACH BEFORE CITING] - "
            f"these were proposed from context, not read out of the "
            f"references clause of {standard}.",
            grounded=False,
            basis="Proposed by the language model, not extracted from a page.",
        ))

    # 4. Marking and certification - deliberately a verification step, not
    #    a claim. The system has no certification data source at all.
    clauses.append(_clause(
        "Marking and certification",
        f"Each {item} shall be marked as required by {standard}. "
        f"[CERTIFICATION REQUIREMENT NOT DETERMINED BY PRISM - VERIFY "
        f"AGAINST THE CURRENT BIS PRODUCT CERTIFICATION AND QCO LISTINGS "
        f"WHETHER THIS ITEM REQUIRES AN ISI MARK, CRS REGISTRATION OR "
        f"OTHER MANDATORY CERTIFICATION].",
        grounded=False,
        basis="PRISM has no certification data source; nothing here is asserted.",
    ))

    # 5. The commercial terms PRISM has no view on at all. Included because
    #    an officer working from this draft should see the gaps in the same
    #    place as the content, not discover them later.
    clauses.append(_clause(
        "Commercial terms",
        "Quantity: [QUANTITY AND UNIT]. Delivery: [DELIVERY PERIOD AND "
        "LOCATION]. Warranty: [WARRANTY PERIOD]. Packing shall be "
        "[PACKING REQUIREMENT]. Rejected material shall be replaced within "
        "[REPLACEMENT PERIOD] at the supplier's cost.",
        grounded=False,
        basis="Buyer's terms - PRISM has no source for any of these.",
    ))

    return TenderDraft(
        clauses=clauses,
        caveat=CAVEAT,
        placeholders=sorted({p for c in clauses for p in c.placeholders}),
    )


def as_text(draft: TenderDraft) -> str:
    """The draft as plain text an officer can copy into their document."""
    lines = []
    for index, clause in enumerate(draft.clauses, 1):
        lines.append(f"{index}. {clause.heading.upper()}")
        lines.append(clause.text)
        lines.append("")
    lines.append("-" * 60)
    lines.append(draft.caveat)
    return "\n".join(lines)
