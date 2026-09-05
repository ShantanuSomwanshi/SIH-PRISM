# Commit Messages

A record of the commit messages used for the PRISM prototype repository.

---

## `Initial PRISM RAG prototype: backend, hybrid retrieval, frontend, and project documentation`

### Scope

- FastAPI backend prototype with health and document-ingestion endpoints.
- PDF ingestion into a local Chroma collection using Hugging Face embeddings.
- Hybrid retrieval: vector similarity, BM25, reciprocal rank fusion,
  cross-encoder reranking.
- Standalone terminal question-answering flow using Groq.
- React frontend prototype for product descriptions and recommendation output.
- Backend dependency metadata and project structure documentation.
- `PIPELINE.md` with purpose, workflow, architecture and setup commands.
- `.gitignore` rules keeping secrets, the virtual environment, source PDFs
  and the generated vector database out of Git.

### Intentionally excluded

- `backend/.env`, `backend/data/`, `backend/chroma_db/`, `.venv/`

---

## `Fix RAG pipeline: OCR ingestion, standards catalog, security, recommendation API`

A repair pass over the whole pipeline. The prototype ran, but several
failures were silent rather than visible.

### Ingestion

- Per-page OCR fallback for scanned pages. Detection is per page, not per
  file: IS 1067 is a born-digital 2024 document with one scanned page, which
  a per-file check would have lost silently. `1001.pdf` went from 132 to
  1,995 characters per page - previously its entire text layer was the
  download watermark, and BM25's filename matching made it look searchable.
- BIS watermark stripping, 15,816 characters removed across the corpus. It
  also carried a downloader's email address and IP into the vector store.
- Per-page chunking so a chunk never straddles a page boundary and its
  cited page number is always correct.
- Bare filenames in metadata instead of absolute Windows paths, which were
  stale after a folder move and leaked a local path into API responses.
- File-hash manifest, so replacing a PDF re-ingests it.
- `ingestion_report.json` recording extraction quality per file.

### Catalog

- `standards_catalog.json` maps each PDF to its real IS number and title.
  Chunks previously knew only a filename, so the API could not report a
  standard number at all.
- Entries are scored automatically from filename/cover agreement rather than
  hand-verified, so only low-confidence entries need review.

### Retrieval

- RRF keyed on `chunk_id` instead of chunk text. Two standards sharing a
  boilerplate paragraph merged into one result and inherited a single
  identity, which meant citing a passage under the wrong standard.
- One shared embedding definition. `main.py` used a different wrapper class
  from the other modules; divergent defaults would have broken search
  silently.
- BM25 index persisted and rebuilt only when the corpus fingerprint changes.
- Citations carry standard number, page and OCR provenance.

### Security

- `/ingest` disabled by default and API-key gated.
- CORS restricted to named origins rather than `*`.
- Per-IP rate limiting and request size caps.
- Generic error responses; full detail logged server-side only.
- Prompt hardened against instructions embedded in source text.

### API

- `POST /api/recommend` returning primary standard, allied standards,
  version status, certification, confidence and sources.
- Standard-level ranking so allied standards can surface; passage-level
  ranking returned everything from one document.
- Clarification branch for descriptions too brief to identify a product.
- Models load once at startup rather than on every import.

---

## `Stop tracking generated scraper downloads and the local ingestion manifest`

- `scraper/.gitignore` used `downloads/*`, which git anchors to the folder
  containing the `.gitignore`. It matched `scraper/downloads/` only and
  missed `scraper/legacy_scraper/downloads/` - 29 files, 796 KB.
- `processed_files.json` records which PDFs are in this machine's
  `chroma_db`, which is not committed. A fresh clone would have read it,
  skipped ingestion, and served an empty index.

---

## `Add frontend build setup, surface evidence in the UI, tidy clarification labels`

### Frontend

- Vite, React and Tailwind v4 setup. `package.json`, `index.css` and
  `tailwind.config.js` were empty files and `index.html`, `main.jsx` and
  `vite.config.js` did not exist, so the UI could not start at all.

### UI

- Request failures are shown to the user. The catch block previously only
  logged to the console, so an unreachable backend looked identical to
  nothing happening.
- Sources rendered with page numbers, and OCR-derived pages flagged with a
  warning to check numerical values against the original document.
- Allied standards marked as indexed or not held.
- Confidence shown in three states; a medium-confidence answer previously
  looked identical to a high-confidence one.

### Backend

- Clarification options are built from the product part of a title rather
  than a fixed character cut, which produced labels broken mid-phrase.
  Acronyms are preserved from an explicit list, since guessing by word
  length kept AND, FOR and PART in capitals.

### Documentation

- `PIPELINE.md` rewritten to describe the current architecture.
