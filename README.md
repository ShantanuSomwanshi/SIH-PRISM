# PRISM: Indian Standards Recommendation Engine

PRISM is an AI-powered procurement intelligence platform designed to help teams identify the most relevant Indian Standards for technical specifications, tender documents, and compliance review.

It combines a standards recommendation workflow with a BIS monitoring pipeline so users can not only find suitable standards, but also stay aware of revisions, updates, and lifecycle changes.

## Why PRISM

Procurement and engineering teams often struggle with:

- fragmented standards information
- outdated or superseded references
- incomplete product specification coverage
- difficulty identifying related compliance standards

PRISM addresses this by using retrieval-based AI and standards monitoring together to surface useful, context-aware recommendations with supporting references.

## Core Modules

### 1. RAG recommendation engine
The `rag/` directory contains the recommendation and retrieval stack.

Features include:

- hybrid retrieval using vector and lexical signals
- document ingestion for technical files and standards-related material
- recommendation responses grounded in project documents
- React-based frontend for exploration and review
- LLM-assisted structured output generation

### 2. BIS lifecycle monitoring
The `scraper/` directory contains the BIS tracking and change-detection workflow.

Features include:

- monitoring updates on BIS standard pages
- detecting revision and lifecycle changes
- extracting metadata from artifacts and PDFs
- storing update state in SQLite
- enabling scheduled monitoring runs

## Repository Structure

```text
SIH-PRISM/
├── README.md
├── .gitignore
├── rag/
│   ├── backend/
│   ├── frontend/
│   ├── PIPELINE.md
│   ├── COMMIT_MESSAGES.md
│   └── requirements.txt
├── scraper/
│   ├── bis_change_detector/
│   ├── sql/
│   ├── downloads/
│   ├── logs/
│   ├── selected_standards/
│   ├── README.md
│   └── PROJECT_CONTEXT.md
├── collector/
│   └── bis/
└── docs and project reports
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Git

### RAG setup

```bash
cd rag
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

### Frontend setup

```bash
cd rag/frontend
npm install
npm run dev
```

### Scraper setup

```bash
cd scraper
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

### Run the services

```bash
# Start backend
cd rag
.\.venv\Scripts\python.exe -m backend.main

# Start frontend
cd rag/frontend
npm run dev

# Run scraper once
cd scraper
.\.venv\Scripts\python.exe -m bis_change_detector.change_detector
```

## Current Capabilities

- AI-assisted recommendation for standards and technical references
- retrieval over project documents and standards-related sources
- hybrid ranking for improved precision and recall
- support for scanned and document-based ingestion workflows
- BIS update detection and lifecycle monitoring
- SQLite-backed tracking for state and metadata
- extensible architecture for future compliance tools

## Documentation

- [RAG pipeline notes](rag/PIPELINE.md)
- [Scraper guide](scraper/README.md)
- [Project context](scraper/PROJECT_CONTEXT.md)
- [Commit history notes](rag/COMMIT_MESSAGES.md)

## Tech Stack

- Python
- FastAPI
- React + Vite
- Tailwind CSS
- Chroma vector store
- Hugging Face embeddings
- SQLite
- APScheduler

## Roadmap

- deeper live BIS revision tracking
- stronger normative reference graph analysis
- certification and compliance mapping
- improved evaluation and retrieval tuning
- deployment-ready production packaging

## Contributing

Contributions are welcome. Please create a feature branch and submit a clean pull request for review.

## License

This repository is intended for research, prototyping, and applied standards intelligence workflows. Please review local legal or institutional policies before production deployment.

## Notes

PRISM brings together two complementary workflows:

1. recommendation and retrieval for standards intelligence
2. lifecycle monitoring for BIS changes and updates

Together, these workflows support a practical standards compliance and tender-preparation workflow for real-world procurement scenarios.
