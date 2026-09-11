# PROJECT_STATUS

This document is a repository handoff note for a future AI assistant that has no access to the codebase. It describes the repository as it exists in the current workspace, on branch `rag`, connected to `origin` on GitHub at `https://github.com/ShantanuSomwanshi/SIH-PRISM.git`. It is intentionally written as a plain-language operating guide, not a checklist of filenames alone.

## 1. Repository structure and architectural split

The repository is best understood as a two-half system split by execution timing rather than by subject matter. The top-level folders are intentionally simple:

- `README.md` documents the product and high-level project intent.
- `data/` is the boundary between the scheduled collector half and the request-serving retrieval half. It contains generated artifacts and source inputs that the collectors write and the RAG engine reads.
- `collectors/` contains the BIS change detector pipeline and its related supporting code. In the current workspace, the BIS collector is organized under `collectors/bis` rather than a top-level `scraper/` folder. It is the source of standards metadata and page-change detection logic using a SQLite database and an HTML page-hashing approach.
- `rag/` is the live retrieval, recommendation, API, and frontend half. It contains the FastAPI application, the standards ingestion/retrieval engine, the reference graph builder, the GeM catalogue and GeM suggestion logic, and the Vite/React frontend.

The intended contract between the two halves is formalized in `data/README.md`. Collectors write new standard state and metadata into the data boundary, while the retrieval side reads from those artifacts and from the generated vectors and catalogs located around the engine. The project deliberately avoids coupling API requests to the health of the BIS collector; the collector may run on a timer or a different machine, and the API reads the data boundary instead of maintaining a direct dependency. In that sense the topology is `collectors/bis` → `data/` → `rag/backend` and `rag/frontend`.

The main `rag` package is the application that is actually runnable for live user-facing use. It has a FastAPI backend, a Chroma vector store, a BM25 keyword index, a Hugging Face embeddings layer, a LangChain + Groq integration, and a Vite React frontend. Its code is not meant to be run as an all-in-one command; it is intentionally separated so the retrieval side can answer requests independently from collector output.

The BIS collector half is named `collectors/bis` and currently centers around `bis_change_detector/`. That package contains modules for:

- parsing BIS artifact metadata and page artifacts,
- computing page and row fingerprints,
- discovering standards and matching page hashes,
- writing the SQLite metadata store,
- running scheduler and change-detection loops,
- coordinating the Selenium legacy scraper wrapper through an `XLSX` temporary adapter.

The code tries to preserve the old legacy scraper by keeping `legacy_scraper/download_standards.py` unchanged and by creating a temporary workbook for only IDs that changed or are new. That means the `collectors/bis` structure is a wrapper around the old BIS scraper rather than a fully replacement. The collector does not currently feed the engine in a live way, which is why the API’s current status logic often has to report “not known” or “not determined” rather than claiming live currentness.

## 2. What is actually built and working

The repository has an established backend workspace under `rag/backend`. The real implementation files are described below in one-line functional terms.

### RAG backend modules

- `rag/backend/main.py` is the FastAPI server entry point. It defines the health check route, the recommendation API routes, the upload recommendation route, the standards-reference chain route, and the protected ingest route. It also loads the embedding model and retriever on startup and returns secure CORS and key-policy behavior.
- `rag/backend/config.py` is the single configuration authority. It owns all file path constants, model constants, Chroma collection naming, request size caps, rate limiting, API key policies, GeM configuration, and OCR settings.
- `rag/backend/documents.py` wraps uploaded tender document parsing. It supports `.pdf`, `.docx`, `.txt`, and `.md` inputs and extracts text from them in a uniform shape so the same `recommend_from_document` logic can work over uploaded documents.
- `rag/backend/pdf_extract.py` is the PDF text extractor and OCR engine. It handles pdfplumber extraction, PyMuPDF page render, OCR fallback using Tesseract, pre-Unicode legacy font detection for Hindi pages, and watermark/boilerplate cleanup for BIS PDFs.
- `rag/backend/rag_engine.py` is the PDF ingestion and indexing pipeline. It chunks extracted text per page, writes a generated manifest, writes an ingestion report, compares the index to what the saved chunks actually say, and supports `--prune` and `--rebuild` ingestion patterns.
- `rag/backend/catalog.py` loads and interprets the generated catalog mapping between filename and metadata. It is the bridge between an extracted PDF file and a standard’s `standard_id`, title, edition, year, part, and office-level fields used in chunk metadata. Its `CHUNK_FIELDS` match the columns emitted by the BIS collector.
- `rag/backend/build_catalog.py` builds the draft `standards_catalog.json` by parsing filenames and the cover page of standards PDFs. It is a draft, not an authoritative proof.
- `rag/backend/build_reference_graph.py` constructs `reference_graph.json` by scanning the corpus PDFs, extracting normative references from the documents, and writing graph edges with confidence and in-corpus resolution flags.
- `rag/backend/reference_extract.py` is the regex-based parser that extracts normative references from standards text, classifying them into reference-role categories such as test method, terminology, sampling, and installation.
- `rag/backend/references.py` implements the reference graph accessor layer. It can return outgoing edges, an allied-standards list, citation chains, and graph stats from `reference_graph.json`.
- `rag/backend/retriever.py` is the hybrid retrieval engine. It combines a vector store and a BM25 keyword index, runs reciprocal rank fusion, applies a reranker using a cross-encoder, and groups results by standard during ranking. It also formats evidence and citation strings for recommendation and LLM prompts.
- `rag/backend/recommend.py` is the recommendation engine. It turns retrieved groups into a `RecommendResponse` object, asks clarifying questions when ambiguity persists, decides confidence, chooses a primary standard, bases allied standards on graph edges and model output, and uses the GeM function and tender-draft builder as optional overlays.
- `rag/backend/clarify.py` implements the clarification branching and answer modeling. It asks questions about dimension families such as part, role, and product instead of asking a single generic question.
- `rag/backend/tender.py` turns the `RecommendResponse` into a tender-draft clause structure. It explicitly marks placeholders and notes what is grounded or not grounded, and writes a caveat that the draft is not a tender-ready legal document.
- `rag/backend/evaluate.py` is an evaluation harness that compares retrieval outputs against `eval_set.json` and emits results for precision and recall-style evaluation, optionally using an LLM.
- `rag/backend/list_models.py` lists Groq and local model capabilities for the backend environment.
- `rag/backend/embeddings.py` centralizes the shared embedding model and vector store so Chroma, retrieval, and ingestion cannot drift into using inconsistent embedding wrappers.

### GeM integration modules

- `rag/backend/gem/__init__.py` is the package manifest layer for the GeM integration, exposing category and search helpers.
- `rag/backend/gem/__main__.py` provides the command-line driver for GeM commands such as stats, standard, find, query, search, and verify.
- `rag/backend/gem/models.py` defines the `Standard` and `Category` dataclasses for parsed GeM categories.
- `rag/backend/gem/catalog.py` loads the local GeM category catalogue snapshot from `gem_categories.csv` and exposes vocabulary, standard-to-category indexing, and product-name-to-category maps.
- `rag/backend/gem/client.py` is the HTTP client for the GeM marketplace. It supports cache-aware, rate-limited, user-agent-aware HTML fetches, and intentionally raises `GemUnavailable` when live access is disabled or fails.
- `rag/backend/gem/extract.py` parses category listings from GeM HTML pages and differentiates the strategies used to recognize a category name from HTML snippets.
- `rag/backend/gem/parse.py` normalizes a GeM category string into a `Category` dataclass and resolves the underlying standard citations.
- `rag/backend/gem/search.py` performs live or cached category search, used for verification and comparison against the snapshot.
- `rag/backend/gem/suggest.py` selects GeM categories for a recommended standard using exact category-name evidence, fallback keyword evidence, and an honest note when vocabulary terms are absent from the GeM catalogue.

### BIS collector modules

- `collectors/bis/bis_change_detector/artifact_parser.py` parses metadata and evidence from a BIS downloaded artifact, including title, scope, committee details, and standards contextual metadata.
- `collectors/bis/bis_change_detector/change_detector.py` is the main BIS watch loop and page change detector. It hashes the visible page, compares the current and previous artifacts, and decides when to run a discovery or scraper pass.
- `collectors/bis/bis_change_detector/config.py` holds BIS URLs, database paths, scraper settings, and change-signal limits.
- `collectors/bis/bis_change_detector/db.py` creates the SQLite schema and provides the standard metadata storage, run recording, and change-log API. It is where the collector stateful `monitor_state`, `crawl_runs`, `standards`, and `standard_delta_log` tables live.
- `collectors/bis/bis_change_detector/discovery.py` discovers standards from page structure and generates IDs that can be fed into the library or spreadsheet-based wrapper.
- `collectors/bis/bis_change_detector/fingerprint.py` computes metadata fingerprints for page rows and artifact variation; this is the basis for row-level and page-level change detection.
- `collectors/bis/bis_change_detector/logging_config.py` sets up the silent, per-run, per-module logger arrangement for the collector.
- `collectors/bis/bis_change_detector/page_hasher.py` normalizes page HTML and computes deterministic SHA-256 page hashes used by the scheduler.
- `collectors/bis/bis_change_detector/scheduler.py` schedules the periodic BIS monitoring pass and handles a long-running loop with the scheduler library.
- `collectors/bis/bis_change_detector/scraper_adapter.py` wraps the Selenium/BIS legacy download flow into a filesystem and workbook adapter for temporary discovery runs.

### Supporting packaged files

- `rag/frontend/src/App.jsx` is the user-facing web UI. It calls the FastAPI endpoints from a Vite React page and renders the API’s `RecommendResponse` structure, including clarifying questions, confidence, sources, allied standards, GeM categories, and tender-draft clauses. It implements a search box, upload document support, and a consent/clarification feedback workflow.
- `rag/frontend/src/main.jsx` is the Vite entrypoint that mounts the React application.
- `rag/frontend/src/index.css` holds the global styling and the imported theme styling used by the page.

## 3. API surface

The backend is a FastAPI app in `rag/backend/main.py` with five meaningful user-facing routes and one protected ingestion route.

1. `GET /`
   - Method: `GET`
   - Request: no body.
   - Response: a health object with fields `status`, `collection`, `chunks`, `ingest_enabled`, and `api_key_required`.
   - Internally: reads the shared vector store from the FastAPI `lifespan` state and reports the number of chunks in the Chroma collection. It also reports whether the API key requirement is active and whether ingestion is permitted.

2. `POST /api/recommend`
   - Method: `POST`
   - Request shape: `RecommendRequest` as `query: str`, `answers: list[ClarifyAnswer]`, `asked: list[str]`, `include_tender: bool = True`, `include_gem: bool = True`.
   - Response shape: `RecommendResponse` with `clarification_needed`, `message`, `questions`, `asked`, `primary_standard`, `title`, `allied_standards`, `version_status`, `certification`, `confidence_flag`, `confidence`, `confidence_note`, `reasoning`, `sources`, `reference_chain`, `gem_categories`, `tender_draft`.
   - Internally: validates the query and API key requirement via dependency injection, loads the retriever and Groq-backed LLM from the app `state`, passes the search text + clarifying answers to `recommend()`, and catches internal exceptions as a 500 error. It uses the `RecommendResponse` model object as the return contract.

3. `POST /api/recommend/upload`
   - Method: `POST`
   - Request shape: multipart file upload under key `file` with `UploadFile = File(...)`.
   - Response shape: same `RecommendResponse` as ordinary recommendation.
   - Internally: reads the uploaded bytes from the request, calls `documents.extract_upload(filename, data)` to parse PDF, DOCX, TXT, or MD, logs parsing information, and then hands the resulting text to `recommend_from_document()` in the same recommendation stack. This path intentionally treats the uploaded tender as a passage chunking problem rather than one long vector embedding input.

4. `GET /api/standards/references`
   - Method: `GET`
   - Request shape: query parameter `standard_id` and optional `depth` capped at 4 via max/min in the route. It is intended to show the reference-graph chain for a standard: what it cites and what those standards cite onward.
   - Response shape: object `{stats, chain}` where `stats` describes `edges`, `resolved`, and `outdated_citations`, and `chain` is nested reference data.
   - Internally: uses `backend.references.graph_stats()` and `backend.references.chain()` to show the citation chain if `reference_graph.json` is present; otherwise it returns 503 with a command hint to build the graph. It uses the API key dependency if configured.

5. `POST /ingest`
   - Method: `POST`
   - Request body: list of `DocumentIngest` records with fields `id`, `content`, `metadata`.
   - Response: `{status: "success", ingested: N}` or an error with standard FastAPI HTTP error detail.
   - Internally: requires `INGEST_ENABLED=true` and a valid `INGEST_API_KEY` header; then writes documents into the vector store with `store.add_documents(...)`. It is deliberately protected because ingestion writes directly into the trusted search corpus and the data will later flow into the LLM context.

Other supporting routes are not present as formal path decorations; the API is intentionally small and read-only around the recommendation and ingestion model. The `main.py` file also implements middleware for CORS and request rate limiting. The `rate_limit` middleware is in-memory and keyed by IP, and it returns a JSON error with `detail: "Too many requests. Please slow down."` when a client exceeds the configured limit.

## 4. Data model and schema

The repository uses several schemas and metadata forms:

### Backend metadata model for standards chunks

The backend uses the `catalog.CHUNK_FIELDS` tuple, with metadata fields copied onto every chunk of every indexed standard:

- `standard_id`
- `title`
- `doc_type`
- `number`
- `part`
- `publication_date`
- `edition`
- `status`
- `reaffirmed_year`
- `confidence`

The catalog loader `metadata_for()` converts this into per-chunk metadata for Chroma, and every chunk also carries fields from the extraction process such as `source`, `page`, `total_pages`, `extraction_method`, `chunk_id`, `source_sha256`, and `source_chunks`. These fields serve public citation, debug traceability, and re-ingestion safety. The chunk metadata is what allows the retriever to explain evidence in the form `IS 33 : 1992, page 12 [OCR]` and the API to group results by standard.

### Standards catalog model

The generated file `rag/backend/standards_catalog.json` is not a SQL schema but a JSON catalog mapping each `filename` to a standard metadata record. The file is built by `build_catalog.py` and later trusted by `retriever.py` and the recommendation engine. It records a draft standard metadata record to the extent the catalog builder can determine it from the filename and cover page. Fields are deliberately close to the collector’s database schema so the two halves can match. This file is used as the primary local metadata source for standard title, edition, version status, and `standard_id` labels where the vector store only has a chunk-level `source` filename.

### Reference graph model

The `rag/backend/reference_graph.json` file is the JSON output of `build_reference_graph.py`. It is a graph object with the fields `generated_at`, `documents`, and `edges`. Each edge has fields such as `from`, `from_file`, `to_number`, `to_part`, `to_section`, `cited_year`, `cited_title`, `role`, `page`, `confidence`, `source`, `context`, `in_corpus`, `resolved_id`, and optional `edition_note` if the cited edition differs from the edition in the indexed standard.

This graph is not a database table. It is a generated reference map consumed by `backend.references.py` and in turn surfaced by `GET /api/standards/references` and `recommend.py` for allied standards.

### Chroma vector store schema and metadata

The repository uses Chroma’s persistent directory model rather than Postgres/pgvector. The collection name is configured as `prism_standards`. The backend config sets `CHROMA_DIR` and `COLLECTION_NAME = "prism_standards"` and `EMBEDDING_MODEL = "BAAI/bge-m3"`. The vector store is persisted locally under `rag/backend/chroma_db/`. All metadata stored with vectors is built from `catalog.CHUNK_FIELDS` plus extraction, identifier, and source metadata. The vector store is not the authoritative data transfer mechanism from the collector; its role is the search and retrieval side.

### BIS collector SQLite schema

The collector uses a local SQLite database and database file path environment for the BIS metadata. The SQLite schema in `collectors/bis/bis_change_detector/db.py` includes the following tables:

- `monitor_state(key, value, updated_at)`
- `crawl_runs(run_id, started_at, finished_at, tier1_hash, status, message, standards_processed)`
- `standards(standard_id, title, status, last_amendment_date, publication_date, edition, scope, is_active, row_fingerprint, page_fingerprint, source_artifact, raw_text_excerpt, extraction_warnings, first_seen_at, last_seen_at, updated_at)`
- `standard_delta_log(id, run_id, standard_id, change_type, old_fingerprint, new_fingerprint, old_status, new_status, created_at, details)`

The schema deliberately uses row fingerprints and page fingerprints for change detection. It also tracks full `run_id` and `standard_id` deltas for audit, new standard insertion, update, and withdrawal processing. `standard` records can be marked `WITHDRAWN` through `mark_removed()` when discovery shows a required identification set and a discovered page no longer has the old standard. `get_standards()` and `get_by_ids()` are the main inspection accessors, while `upsert_standard()` writes metadata rows and `mark_removed()` triggers updates for withdrawn standards.

The use of SQLite in the collector is a significant design decision because the project is intentionally not using Postgres or pgvector in the BIS collector. The vocabulary of the data model is intentionally aligned with the `catalog` metadata fields, allowing the backend to integrate a retrieved source into a standard’s title and version.

## 5. Dependencies and actual technologies in use

The repo works in two installed ecosystems: Python and Node.

### Python backend dependencies

The `rag/backend/requirements.txt` file is the canonical Python stack and it contains the following packages:

- `fastapi[standard]>=0.115.0` with `pydantic>=2.9.0` and `python-dotenv>=1.0.1` for the web service and environment loading.
- LangChain stack: `langchain>=0.3.0`, `langchain-core>=0.3.0`, `langchain-community>=0.3.0`, `langchain-text-splitters>=0.3.0`, `langchain-chroma>=0.1.4`, `langchain-huggingface>=0.1.0`, and `langchain-groq>=0.2.0`.
- Chroma vector store package: `chromadb>=0.5.0`.
- Embeddings and reranking: `sentence-transformers>=3.0.0` and `rank-bm25>=0.2.2` (BM25 direct keyword search).
- GeM scraping and parsing: `requests>=2.32.0` and `beautifulsoup4>=4.12.3`.
- PDF extraction: `pdfplumber>=0.11.0`.
- OCR: `pytesseract>=0.3.13`, `PyMuPDF>=1.24.0`, and `Pillow>=10.4.0`.
- LLM client: `groq>=0.11.0`.

The backend also uses `langchain_chroma` and `langchain_huggingface`, which are explicit wrappers from the same library family. It is not using `pgvector`; rather it uses Chroma persisted locally in `chroma_db` and an additional BM25 pickle cache.

### BIS collector dependencies

The collector package dependencies in `collectors/bis/requirements.txt` are:

- `apScheduler>=3.10,<4`
- `beautifulsoup4>=4.12`
- `filelock>=3.13`
- `openpyxl>=3.1`
- `pandas>=2.0`
- `pypdf>=5.0`
- `python-dotenv>=1.0`
- `requests>=2.31`
- `selenium>=4.20`

This confirms the BIS collector’s own technology stack is scheduler-driven and Selenium-based; it is intentionally local and mostly Pythonic rather than integrated into the main backend stack.

### Frontend dependencies

The frontend `rag/frontend/package.json` contains a Vite + React web UI. It uses `vite`, `react`, `react-dom`, `@vitejs/plugin-react`, `@tailwindcss/vite`, and `tailwindcss`. It uses the Vite development command and build command; the toolchain is a standard Vite/Javascript environment. Its dependency model is a modern static web UI with React rather than a server-rendered template.

## 6. Known gaps and stubbed-out code

The strongest known gap is that the BIS change detector is not connected to the main retrieval engine. This is the canonical example of a design contract not yet implemented. The catalog and recommendation code are built to say explicitly that version status is “published in source document; status of newer revision not yet verified,” and that the certification rule is “not determined.” The engine is honest about it rather than guessing.

The code also contains several areas that are partial or intentionally deferred:

- `GEM_LIVE_ENABLED` defaults to `false` in `config.py`. Live GeM lookups are implemented but not enabled by default, as the code deliberately chooses a local-snapshot or cached path for demos and prototypes.
- The local GeM catalogue in `gem_categories.csv` is a snapshot and is a generated artifact in the repository context. It is supported by `gem/suggest.py`, `catalog.py`, and `parse.py`, but the backend does not guarantee live verification of all categories in the marketplace.
- The `POST /ingest` route is disabled until `INGEST_ENABLED=true` and `INGEST_API_KEY` are deliberately supplied.
- `DocumentIngest` data is not automatically converted into a trusted metadata model beyond the straightforward storage into the vector store; the code intentionally says the vector store is a trusted resource but it is not new-source validation. This is an ingestion sensitivity area.
- `recommend.py` contains a branch that says one standard’s reference chain is optional and that the graph may not be built; it returns `None` rather than an invented chain. It is a strong example of the repository’s honesty regime.
- `tender.py` and `recommend.py` consistently treat the draft tender as a human-edited artifact, not a final legal instrument. It writes explicit placeholder fields and caveats to identify all human-authored parts. Draft generation is therefore partially complete and intentionally partial.
- The `legacy_scraper` directory in the BIS collector remains unchanged by design; the project includes a legacy wrapper but a full scraper replacement is not the goal of the main branch.
- The repository includes `.bak` duplicates of `main.py`, `requirements.txt`, and `retriever.py` in `rag/backend`. These are backup files and appear as artifacts of earlier versions rather than active code. They do not need to be imported. They document that the project has been iteratively evolved and that main logic has been cut over into the current path.

Specific files that are intentionally only drafts or not enabled by default:

- `standards_catalog.json` is a draft catalog and must be manually reviewed.
- `reference_graph.json` is generated and may not exist until the graph builder is run.
- `gem_categories.csv` is a snapshot for GeM categorization; it is not the same thing as the live government site.
- `ocr_cache/` is a generated cache, not a data source.
- `chroma_db/` is a generated index, not a committed file in Git. The code is designed to use it from disk.

## 7. Recent changes and groupings

The repository is clearly in a branch named `rag`, and recent commits show an active and evolving project. The last few commits from the current local git log are grouped into meaningful feature arcs:

### Feature arc: split the public API and index from the BIS collector data boundary

The newest commit `fe4ca2a` (HEAD -> rag, origin/rag) moves the BIS change detector from the previous in-repo path into `collectors/bis` and clearly introduces the data-boundary concept described in `data/README.md`. It makes the repository read as a proper two-half system: collectors write into `data/`, and the RAG engine reads the data boundary rather than depending on the collector’s immediate availability. The commit also symbolizes an architecture shift toward a clean separation between generated artifacts and code.

### Feature arc: recommendation, upload flow, evaluation, graph, and GeM integration

The `0730990` commit adds document upload support; evaluation harness support; the reference graph builder; API key support and security patterns; and the GeM catalogue integration. This is the release that moves the project from a bare retrieval/LLM prototype to a serviceable end-user demo with a document ingest path and a structured route model. It also introduces the core recommendation `response_model` pattern used by the frontend and API.

### Feature arc: UI evidence and disambiguation

The `d8aaec8` commit adds the frontend build setup, surfaces evidence in the UI, and cleans up the clarification label shape. It aligns an existing frontend file with the backend `RecommendResponse` object and supports the visual rendering of evidence across the `sources` and `questions` fields. It also improves UI clarity by making the different answer states visible in the user interface.

### Feature arc: generated data cleanup and repository hygiene

The `3dfd59b` commit removes generated scraper downloads and the local ingestion manifest from version control. This is a consistency and hygiene improvement: it acknowledges that generated artifacts should be local cache or index data and not treated as source code.

### Feature arc: retrieval correctness, OCR, catalog, and honest recommendation safeguards

The `00a9596` commit fixes the RAG pipeline around OCR ingestion, standards catalog mapping, security, and recommendation API. It gives the repository the `errors where missing fields are exposed as honest model fields` pattern, not a silent fake output. It is the first patch that makes the recommendation route behave more realistically around document ingestion and Chroma integration.

### Feature arc: initial prototype

The `c54ab5a` commit introduces the initial prototype for the backend, hybrid retrieval, frontend, and project documentation. It documents that the project was born around a backend recommendation API, retrieval stack, and an initial web UI rather than the later BIS collector separation. It also represents the base architecture from which the later patches diverged.

## 8. Pending and unverified work

The repository contains many implemented artifacts that are present but not verified here in the workspace. The following commands should be treated as the expected verification commands for a cold handoff. They are commands the AI being handed off would need to run from a clean terminal with the correct environment.

### Verify backend startup

Command:

```sh
cd rag
python -m backend.main
```

Expected purpose: starts a FastAPI endpoint for the recommendation and document upload system. It requires the backend environment to be configured with a valid `backend/.env` and, if the system is expected to answer recommendations, `GROQ_API_KEY` in the runtime environment.

### Verify backend indexing and ingestion

Command:

```sh
cd rag
python -m backend.rag_engine --rebuild
```

Expected purpose: rebuilds the local Chroma vector store from `DATA_DIR` and replays the index. This is the most central component of the retrieval system. It must be run whenever the corpus changes or if the vector store is removed. It writes `processed_files.json` and `ingestion_report.json` alongside the vector store.

### Verify reference graph generation

Command:

```sh
cd rag
python -m backend.build_reference_graph
```

Expected purpose: writes `reference_graph.json` by walking the local corpus and parsing outgoing citations. This should be run before the reference chain endpoint will return live graph information. It consumes the extracted document text and writes graph edges to `reference_graph.json`.

### Verify catalog generation

Command:

```sh
cd rag
python -m backend.build_catalog
```

Expected purpose: writes or updates the standards catalog used by the retrieval engine to map file names into standard IDs and titles. It is a draft and must be verified by a human reviewer before being accepted as final truth.

### Verify frontend build

Command:

```sh
cd rag/frontend
npm install
npm run build
```

Expected purpose: ensures the React + Vite frontend compiles successfully and that the UI adapts to the route contract in the API. Build success will prove that the packaged frontend remains compatible with the installed frontend dependency versions in `package.json`.

### Verify BIS collector specific commands

Commands:

```sh
cd collectors/bis
python -m bis_change_detector.change_detector
python -m bis_change_detector.scheduler
```

Expected purpose: exercises the BIS monitoring loop and ongoing scheduled cycle. The scheduler is the long-running command; a one-shot change detector invocation emits standard metadata and writes it to the SQLite `standards` table. It must be run in the environment with `DATABASE_URL=sqlite:///./bis_monitor.db` or its default path.

The repository has a `PROJECT_CONTEXT.md` and a `README.md` in the BIS subfolder that explain the workflow. The database should not be assumed safe to connect to from a cold environment until the environment variables and dependency stack are installed.

## 9. Current branch and remote

The repository’s active git branch is `rag`. The workspace is on `HEAD -> rag` and the remote configured as `origin` points to `https://github.com/ShantanuSomwanshi/SIH-PRISM.git`. The remote branch `origin/rag` exists and the local branch is currently named `rag`. The documentation in this repository intentionally notes that `rag` is the active branch on the GitHub repository `github.com/ShantanuSomwanshi/SIH-PRISM` and that the project is developed as a retrieval, API, and frontend engine branch rather than a collector branch.

## Final operating summary

At the current point in the repository, the backend and engine are substantially implemented. The core modules `main.py`, `retriever.py`, `recommend.py`, `catalog.py`, `build_catalog.py`, `build_reference_graph.py`, `document.py`, `pdf_extract.py`, `rag_engine.py`, and `tender.py` represent a functioning retrieval recommendation architecture and support the reference graph, GeM category suggestion, and tender-draft subdomains. Separately, the BIS collector is implemented in `collectors/bis/bis_change_detector`, including a SQLite database and a wrapper that feeds new or changed standards from a discovered artifact path.

The broad weakness is not that the code is missing. It is that the data contract between the collector and RAG engine is intentionally not yet complete. The `recommendation` stack is stable and designed to say “not determined” or “not currently verifiable” rather than invent a fact. That is the correct behavior for a project that wants to avoid hallucinating certifications or the live state of publications. The working handoff goal is to avoid assuming that any of the generated JSON or metadata fields are authoritative; use the graph, catalog, metadata model, and user-facing phrasing to keep the system honest until the BIS collector and the source-of-truth data boundary are fully connected.
