# data/tenders/

**Test inputs.** Tender documents, bid papers, requirement notes.

These are what PRISM is asked ABOUT. They are never ingested into the
standards index.

## Why they are kept apart

If a tender goes into the corpus, it competes with the standards. A search
for "LED luminaire" would match a tender that merely mentions LED
luminaires as strongly as the standard that defines them - and PRISM would
recommend a tender as though it were a standard, with a citation and a
confidence badge attached.

Standards are what you search. Tenders are what you search with.

## What they are for

**Testing the upload path.**

```powershell
curl -X POST http://127.0.0.1:8000/api/recommend/upload -F "file=@../data/tenders/example.pdf"
```

**Evaluation material.** A tender that names the standard it used is a
labelled example: this product description produced this standard. The GeM
bid we looked at cited IS 10322 (Part 5/Section 2) for recessed LED
downlights - real procurement language paired with the answer a real
officer chose. Those make far better test cases than invented ones.

**Auditing.** A published tender is a decision already made, so there is
nothing left to recommend - but you can still ask whether the standards it
cites are current. That is the one use where a finished document is the
right input.

## Not committed

These are gitignored, and should stay that way. Real tenders name
officials, list their email addresses and office addresses, and carry bid
identifiers.
