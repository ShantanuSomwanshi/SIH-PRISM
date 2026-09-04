# Commit Messages

This file records the commit messages used for the PRISM prototype repository.

## `Initial PRISM RAG prototype: backend, hybrid retrieval, frontend, and project documentation`

### Commit scope

- Added the FastAPI backend prototype with health and document-ingestion endpoints.
- Added PDF ingestion into a local Chroma collection using Hugging Face embeddings.
- Added hybrid retrieval using vector similarity search, BM25 keyword search, reciprocal rank fusion, and cross-encoder reranking.
- Added the standalone terminal question-answering flow using Groq and grounded standards context.
- Added the React frontend prototype for product descriptions, tender specifications, clarification choices, and recommendation output.
- Added backend dependency metadata and the project structure documentation.
- Added `PIPELINE.md` with project purpose, workflow, architecture, setup commands, constraints, current limitations, and integration status.
- Added `.gitignore` rules to keep local secrets, the Python virtual environment, source PDF data, and the generated Chroma vector database out of Git.

### Intentionally excluded from the commit

- `backend/.env`
- `backend/data/`
- `backend/chroma_db/`
- `.venv/`