# PRISM

**Procurement Recommendation for Indian Standards Matching**

Smart India Hackathon 2026, Problem Statement 26108. Team: localhost legends.

Given a product description or a tender document, PRISM identifies the
applicable Indian Standard(s), the allied standards that should also be
cited, and whether what it found is still current.

## Layout

The project is split by **when code runs**, not by what it is about.

```
collectors/     run on a schedule; write into data/
  bis/          watches BIS for new, revised and withdrawn standards
  gem/          snapshots the GeM category catalogue        (planned)

data/           the boundary - collectors write, engine reads

rag/            runs per request
  backend/      retrieval, recommendation, the API
    gem/        GeM catalogue lookup and live verification
  frontend/     the web interface
```

A collector has no user waiting on it: it can take an hour, need a browser,
and fail without anyone noticing until the next run. The engine has a
request open and a second to answer. Keeping them apart means the API never
depends on a scraper being healthy, and the scraper can be run anywhere.

`data/README.md` states the contract between them.

## Running it

Each half is independent. See:

- `rag/PIPELINE.md` - the engine: setup, ingestion, retrieval, the API
- `collectors/bis/README.md` - the BIS change detector

## Where things stand

Working: OCR ingestion of scanned standards, hybrid retrieval with
grounded page-level citations, a recommendation API with a clarification
branch, extraction of the reference graph between standards, and the GeM
category catalogue as a searchable corpus.

Not yet connected: the BIS collector does not feed the engine, so a
standard's live status still reads `Unknown`. Certification requirements
are reported as not determined rather than guessed. Both gaps are stated
in the API's own responses rather than hidden.
