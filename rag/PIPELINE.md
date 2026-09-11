# PRISM - Pipeline and Architecture

PRISM recommends the Indian Standard(s) that apply to a product description
or tender specification. PDFs are indexed locally, a query is answered with
hybrid retrieval, and an LLM turns the retrieved evidence into a structured
recommendation with citations.

This document describes the engine - the half that runs per request. The
BIS change detector lives in `collectors/bis/` and is not yet connected;
see **Handoff** at the end. `data/README.md` states the contract between
the two halves.

---

## 1. Problem

Procurement officials must reference the correct Indian Standards when
writing tender specifications. There are thousands of published standards
with overlapping scopes and frequent revisions, plus normative references
that also need citing. Specifications routinely omit relevant standards or
cite superseded editions, which causes ambiguity and procurement disputes.

PRISM takes a product description and returns:

- the most relevant primary standard
- allied standards (normative references, test methods, terminology)
- the edition and reaffirmation status
- applicable certification requirements
- page-level citations for every claim

---

## 2. Current status

**Working**

- Ingestion of text and scanned PDFs, with automatic per-page OCR
- Standards catalog mapping each file to its real IS number and title
- Hybrid retrieval (vector + BM25), fused and reranked
- Standard-level ranking, so allied standards can surface
- `POST /api/recommend` returning a structured recommendation
- A clarification branch for descriptions too brief to act on
- React frontend showing recommendations, sources and confidence

**Not yet built**

- No connection to the `collectors/bis` component, so live revision status is
  unknown and `status` is `"Unknown"` for every standard
- No certification data - `certification` always reports "Not determined"
- No deterministic normative-reference graph; allied standards are read out
  of retrieved text by the LLM
- Corpus is 10 documents, so most referenced standards are not held
- The reranker is English-only, which limits the multilingual claim
- No automated tests and no retrieval evaluation set

---

## 3. Repository map

```
rag/
  backend/
    config.py            All paths and settings, read from .env
    embeddings.py        The single definition of the embedding model
    pdf_extract.py       Page-by-page text extraction with OCR fallback
    build_catalog.py     Builds standards_catalog.json from the PDFs
    catalog.py           Loads the catalog, supplies per-chunk metadata
    rag_engine.py        Ingestion: extract, chunk, embed, store, report
    retriever.py         Hybrid search, fusion, reranking, terminal Q&A
    recommend.py         Recommendation logic behind /api/recommend
    main.py              FastAPI app, routes, security
    data/                Source PDFs (not committed)
    chroma_db/           Vector store (generated, not committed)
    ocr_cache/           Cached OCR text (generated, not committed)
    standards_catalog.json   Filename -> IS number and title (committed)
    ingestion_report.json    Per-file extraction quality report
  frontend/
    index.html, vite.config.js, package.json
    src/App.jsx          The UI
    src/main.jsx         React entry point
```

**Run every backend command from the `rag` folder**, using
`python -m backend.<module>`. That matches how `uvicorn backend.main:app`
resolves imports.

---

## 4. Setup

### Backend

```powershell
cd rag
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
copy backend\.env.example backend\.env
```

Then edit `backend/.env` and set `GROQ_API_KEY`.

**OCR requires Tesseract**, installed separately:
<https://github.com/UB-Mannheim/tesseract/wiki>, or `winget install
UB-Mannheim.TesseractOCR`. Set `TESSERACT_CMD` in `.env` to its full path,
or leave it blank if Tesseract is on your PATH.

The embedding model (`BAAI/bge-m3`, ~2.2 GB) and the reranker download on
first use into `~/.cache/huggingface`, not into the project.

### Build the index

```powershell
python -m backend.build_catalog        # draft the standards catalog
python -m backend.rag_engine           # ingest new or changed PDFs only
python -m backend.rag_engine --prune   # also remove PDFs deleted from data/
python -m backend.rag_engine --rebuild # wipe and rebuild from scratch
python -m backend.rag_engine --dry-run # show the plan; extract and chunk, store nothing
```

A normal run is incremental: files already in the index are skipped without
loading the embedding model, so adding one PDF to the corpus embeds that one
PDF. See **Which files get ingested** in section 5.

### Run

```powershell
uvicorn backend.main:app --reload      # from the rag folder
```

Startup takes about a minute - the embedding model, reranker and keyword
index all load before the first request. Wait for `Application startup
complete.` Interactive docs are at <http://127.0.0.1:8000/docs>.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Opens on <http://localhost:5173>, which is in the backend's default
`ALLOWED_ORIGINS`. Change both together if you change the port.

---

## 5. Ingestion

For each PDF, **page by page**:

1. Extract text with `pdfplumber`.
2. Strip the BIS download watermark. Every page of a portal-downloaded BIS
   PDF carries a line naming the downloader and their IP address. It is
   noise, it repeats hundreds of times, and it contains personal data that
   should not enter the vector store or an LLM prompt.
3. If what remains is under `MIN_CHARS_PER_PAGE` (default 200), treat the
   page as a scan: render it with PyMuPDF at `OCR_DPI` (default 300) and
   read it with Tesseract. Keep whichever result has more text.
4. If instead the page has plenty of text but that text is **mis-encoded**
   (see below), OCR it as well.
5. Cache the raw OCR output in `ocr_cache/`, keyed to the file's SHA-256 so
   replacing a PDF invalidates it automatically, and to `OCR_LANG` so
   adding a language pack does not keep serving the old reading. Only
   corpus files (PDFs inside `DATA_DIR`) are cached - see **Uploaded
   documents** below.

The check is **per page, not per file**. Mixed documents are common: IS 1067
is a born-digital 2024 standard with one scanned page in the middle. A
per-file check would call it healthy and lose that page silently.

### Mis-encoded Hindi pages

Older BIS PDFs set their Hindi in a legacy font (Krutidev, Chanakya and
relatives) from before Unicode. These fonts paint Devanagari glyphs onto
ordinary Latin codepoints, so `भारतीय मानक` extracts as `Hkkjrh; ekud`.
The text is not missing, it is mis-encoded - which means the "too little
text" rule never fires and a page of pure noise goes straight into the
index. No model can undo this, because the mapping differs per font, but
the *rendered* page is correct Devanagari, so OCR reads it fine.

Detection is the delicate part. The obvious test - "unusual characters on
the page" - is wrong: on IS 10262 it flagged 9 of 44 pages, and 8 of them
were ordinary English mix-design pages full of `=`, `×`, `+` and `≈`.
OCR-ing those would have replaced good text with worse text. The rule that
works uses two signals, both about the shape of *words*, which mathematics
does not produce: glyph substitutes appearing inside words, and runs of
four or more letters with no vowel at all. On the same file that flags
page 1 only, which is correct.

Reading these pages needs the Tesseract Hindi pack and `OCR_LANG=eng+hin`.
Without it the OCR result comes back with no Devanagari in it, the page is
marked `legacy-font` and **left out of the index** rather than swapped for
a second kind of gibberish. `ingestion_report.json` reports how many pages
that was. `OCR_LEGACY_FONTS=false` skips the check entirely.

Chunking is also per page (1000 characters, 200 overlap), so a chunk never
straddles a page boundary and its page number is always correct. Each chunk
is prefixed with `[IS 33 : 1992] TITLE` so the standard number is searchable
in the chunk's own content.

Every chunk stores: `standard_id`, `title`, `doc_type`, `number`, `part`,
`publication_date`, `edition`, `status`, `source` (bare filename),
`page`, `total_pages`, `extraction_method`, `chunk_id`, `confidence`,
`source_sha256` (hash of the PDF it came from) and `source_chunks` (how
many chunks that PDF produced).

`ingestion_report.json` records characters per page, OCR page count and
watermark characters removed for each file, and warns on anything that
extracted poorly. It describes the **whole index**: a run updates the
entries for the files it processed and keeps the rest, so adding one PDF
does not shrink the report to that one file.

### Which files get ingested

`processed_files.json` is the list of ingested files - filename, SHA-256,
chunk count, time. A file is skipped only when the index confirms it:

- If its chunks carry `source_sha256` equal to the file's current hash, and
  there are exactly `source_chunks` of them, it is fully and currently
  indexed. The index vouches for itself, so a lost manifest is rebuilt
  rather than triggering a re-embed.
- Chunks ingested before those fields existed are checked against the
  manifest instead: same hash, same chunk count.

Anything else is re-ingested, with the reason printed: a new file, a
changed file, an index holding only some of a file's chunks (an
interrupted run), or a manifest listing files the index does not have
(`chroma_db` deleted or swapped). Trusting the manifest alone used to skip
every file in that last case and leave the index empty.

**Replacing a PDF removes its old chunks.** Chunk ids are
`<file>::p<page>::c<n>` and Chroma upserts by id, so a new version
overwrites the ids it reproduces - but if it has fewer pages, or a page
splits into fewer pieces, the old version's extra chunks used to stay
searchable. After the new chunks are stored, any chunk of that file whose
id the new version did not produce is deleted.

**Removing a PDF from `data/`** does not delete its chunks by default; the
run warns that they are still searchable. `--prune` removes them, along
with their manifest and report entries. It is opt-in because a
mis-set `DOCUMENTS_DIR` would otherwise empty the index in one run.

### Uploaded documents

`POST /api/recommend/upload` reads a PDF **entirely in memory**
(`extract_pdf_bytes`). Nothing from a tender is written to disk: no temp
file and no OCR cache entry. The upload route used to save each tender to
a temp file named `upload.pdf`; because the OCR cache is named after the
file, every scanned tender's text ended up in `ocr_cache/upload.json`,
outliving the request, overwritten by the next upload, and shared by two
uploads arriving together. `extract_pdf` on a path also skips the cache
for any file outside `DATA_DIR`.

### Current corpus

10 documents, 118 pages, 311 chunks, 15 pages recovered by OCR, 15,816
watermark characters removed.

---

## 6. The standards catalog

`standards_catalog.json` maps each filename to its real identity. Without
it a chunk knows only that it came from `10_1_1990_reff2020.pdf`, not that
this is IS 10 (Part 1) : 1990.

`build_catalog.py` reads each PDF's **cover page only** - body pages contain
prose like "...is 2 mm..." and cross-references like "33-1960" that look
like standard numbers and years. The filename wins for the number (OCR
mangles digits; one cover's text layer reads "IS 10 ( Part 1 ): 1910"), and
the cover supplies the title and edition.

Entries are **scored, not hand-verified**. The filename and cover page are
independent sources; where they agree the entry verifies itself. Confidence
drops on disagreement, a failed title sanity check, or an OCR'd cover. Only
`medium` and `low` entries need a human, which is what makes this scale
past a handful of documents.

Field names deliberately match the scraper's SQLite columns so the two
components join cleanly later.

---

## 7. Retrieval

`retriever.py`, for each query:

1. Vector search over Chroma (`prism_standards`, `BAAI/bge-m3`) - 20 chunks.
2. BM25 keyword search - 20 chunks. The standard number and title are folded
   into the indexed text so "IS 33" matches directly.
3. Reciprocal Rank Fusion at `1/(60 + rank)`, **keyed on `chunk_id`**.
   Keying on chunk text merges two different standards that share a
   boilerplate paragraph, and the survivor inherits one of their identities
   - which means quoting a passage under the wrong standard number.
4. Cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`).

The BM25 index is saved to `bm25_index.pkl` and rebuilt only when the corpus
fingerprint (chunk count plus ingestion manifest) changes.

`search_standards()` groups the results **by standard** rather than
returning a flat list of passages. A standard scores on its best chunk plus
`log1p(chunk_count)`, so one lucky match does not beat consistent relevance.
Without this grouping the top passages nearly always come from a single
document and allied standards can never surface.

---

## 8. Recommendation API

`POST /api/recommend` with `{"query": "..."}` returns either a
recommendation or a clarifying question.

```json
{
  "clarification_needed": false,
  "primary_standard": "IS 38 : 1976",
  "title": "Specification for Antimony Oxide for Paints",
  "allied_standards": [
    {"code": "IS 33 : 1992", "role": "methods of sampling and test",
     "in_corpus": true}
  ],
  "version_status": "...",
  "certification": "Not determined...",
  "confidence_flag": true,
  "confidence": "high",
  "reasoning": "...",
  "sources": [
    {"citation": "IS 38 : 1976, page 4", "standard_id": "IS 38 : 1976",
     "page": 4, "ocr": false}
  ]
}
```

### Guardrails

- The model may only choose a primary standard from the retrieved
  candidates. Anything else is logged and replaced with the top-ranked
  standard, so IS numbers cannot be invented.
- The prompt forbids the model from mentioning certification. A wrong
  certification claim in a tender is worse than no claim, and there is no
  data source for it yet.
- `version_status` states plainly that live revision status is unverified
  rather than implying the standard is current.
- Retrieved text is wrapped in `<candidate>` tags and the model is told it
  is data, never instructions.
- Citations mark OCR'd pages. OCR misreads characters - one page rendered
  "100 +/- 1 degC" as "100 + 1 degC" - so a reader needs to know which
  numbers to check against the original.

### When it asks instead of answering

Three independent triggers:

1. **Too brief.** Fewer than `MIN_QUERY_TERMS` (3) meaningful words after
   removing filler. This is not about retrieval quality: "paint" matches
   IS 33 strongly, but still does not say whether you are buying pigment,
   testing it, or packaging it. Similarity is not sufficiency.
2. **Too close to call.** Top score below `WEAK_MATCH_SCORE` (0.0) *and*
   the top two candidates within `AMBIGUOUS_MARGIN` (1.5).
3. **Same-family tie.** The top two candidates are different *parts* of the
   same standard, within `AMBIGUOUS_MARGIN`. This needs its own trigger
   because trigger 2 requires a weak score, and "household zig-zag sewing
   machine head" matches all four parts of IS 15449 *strongly*. Retrieval
   is working perfectly and the answer is still undetermined.

Confidence is `high` at or above `STRONG_MATCH_SCORE` (4.0) with the model
reporting sufficient evidence, `medium` above 0.0, otherwise `low`.

### Cross-questioning (`clarify.py`)

The question is derived from what the *candidates* disagree about, not from
a fixed list. Three dimensions, in order of how hard the ambiguity is:

- **Part** - candidates are parts of one standard. IS 15449 splits into
  General / Accuracy / Sewing / Durability requirements: four documents,
  one product. No further description of the sewing machine can separate
  them; only naming the aspect can.
- **Role** - candidates are different *kinds* of document. Buying a
  product, testing it and maintaining it are three different standards for
  the same object, read out of the title ("Methods of test for...",
  "Code of practice for...").
- **Product** - candidates are genuinely different products. The fallback.

The rule that stops this becoming a form: **never ask a question whose
answer cannot change the outcome.** A dimension the candidates agree on is
never raised, and when nothing is left to disambiguate, nothing is asked.

The API stays **stateless** across rounds. The client returns the answers
it was given plus the dimensions already covered; the server holds no
session. Answers *narrow the candidate set* rather than only being appended
to the query - but only as an intersection with what retrieval returned on
this request's own evidence, so a client can narrow and never inject. An
answer that would eliminate every candidate is ignored rather than obeyed.

### Draft tender clauses (`tender.py`)

Templates and data - deliberately **not** a second call to the language
model. A model asked to "write a testing clause" produces fluent text about
sampling plans and acceptance criteria that reads exactly like the grounded
clauses and is invented. In a document that becomes a contract, that is the
worst available failure and it is not detectable by reading.

So every clause is either grounded in a retrieved page or a visible
`[BRACKETED]` blank, and there is no third category. Standards the model
proposed are quarantined in their own clause, labelled as not read out of
the references clause. Certification and current-edition status appear as
verification steps addressed to the officer, never as claims.

This drafts language for the officer to edit. It does not write the tender.

### GeM category suggestion (`gem/suggest.py`)

Two tiers of unequal confidence. **Exact**: the GeM category's own name
cites the standard, so the marketplace has already made the link and we
only read it back. **Keyword**: no category cites it, so terms are matched
by IDF - a word used by six categories is worth far more than one used by
five hundred.

The honest signal matters more than the ranking: some words do not exist in
GeM's vocabulary at all ("downlight" and "recess" occur zero times in 9,761
category names). When the officer's words are absent, the result says so,
because keyword search *on GeM itself* would fail the same way. That
absence is the argument for semantic matching.

---

## 9. Security

- `POST /ingest` is disabled unless `INGEST_ENABLED=true` and requires a
  matching `X-API-Key`. Anything written there becomes source material the
  LLM treats as authoritative, so an open ingest route is a way to poison
  answers.
- CORS is restricted to `ALLOWED_ORIGINS`, never `*`.
- Per-IP rate limit, default 30 requests per 60 seconds. In-memory, so it
  resets on restart and does not span processes - adequate for a prototype,
  not for deployment.
- Request caps: `MAX_QUERY_CHARS` 4000, `MAX_INGEST_DOCS` 100,
  `MAX_INGEST_CHARS` 50000.
- Errors are logged in full server-side and returned as generic messages.
- `/docs` is public. Disable or protect it before any real deployment.

---

## 10. Handoff to the BIS collector

`collectors/bis/` monitors BIS pages, detects changes and extracts standard
metadata into SQLite. It is not yet wired in. Two visible seams:

- `status` is `"Unknown"` on every catalog entry
- `version_status` says revision status is unverified

The catalog already uses the collector's field names (`standard_id`,
`title`, `status`, `last_amendment_date`, `publication_date`, `edition`),
so connecting them is a fill-in rather than a rewrite. When it lands, the
collector should write its database into `data/`, which is where the
engine expects to read it.

---

## 11. Conventions

- Recommendations must be grounded in retrieved chunks. Unsupported claims
  are reported as unknown, never invented.
- Source metadata and standard identifiers are preserved through ingestion,
  retrieval, reranking and serialisation so answers stay auditable.
- Ingestion is repeatable and hash-based; a changed PDF is re-ingested and
  its old chunks removed. A file is skipped only when the index confirms it.
- Uploaded documents never touch disk.
- The collection is `prism_standards` and the model is `BAAI/bge-m3`.
  Changing either requires a full reindex - vectors from different models
  are not comparable.
- Secrets live in `backend/.env`, which is git-ignored. Never commit it.
