# data/

The boundary between the two halves of PRISM.

**Collectors write here. The engine reads from here. Nothing else.**

That one rule is what keeps the halves independent. The scraper can run on
a schedule, on another machine, or not at all, and the API does not care -
it reads whatever is in this folder and reports honestly how fresh it is.

```
collectors/            data/                       rag/  (engine)
  bis/      ──write──▶   standards.sqlite   ──read──▶  status, amendments
  gem/      ──write──▶   gem_categories.csv ──read──▶  category search
                         reference_graph.json         allied standards
                         pdfs/                        full text, citations
```

## What belongs here

| File | Written by | Read by | Holds |
|---|---|---|---|
| `standards.sqlite` | `collectors/bis` | engine | BIS metadata: number, title, status, amendment dates, withdrawal |
| `gem_categories.csv` | `collectors/gem` | engine | the GeM category catalogue snapshot |
| `reference_graph.json` | `tools/build_reference_graph` | engine | which standard cites which |
| `pdfs/` | `collectors/bis` | engine | standard documents |

## What does not belong here

Anything derived that can be rebuilt from the above - the Chroma vector
store, OCR caches, BM25 indexes. Those live beside the code that builds
them, because deleting them costs time, not data.

## Rules

1. **Collectors never read the engine's files.** If a collector needs to
   know what the engine wants, that is a sign the boundary is in the wrong
   place.
2. **The engine never writes here.** A request should not change source
   data.
3. **Everything here carries a timestamp.** The engine must be able to say
   "as of 03-09-2026" rather than implying the data is current.
4. **Nothing here is committed** except this README. It is all fetched or
   generated - except `gem_categories.csv`, which is committed because it
   is the snapshot everything else is compared against.
