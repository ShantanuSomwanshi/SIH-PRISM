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
python -m backend.rag_engine           # ingest new PDFs
python -m backend.rag_engine --rebuild # wipe and rebuild from scratch
python -m backend.rag_engine --dry-run # extract and chunk without embedding
```

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
4. Cache the raw OCR output in `ocr_cache/`, keyed to the file's SHA-256 so
   replacing a PDF invalidates it automatically.

The check is **per page, not per file**. Mixed documents are common: IS 1067
is a born-digital 2024 standard with one scanned page in the middle. A
per-file check would call it healthy and lose that page silently.

Chunking is also per page (1000 characters, 200 overlap), so a chunk never
straddles a page boundary and its page number is always correct. Each chunk
is prefixed with `[IS 33 : 1992] TITLE` so the standard number is searchable
in the chunk's own content.

Every chunk stores: `standard_id`, `title`, `doc_type`, `number`, `part`,
`publication_date`, `edition`, `status`, `source` (bare filename),
`page`, `total_pages`, `extraction_method`, `chunk_id`, `confidence`.

`ingestion_report.json` records characters per page, OCR page count and
watermark characters removed for each file, and warns on anything that
extracted poorly.

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

Two independent triggers:

1. **Too brief.** Fewer than `MIN_QUERY_TERMS` (3) meaningful words after
   removing filler. This is not about retrieval quality: "paint" matches
   IS 33 strongly, but still does not say whether you are buying pigment,
   testing it, or packaging it. Similarity is not sufficiency.
2. **Too close to call.** Top score below `WEAK_MATCH_SCORE` (0.0) *and*
   the top two candidates within `AMBIGUOUS_MARGIN` (1.5).

Confidence is `high` at or above `STRONG_MATCH_SCORE` (4.0) with the model
reporting sufficient evidence, `medium` above 0.0, otherwise `low`.

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
- Ingestion is repeatable and hash-based; a changed PDF is re-ingested.
- The collection is `prism_standards` and the model is `BAAI/bge-m3`.
  Changing either requires a full reindex - vectors from different models
  are not comparable.
- Secrets live in `backend/.env`, which is git-ignored. Never commit it.
