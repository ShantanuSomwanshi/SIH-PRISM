"""Types used across the GeM package."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Standard:
    """An Indian Standard cited by a GeM category."""

    doc_type: str                      # "IS" or "SP"
    number: str
    part: Optional[str] = None         # "0" is real and distinct from None
    section: Optional[str] = None
    year: Optional[str] = None

    @property
    def label(self) -> str:
        """How the standard is written out, e.g. 'IS 10322 (Part 5/Section 2)'."""
        text = f"{self.doc_type} {self.number}"
        if self.part is not None:
            text += f" (Part {self.part}"
            text += f"/Section {self.section})" if self.section is not None else ")"
        if self.year:
            text += f" : {self.year}"
        return text

    @property
    def key(self) -> str:
        """
        Identity ignoring the edition year.

        IS 33 : 1976 and IS 33 : 1992 are the same standard in different
        editions, so they share a key. Part 5/Section 1 and Part 5/Section 2
        are different documents and do not.
        """
        return f"{self.doc_type}|{self.number}|{self.part or ''}|{self.section or ''}"


@dataclass
class Category:
    """One GeM product category."""

    name: str                          # exactly as GeM writes it
    product_name: str                  # name with standard/version/cert removed
    standards: List[Standard] = field(default_factory=list)
    version: Optional[str] = None      # "V4" - the category specification version
    listing_tag: Optional[str] = None  # "Q2" - shown on the search page only
    certification: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[str] = None
    group: Optional[str] = None        # parent card heading, live results only
    found_by: Optional[str] = None     # which parsing strategy found it

    @property
    def primary_standard(self) -> Optional[str]:
        return self.standards[0].label if self.standards else None

    @property
    def base_number(self) -> Optional[str]:
        return self.standards[0].number if self.standards else None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "product_name": self.product_name,
            "primary_standard": self.primary_standard,
            "standards": [s.label for s in self.standards],
            "version": self.version,
            "listing_tag": self.listing_tag,
            "certification": self.certification,
            "url": self.url,
            "created_at": self.created_at,
            "group": self.group,
            "found_by": self.found_by,
        }
