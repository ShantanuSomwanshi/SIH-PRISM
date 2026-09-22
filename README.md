# PRISM

Procurement Recommendation for Indian Standards Matching.

PRISM is a Smart India Hackathon project that helps procurement teams identify the relevant Indian Standards for a product description or tender specification. It recommends the most relevant standard, lists allied standards, shows evidence from the source documents, and explains whether the result is still current or needs human validation.

## What the project does

- Recommends the most relevant Indian Standard(s) for a query or uploaded tender document
- Uses hybrid retrieval combining vector search and BM25 keyword search
- Surfaces allied standards and reference chains from the standards corpus
- Provides page-level evidence and citations for each recommendation
- Includes a clarification flow when the query is too vague
- Supports GeM category lookup and verification for related products
- Has a BIS collector component that tracks standards updates independently of the live API

## Architecture

The repository is intentionally split by execution timing rather than by business domain:

```text
collectors/
  bis/                  schedules and tracks BIS updates

data/                  data boundary: generated artifacts and source inputs

rag/
  backend/              FastAPI app, retrieval, recommendation, ingestion
    gem/                GeM catalogue lookup and verification helpers
  frontend/             Vite + React web interface
```

This separation keeps the live API independent from the scraper. The collector may run on a schedule or on another machine, while the retrieval layer reads from the generated data boundary rather than depending on a browser scraper being online.

See also:

- `rag/PIPELINE.md` for the retrieval and recommendation pipeline
- `collectors/bis/README.md` for the BIS change detector
- `data/README.md` for the contract between collector output and engine input

## Current status

### Working features

- OCR ingestion of scanned standards and PDFs
- Hybrid retrieval with grounded citations
- Recommendation API and document upload flow
- Reference graph generation for allied standards
- GeM catalogue support for category matching
- React frontend for requests and result display

### Important limitations

- The BIS collector is not yet connected to the main recommendation engine in real time
- Live standards status may still appear as `Unknown`
- Certification requirements remain `Not determined` unless verified elsewhere
- The project is a functional prototype and not a complete production legal/compliance system

## Tech stack

### Backend

- Python
- FastAPI
- LangChain
- ChromaDB
- Hugging Face embeddings
- BM25 keyword search
- Groq LLM integration
- PyMuPDF, pdfplumber, Tesseract OCR

### Frontend

- React
- Vite
- Tailwind CSS

### Collector

- Python
- SQLite
- Selenium-based BIS download flow
- Scheduler-based monitoring

## Repository layout

```text
README.md
PROJECT_STATUS.md
collectors/
  bis/
    README.md
    requirements.txt
    bis_change_detector/
    legacy_scraper/
    sql/

data/
  README.md
  standards/
  tenders/
  certifications/

rag/
  PIPELINE.md
  backend/
    .env.example
    requirements.txt
    main.py
    config.py
    rag_engine.py
    retriever.py
    recommend.py
    catalog.py
    references.py
    build_catalog.py
    build_reference_graph.py
    pdf_extract.py
    documents.py
    gem/
    chroma_db/
    ocr_cache/
    standards_catalog.json
    reference_graph.json
  frontend/
    package.json
    src/
    vite.config.js
```

## Prerequisites

Before running the project, install:

- Python 3.10+ or newer
- Node.js 18+
- Tesseract OCR and ensure it is available on PATH or point `TESSERACT_CMD` to the install location
- Access to a Groq API key if using the LLM-backed recommendation flow

On Windows, you can install Tesseract using:

```powershell
winget install UB-Mannheim.TesseractOCR
```

## Environment setup

### 1) Backend setup

From the project root:

```powershell
cd rag
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend\requirements.txt
copy backend\.env.example backend\.env
```

Then update `rag/backend/.env` with your values, especially:

```env
GROQ_API_KEY=your_key_here
TESSERACT_CMD=C:\path\to\tesseract.exe
```

### 2) Build the standards catalog

```powershell
cd rag
.\.venv\Scripts\activate
python -m backend.build_catalog
```

This creates or refreshes the draft `standards_catalog.json` used by the retrieval pipeline.

### 3) Ingest the standards corpus

```powershell
cd rag
.\.venv\Scripts\activate
python -m backend.rag_engine
```

Useful ingestion commands:

```powershell
python -m backend.rag_engine --prune     # remove deleted PDFs from the index
python -m backend.rag_engine --rebuild   # wipe and rebuild the index from scratch
python -m backend.rag_engine --dry-run   # preview what would be ingested
```

## Run the application

### Backend API

From the `rag` folder:

```powershell
cd rag
.\.venv\Scripts\activate
uvicorn backend.main:app --reload
```

Then open:

- API docs: http://127.0.0.1:8000/docs
- Health endpoint: http://127.0.0.1:8000/

### Frontend UI

Open a second terminal:

```powershell
cd rag\frontend
npm install
npm run dev
```

Then open the local Vite URL, usually:

- http://localhost:5173

## Optional: run the BIS collector

This part runs independently and is not required for the API to work locally.

```powershell
cd collectors\bis
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe -m bis_change_detector.change_detector
```

For continuous monitoring:

```powershell
.\.venv\Scripts\python.exe -m bis_change_detector.scheduler
```

## Typical workflow

1. Install Python dependencies for the backend
2. Configure `.env` with Groq and Tesseract values
3. Build the standards catalog
4. Ingest the data corpus
5. Start the backend API
6. Start the frontend UI
7. Submit a query or upload a tender document
8. Review the recommended standard, allied standards, sources, and tender draft

## API overview

The main live routes in the backend are:

- `GET /` - health check
- `POST /api/recommend` - recommend standards for a query
- `POST /api/recommend/upload` - recommend based on uploaded document
- `GET /api/standards/references` - view reference chain for a standard
- `POST /ingest` - protected ingestion endpoint for authorized writes

## Notes for contributors

- Keep the collector and retrieval engine independent; the collector writes to the data boundary and the engine reads from it
- Generated artifacts like `chroma_db/`, OCR cache files, and catalogs should be treated as runtime outputs rather than source code
- Keep status messages honest: if the project cannot verify currentness, it should say so instead of guessing

## License and project context

This project was developed as part of Smart India Hackathon 2026, problem statement 26108, by Team: localhost legends.

## Related docs

- `PROJECT_STATUS.md` - repository-level handoff notes and architecture details
- `rag/PIPELINE.md` - backend engine setup, ingestion, retrieval and execution flow
- `collectors/bis/README.md` - BIS collector setup and operation
- `data/README.md` - data contract between collector and engine
