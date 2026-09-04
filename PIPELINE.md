# PRISM Prototype Pipeline

PRISM is a standards-focused RAG prototype: PDFs are indexed locally, a query is retrieved with both semantic and keyword search, and an LLM is intended to turn the retrieved context into a procurement recommendation.

## Project context

### Problem and purpose

Government departments, public sector enterprises, procurement agencies, and private organizations prepare tender specifications that often need to reference the correct Indian Standards (IS). Finding the right standards is difficult because there are many published standards, overlapping scopes, frequent revisions, and associated or normative references. Missing standards, outdated versions, or incomplete requirements can create ambiguity, reduce product quality, and lead to procurement disputes.

PRISM is intended to be an AI-assisted recommendation engine that can integrate with procurement portals. Given a product description, technical specification, or tender document, it should recommend the most relevant Indian Standard(s) and identify allied standards such as normative references, test methods, terminology, safety, installation, and related product standards. It should also surface the latest version and amendments, applicable certification requirements such as BIS Product Certification, CRS, or Hallmarking, and support multilingual natural-language input.

### Expected end-to-end workflow

1. A procurement official enters a product description, technical specification, or tender text in the web interface.
2. The backend retrieves relevant chunks from the locally indexed BIS/Indian Standards corpus.
3. Retrieval results are reranked and supplied to an LLM as the evidence context.
4. The system returns a grounded recommendation with a primary standard, allied standards, version status, certification information, confidence, and source references.
5. When the input is ambiguous, the system asks for clarification before making a recommendation.

### Repository map

- `backend/rag_engine.py` ingests PDFs from `backend/data/` into the local Chroma database.
- `backend/retriever.py` implements hybrid retrieval, reranking, and the standalone terminal Q&A flow.
- `backend/main.py` contains the FastAPI service and currently implements health and document-ingestion routes.
- `backend/chroma_db/` contains the local Chroma persistence directory and should be treated as generated data.
- `backend/processed_files.json` tracks PDFs already processed by the ingestion script.
- `frontend/src/App.jsx` contains the React prototype for submitting queries and rendering clarification or recommendation responses.
- `frontend/` contains the web client configuration; its `package.json` is currently empty, so frontend installation/startup metadata still needs to be completed.

### Development conventions and constraints

- Keep the standards corpus grounded: recommendations must be based on retrieved source chunks, and unsupported claims should be reported as unknown rather than invented.
- Preserve source metadata and standard identifiers through ingestion, retrieval, reranking, and API serialization so answers can be audited.
- Keep ingestion repeatable. Do not reprocess files already listed in `backend/processed_files.json` unless intentionally rebuilding the index.
- Use the existing local Chroma collection `prism_standards` and embedding model `BAAI/bge-m3` unless a change explicitly includes migration or reindexing work.
- Keep secrets such as `GROQ_API_KEY` in `backend/.env`; do not commit credentials.
- Changes that connect the UI to the backend must keep the frontend request and response schema aligned with the FastAPI route.

### Current priorities and known limitations

The highest-priority integration work is to add `POST /api/recommend` to `backend/main.py`, connect it to `PrismHybridRetriever`, invoke the Groq generation chain, and return the response shape expected by `frontend/src/App.jsx`. The current browser UI cannot complete a recommendation because that route is absent.

Other prototype limitations include incomplete frontend package configuration, no visible CORS configuration in the FastAPI app, local-only Chroma storage, no automated test suite, and no implemented workflow yet for checking the latest standard versions, amendments, or certification rules. These should be treated as planned capabilities rather than claims that the current prototype already satisfies.

### Verified local setup

Backend dependencies are listed in `backend/requirements.txt`. The embedding model and cross-encoder download model weights on first use, so the first ingestion or retrieval run may be slow and require substantial disk space. The terminal Q&A path also requires `GROQ_API_KEY` in `backend/.env`.

From the repository root, the intended backend commands are:

```text
pip install -r backend/requirements.txt
python backend/rag_engine.py
python backend/retriever.py
uvicorn backend.main:app --reload
```

The frontend startup command is not yet documented because `frontend/package.json` is empty and the client dependency/tooling setup is incomplete.

## 1. Source documents and ingestion

1. Place BIS/Indian Standards PDFs in `backend/data/`.
2. Run `backend/rag_engine.py`.
3. The ingestion engine:
   - reads only `.pdf` files not listed in `backend/processed_files.json`;
   - extracts page text with `PDFPlumberLoader`;
   - splits text into 1,000-character chunks with 200-character overlap;
   - creates chunk IDs such as `<filename>_chunk_<number>`;
   - embeds chunks with `BAAI/bge-m3` via Hugging Face;
   - writes vectors, text, and metadata to the local Chroma collection `prism_standards` in `backend/chroma_db/`;
   - updates `processed_files.json` so already processed PDFs are skipped on later runs.

The first embedding run downloads the `bge-m3` model weights. The current manifest contains ten tracked PDF filenames.

## 2. Query and retrieval

`backend/retriever.py` loads the same embedding model and Chroma collection, then builds a BM25 index over all stored chunks. The source filename is included in the BM25 text so queries containing a standard number, such as `1001`, can match `1001.pdf`.

For each query:

1. Vector similarity search returns a candidate pool of 20 chunks.
2. BM25 keyword search returns a candidate pool of 20 chunks.
3. Reciprocal Rank Fusion combines both result lists using `1 / (60 + rank)`.
4. A cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) reranks the fused candidates.
5. The top four reranked chunks are selected.
6. Each selected chunk retains its source metadata, fusion score, and reranking score.

This hybrid approach combines meaning-based matching with exact terms and standard identifiers.

## 3. Answer generation

The standalone interactive mode in `retriever.py` formats the four chunks as a source-labeled context and sends them to Groq using `ChatGroq` with model `openai/gpt-oss-120b` and temperature `0.1`.

The prompt instructs the model to:

- answer strictly from the supplied standards context;
- say it cannot find the answer when the context is insufficient;
- cite standard names and clause/table numbers when available.

The Groq API key is loaded from `backend/.env` as `GROQ_API_KEY`. The generated answer and the source filenames/scores are printed in the terminal.

## 4. API and frontend flow

`backend/main.py` creates a FastAPI app and initializes the same local `prism_standards` Chroma collection. Its implemented routes are:

- `GET /` - health check;
- `POST /ingest` - accepts a JSON list of `{id, content, metadata}` objects, embeds them, and stores them in Chroma.

The React UI in `frontend/src/App.jsx` accepts a product description or tender specification, sends it as `{query: "..."}` to `POST http://127.0.0.1:8000/api/recommend`, and renders either clarification choices or a recommendation containing the primary standard, allied standards, version status, certification, and confidence flag.

## 5. Current integration status

The frontend recommendation route is not currently implemented in `backend/main.py`, and `main.py` does not import or call `PrismHybridRetriever` or the Groq generation chain. Therefore the PDF/Chroma pipeline and the terminal Q&A path work as separate prototype pieces, but the browser UI cannot complete a recommendation against the current FastAPI app until `/api/recommend` is added and wired to retrieval plus LLM generation.

## 6. Data flow

```text
PDFs in backend/data/
        |
        v
PDFPlumberLoader -> text chunks -> bge-m3 embeddings -> Chroma
        |                                      |
processed_files.json                           v
                                      vector search + BM25
                                                |
                                      reciprocal rank fusion
                                                |
                                      top 4 context chunks
                                                |
                                      Groq LLM recommendation
                                                |
                         terminal output / intended React API response
```
