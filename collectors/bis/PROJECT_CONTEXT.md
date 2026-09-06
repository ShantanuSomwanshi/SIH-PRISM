# BIS Change Detector (SQLite) - Project Context

## Document Status

This is a draft project-context document for the `bis_change_detector_sqlite` component.

The component is a supporting part of a larger Indian Standards recommendation project. The larger project uses a retrieval-augmented generation (RAG) pipeline to return information about relevant Indian Standards. This repository is not the main RAG application.

## 1. Relationship to the Main Project

The main problem is to help procurement officials identify the most relevant Indian Standard(s) for a product description, technical specification, or tender document. The larger system is expected to:

- Understand product and technical language semantically.
- Recommend relevant Indian Standards.
- Identify allied standards, including normative references, test methods, terminology, safety, installation, and related product standards.
- Highlight current editions, revisions, and amendments.
- Suggest applicable certification requirements such as BIS Product Certification, CRS, or Hallmarking.
- Support multilingual input and natural-language queries.

This repository supports that system by monitoring a BIS standards source, detecting changes, downloading changed standard artifacts, extracting basic metadata, and preserving change history. Its likely downstream role is to provide fresh and traceable source data for indexing, validation, or re-indexing in the main RAG pipeline.

It does not currently implement the recommendation engine, vector search, RAG orchestration, multilingual processing, or certification reasoning.

## 2. Problem Statement (Full Reference)

Government departments, Public Sector Enterprises (PSEs), procurement agencies, and private organizations procure a wide range of products and services through e-procurement portals. Procurement officials are often required to prepare technical specifications that reference the appropriate Indian Standards (IS). However, identifying the correct standard(s) is challenging due to the large number of published standards, overlapping scopes, frequent revisions, and the need to consider associated or normative reference standards. Consequently, tender specifications may omit relevant standards, reference outdated versions, or include incomplete technical requirements, leading to ambiguity, reduced product quality, and procurement disputes.

An intelligent system is required that can automatically analyze a product description or technical specification and recommend the most relevant Indian Standard(s), along with allied, cross-referenced, or normative standards that should also be considered.

### Description

Develop an AI-powered recommendation engine that integrates with procurement portals and assists procurement officials in identifying the most relevant Indian Standards and related standards while preparing tender specifications.

### Expected Features

- Accept product descriptions, technical specifications, or tender documents as input.
- Recommend the most relevant Indian Standard(s) based on semantic understanding rather than keyword matching.
- Identify allied standards, including normative references, test methods, terminology standards, safety standards, installation standards, and related product standards.
- Highlight the latest published version and amendments of the recommended standards.
- Suggest mandatory certification requirements, where applicable, such as BIS Product Certification, CRS, or Hallmarking.
- Support multilingual input and natural-language queries.

## 3. What This Project Does

The project runs a recurring change-detection cycle for a configured BIS page and associated scraper:

1. Fetch the configured monitored page.
2. Remove common dynamic or non-content HTML elements and normalize the remaining HTML.
3. Calculate a SHA-256 page fingerprint.
4. Stop early when the page fingerprint is unchanged.
5. If the page changed, discover visible Indian Standard IDs and fingerprints for their page rows.
6. Select only new standards or standards whose discovered row changed.
7. Invoke the existing legacy scraper for the selected IDs.
8. Parse downloaded PDF and Excel artifacts into structured records.
9. Calculate a metadata fingerprint for each parsed standard.
10. Store standards, crawl runs, state, and standard-level deltas in SQLite.
11. Mark standards as `WITHDRAWN` only when discovery appears complete and the available evidence supports that conclusion.

The design reduces unnecessary scraper calls and avoids reprocessing all historical downloads on every cycle.

## 4. Current Capabilities

### Monitoring and change detection

- Configurable monitored URL.
- Tier 1 page-level SHA-256 fingerprint.
- Tier 2 standard-row fingerprints discovered from the page.
- Dynamic-content cleanup for scripts, styles, iframes, selected attributes, and common token/timestamp text.
- File locking to prevent overlapping crawl cycles.
- Retry handling for one-shot execution.
- Scheduled execution in UTC with APScheduler.

### Standard discovery

- Detects IDs matching common `IS <number>` patterns, with optional parenthetical parts, years, and suffixes.
- Primarily scans table rows.
- Falls back to scanning all visible page text when no rows produce IDs.
- Avoids treating paginated results as a complete set for withdrawal inference.

### Legacy scraper integration

- Reuses `legacy_scraper/download_standards.py` without modifying it.
- Creates a temporary `Book 2.xlsx` containing only selected IDs.
- Runs the scraper in an isolated temporary working directory.
- Captures scraper output and errors in logs.
- Copies resulting artifacts to the configured downloads directory before temporary files are removed.

### Artifact parsing

- Parses PDF text with `pypdf`.
- Parses `.xlsx` and `.xlsm` files with `openpyxl`.
- Extracts or preserves these fields where available:
  - `standard_id`
  - `title`
  - `status`
  - `last_amendment_date`
  - `publication_date`
  - `edition`
  - `scope`
  - `source_artifact`
  - `raw_text_excerpt`
  - `extraction_warnings`
- Records warnings when an IS number or title cannot be confidently extracted.

### Planned enrichment within this component's scope

The intended scope of this component includes extracting references found in downloaded standards, including normative references, test methods, safety standards, terminology standards, installation standards, and related product standards. This is a planned capability and is not implemented by the current parser. It should produce traceable standard-to-standard relationships for downstream indexing.

### Persistence and auditability

SQLite is initialized automatically. The current data model stores:

- Monitor state such as the last page fingerprint and last check time.
- Crawl runs, statuses, messages, and processed counts.
- Current standard metadata and active/withdrawn state.
- Standard-level change records with old and new fingerprints and statuses.
- Source artifact paths and raw text excerpts for traceability.

## 5. What This Project Cannot Do

The current implementation does not:

- Accept a procurement user's product description, tender document, or natural-language query as an application input.
- Recommend standards based on semantic similarity.
- Generate embeddings or maintain a vector database.
- Implement retrieval, reranking, prompting, citation generation, or answer generation.
- Currently extract normative references or allied standards from the contents of a standard. Reference extraction is an intended future capability of this component.
- Build a standards-reference graph.
- Determine whether a certification requirement applies to a product or tender.
- Guarantee that a standard is the legally or operationally correct choice for a procurement.
- Provide multilingual translation or multilingual semantic search.
- Reliably parse every BIS artifact layout, scanned PDF, image-only PDF, table, amendment, or web format.
- Use OCR for scanned documents.
- Guarantee that a page-level change represents a standards-data change.
- Discover standards hidden behind JavaScript rendering, authentication, unsupported navigation, or a changed website layout.
- Infer withdrawals from incomplete, paginated, or unreliable discovery results.
- Verify the legal validity or current authority of extracted metadata independently.
- Provide a production API, user interface, authentication, authorization, or portal integration.
- Replace review by a BIS or procurement-domain expert.

## 6. End-to-End Architecture

```text
Configured BIS page
        |
        v
page_hasher.py: fetch, normalize, page SHA-256
        |
        v
change_detector.py: decide whether Tier 2 is needed
        |
        v
discovery.py: find standard IDs and row fingerprints
        |
        v
scraper_adapter.py: temporary workbook + legacy scraper
        |
        v
downloads/: copied PDF/XLSX artifacts
        |
        v
artifact_parser.py: structured metadata extraction
        |
        v
fingerprint.py: standard metadata SHA-256
        |
        v
SQLite: standards, crawl_runs, monitor_state, standard_delta_log
        |
        v
Downstream handoff to the main RAG indexing/retrieval project
```

### Main modules

- `bis_change_detector/change_detector.py`: coordinates one crawl cycle and retry-aware command-line execution.
- `bis_change_detector/scheduler.py`: runs the detector immediately and then at a configured interval.
- `bis_change_detector/config.py`: loads environment-backed settings and resolves paths relative to the repository root.
- `bis_change_detector/page_hasher.py`: fetches and normalizes the monitored page.
- `bis_change_detector/discovery.py`: discovers standard IDs and page-row fingerprints.
- `bis_change_detector/scraper_adapter.py`: invokes the unchanged legacy scraper in isolation.
- `bis_change_detector/artifact_parser.py`: extracts records from PDF and Excel artifacts.
- `bis_change_detector/fingerprint.py`: calculates the exact standard metadata fingerprint.
- `bis_change_detector/db.py`: owns SQLite initialization and persistence.
- `bis_change_detector/logging_config.py`: configures file/console logging.
- `legacy_scraper/download_standards.py`: existing scraper dependency kept outside the detector logic.
- `sql/schema.sql`: documents the schema; the application creates the schema automatically.

## 7. Fingerprinting Rules

### Page fingerprint

The monitored HTML is normalized after removing selected scripts, styles, noscript elements, iframes, dynamic attributes, and selected dynamic text. The normalized content is hashed with SHA-256.

If this fingerprint is unchanged, the cycle returns `NO_CHANGE` and does not invoke the scraper.

### Page-row fingerprint

Each discovered visible row is whitespace-normalized and hashed with SHA-256. A changed row causes that standard ID to be selected for scraping.

### Standard metadata fingerprint

The standard fingerprint is exactly:

```text
SHA-256(Standard_ID + Title + Status + Last_Amendment_Date)
```

No separators are currently added between these values. This fingerprint is used to record metadata updates.

## 8. Runtime and Configuration

### Dependencies

The project currently depends on Python packages listed in `requirements.txt`, including Requests, Beautiful Soup, FileLock, OpenPyXL, pandas, pypdf, Selenium, python-dotenv, and APScheduler.

### Required environment variables

- `MONITORED_URL`
- `SCRAPER_SCRIPT`

### Important optional environment variables

- `DATABASE_URL` (SQLite URL; defaults to `sqlite:///./bis_monitor.db`)
- `SCRAPER_CWD`
- `SCRAPER_INPUT_FILE`
- `SCRAPER_OUTPUT_DIR`
- `STATE_DIR`
- `LOG_DIR`
- `LOCK_FILE`
- `CHECK_INTERVAL_HOURS`
- `REQUEST_TIMEOUT_SECONDS`
- `SCRAPER_TIMEOUT_SECONDS`
- `RETRIES`
- `RETRY_BASE_SECONDS`
- `DISCOVERY_ENABLED`

Relative paths are resolved from the repository root.

### Commands on Windows PowerShell

Create the environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run one crawl cycle:

```powershell
.\.venv\Scripts\python.exe -m bis_change_detector.change_detector
```

Run continuously:

```powershell
.\.venv\Scripts\python.exe -m bis_change_detector.scheduler
```

The batch files `run_once.bat` and `run_scheduler.bat` provide equivalent shortcuts after the virtual environment exists.

### Selenium and browser prerequisites

The legacy scraper uses Selenium, so a crawl that reaches the scraper stage requires:

- A supported Python installation and the project virtual environment.
- Selenium installed from `requirements.txt`.
- A browser supported by the legacy scraper, such as the browser configured in that scraper.
- A compatible browser driver or Selenium Manager configuration available to Selenium.
- Network access to the BIS pages and downloads requested by the scraper.
- Permission for the process to create temporary folders, write to `downloads/`, and write logs and the SQLite database.

The detector itself fetches the monitored page with Requests. Selenium is used by the existing legacy scraper only when new or changed standards need to be downloaded. Browser-driver setup details may vary with the scraper implementation and should be verified in `legacy_scraper/download_standards.py`.

## 9. Repository Directories and Generated Data

- `bis_change_detector/`: detector application code.
- `legacy_scraper/`: existing scraper and its working downloads area.
- `downloads/`: copied artifacts produced by successful scraper runs.
- `input/`: optional input files or seed data.
- `logs/`: application and scraper logs.
- `state/`: lock and state files.
- `sql/`: schema documentation.
- `.env`: local configuration; it should not be committed if it contains deployment-specific values.
- SQLite database: created at the configured database path.

## 10. Important Operational Assumptions

- The monitored page is reachable with an HTTP GET and does not require browser-only rendering for the relevant content.
- The legacy scraper can run with the generated `Book 2.xlsx` and its required Selenium/browser setup.
- Downloaded artifacts have sufficient extractable text or supported workbook structure.
- A page that appears complete is actually complete before withdrawal inference is enabled.
- The BIS website layout and ID format remain compatible with the discovery expressions.
- The downstream RAG system will define its own indexing, chunking, embedding, retrieval, and citation policies.

## 11. Suggested Handoff to the Main RAG Project

A downstream integration should consume records and deltas rather than scrape the BIS site again. At minimum, the handoff should preserve:

- Standard ID and title.
- Scope and extracted text.
- Publication date, edition, amendment date, and status.
- Whether the record is active or withdrawn.
- Source artifact path or a durable artifact identifier.
- Extraction warnings and crawl/run metadata.
- Change type and old/new fingerprints where incremental indexing is required.
- Extracted standard-to-standard references, when the planned reference-extraction capability is implemented.

The main RAG project should treat this data as source evidence, validate freshness, and expose citations or provenance to users. It should not assume that a successfully parsed record is automatically a recommendation or a certification decision. BIS certification, CRS, and Hallmarking analysis remains in the main RAG project and is explicitly outside this component's scope.

## 12. Operations and Quality Controls

### Troubleshooting

- `Missing required environment variables`: set `MONITORED_URL` and `SCRAPER_SCRIPT` in `.env` or the process environment.
- `Could not discover standard IDs`: verify the monitored URL, page layout, discovery mode, and optional `Book 2.xlsx` fallback.
- Scraper timeout or non-zero exit: inspect the scraper logs, browser availability, driver compatibility, network access, and temporary-directory permissions.
- Empty or incomplete parsed records: inspect the source artifact and `extraction_warnings`; image-only PDFs require OCR, which is not currently implemented.
- Unexpected withdrawal records: verify that the monitored page is complete and not paginated. The detector is designed not to infer withdrawals from incomplete discovery.
- Repeated `NO_CHANGE`: confirm that the monitored URL and page content are correct, and inspect the stored page fingerprint and logs.

Failed scheduled cycles are logged while the scheduler remains alive. A one-shot run retries according to `RETRIES` and `RETRY_BASE_SECONDS`.

### Testing expectations

The repository currently has no dedicated test suite documented in this component. Before production use, tests should cover page normalization, standard-ID discovery, pagination detection, fingerprint stability, PDF/XLSX parsing, scraper failure handling, withdrawal safeguards, SQLite persistence, and restart behavior.

### Backup and recovery

The SQLite database, downloaded artifacts, logs, and state directory should be backed up according to the operating environment's retention policy. A recoverable backup should include the database and the source artifacts referenced by `source_artifact`; backing up only SQLite may lose the evidence needed to reproduce or audit a record. Before restoring or moving the component, preserve the configured paths and verify that the database opens and the scraper can still access its browser prerequisites.

### Data-quality checks

Downstream consumers should check standard ID presence, title quality, status values, date consistency, active/withdrawn state, source-artifact existence, extraction warnings, and crawl freshness. Records with parser warnings should be traceable and should not silently be treated as authoritative. A human or authoritative BIS source review remains appropriate for high-impact procurement decisions.

## 13. Open Questions for This Draft

Please confirm which choices belong in the final version of this document:

The following decisions are recorded from the current review:

- Filename: keep `PROJECT_CONTEXT.md`.
- Problem statement: include the full reference version in this document.
- Selenium/browser setup: include prerequisites, but do not add deployment instructions.
- Operations and quality: include troubleshooting, testing expectations, backup/recovery, and data-quality checks.
- Reference extraction: this component should eventually extract normative and allied standard relationships, but the current implementation does not yet do so.
- Certification analysis: BIS Product Certification, CRS, and Hallmarking remain in the main RAG project.

The remaining questions are:

1. What is the intended downstream interface to the RAG project: direct SQLite reads, exported JSON/JSONL files, an API, a message queue, or another method? This determines how the main RAG system receives new, updated, and withdrawn standards without duplicating the scraper.
2. Which fields are mandatory for RAG indexing, and which fields should be treated as optional or untrusted extraction results?
3. Should raw artifacts and raw text excerpts be retained indefinitely, versioned, or deleted after indexing?
4. Which BIS sources are officially in scope, and are there known pages, file formats, or languages that must be supported?
5. Are there compliance, licensing, access-control, or rate-limit requirements that should be recorded?
6. Are monitoring metrics or alerting requirements needed in addition to the operational sections above?

## 14. Scope Statement

This repository should be understood as a change-aware BIS standards acquisition, metadata persistence, and planned reference-extraction component. It keeps a local SQLite representation of standards current enough for downstream processing and is intended to preserve relationships to normative, test, safety, terminology, installation, and related product standards. It is one part of the larger procurement-assistance solution and should not be described as the complete intelligent recommendation engine. Certification analysis remains outside this component and belongs to the main RAG project.
