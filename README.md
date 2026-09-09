# PRISM: Indian Standards Recommendation Engine

An AI-powered system that helps procurement officials identify the most relevant Indian Standards for product descriptions and tender specifications.

## Problem

Procurement officials often struggle to identify correct Indian Standards when preparing tender specifications. With thousands of published standards, overlapping scopes, frequent revisions, and complex normative references, specifications frequently:

- Omit relevant standards
- Reference outdated versions  
- Include incomplete technical requirements
- Lack proper supporting documents

This leads to ambiguity, reduced product quality, and procurement disputes.

## Solution

PRISM is a **Retrieval-Augmented Generation (RAG)** system that:

1. **Analyzes** your product description or technical specification
2. **Recommends** the most relevant Indian Standard(s)
3. **Identifies** allied standards (normative references, test methods, terminology, safety, installation)
4. **Highlights** current editions, amendments, and revision status
5. **Suggests** applicable certification requirements (BIS Product Certification, CRS, Hallmarking)
6. **Provides** page-level citations for every recommendation

## Project Architecture

PRISM consists of two main components:

### 1. **RAG System** (`/rag`)
Intelligent document retrieval and recommendation engine.

- **FastAPI backend** with hybrid retrieval (vector + BM25)
- **Local Chroma vector store** using Hugging Face embeddings
- **Cross-encoder reranking** for precision ranking
- **React frontend** for interactive recommendations
- **LLM integration** (Groq) for structured outputs

**Status**: Core RAG pipeline operational, ready for production standards corpus

📖 [Read RAG Documentation](rag/PIPELINE.md)

### 2. **BIS Change Detector** (`/scraper`)
Continuous monitoring system for Indian Standards updates.

- Tracks the [BIS Revised Standards](https://standards.bis.gov.in/website/revised-standards) page
- Detects new and modified standards
- Extracts metadata from PDF and Excel artifacts
- Stores change history in SQLite
- No Docker or PostgreSQL required

**Status**: Change detection working; awaiting integration with RAG pipeline

📖 [Read Scraper Documentation](scraper/README.md)

## Quick Start

### Prerequisites
- Python 3.8+
- Node.js 16+ (for frontend)
- Git

### Installation

#### Backend Setup
```bash
cd rag
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

#### Frontend Setup
```bash
cd rag/frontend
npm install
npm run dev
```

#### Scraper Setup
```bash
cd scraper
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

### Running the System

**Start RAG Backend:**
```bash
cd rag
.\.venv\Scripts\python.exe -m backend.main
```

**Start Frontend:**
```bash
cd rag/frontend
npm run dev
```

**Run Change Detector (one cycle):**
```bash
cd scraper
.\.venv\Scripts\python.exe -m bis_change_detector.change_detector
```

**Run Change Detector (continuous monitoring):**
```bash
cd scraper
.\.venv\Scripts\python.exe -m bis_change_detector.scheduler
```

## Features

### Current Capabilities ✅
- Document ingestion with OCR support for scanned PDFs
- Hybrid retrieval combining vector similarity and BM25
- Reciprocal Rank Fusion (RRF) for result fusion
- Cross-encoder reranking for precision
- REST API for recommendations
- Interactive React-based frontend
- SQLite-based change detection and monitoring
- Automatic schema setup and state persistence

### Roadmap 🚀
- [ ] Live standards revision status integration
- [ ] Deterministic normative reference graph
- [ ] Certification requirements database
- [ ] Multilingual support
- [ ] Automated evaluation tests
- [ ] Production standards corpus deployment
- [ ] API rate limiting and authentication

## Project Structure

```
SIH-PRISM/
├── README.md                 # This file
├── rag/                      # RAG system
│   ├── PIPELINE.md          # Architecture and design
│   ├── COMMIT_MESSAGES.md   # Development history
│   ├── backend/             # FastAPI server
│   │   ├── main.py
│   │   ├── rag_engine.py
│   │   ├── embeddings.py
│   │   ├── retriever.py
│   │   └── ...
│   └── frontend/            # React UI
│       ├── src/
│       ├── package.json
│       └── vite.config.js
└── scraper/                 # Change detection system
    ├── README.md           # Setup and usage
    ├── PROJECT_CONTEXT.md  # Detailed context
    ├── bis_change_detector/
    │   ├── change_detector.py
    │   ├── scheduler.py
    │   ├── db.py
    │   └── ...
    ├── sql/
    │   └── schema.sql
    └── downloads/          # Downloaded standards
```

## Technologies

- **Backend**: Python, FastAPI, LangChain, Groq
- **Frontend**: React, Tailwind CSS, Vite
- **Embeddings**: Hugging Face transformers
- **Vector Store**: Chroma
- **Ranking**: Cross-encoders, BM25, RRF
- **Monitoring**: SQLite, APScheduler
- **Web Scraping**: Selenium (legacy), HTTP requests (current)

## Documentation

- [RAG Pipeline Architecture](rag/PIPELINE.md) - Detailed system design
- [BIS Change Detector Guide](scraper/README.md) - Setup and monitoring
- [Project Context](scraper/PROJECT_CONTEXT.md) - Full problem statement
- [Development Commits](rag/COMMIT_MESSAGES.md) - Development history

## API Endpoints

### Health Check
```bash
GET /api/health
```

### Document Ingestion
```bash
POST /api/ingest
Content-Type: multipart/form-data
Body: [PDF files]
```

### Recommendation
```bash
POST /api/recommend
Content-Type: application/json
Body: {
  "query": "Product description or specification"
}
```

## Environment Variables

Create `.env` files in both `rag/` and `scraper/` directories:

```env
# rag/.env
GROQ_API_KEY=your_groq_api_key_here
HUGGINGFACE_API_KEY=your_hf_api_key_here

# scraper/.env
# Configure BIS scraper settings as needed
```

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

[Add your license here]

## Contact & Support

For questions or issues:
- 📧 Email: [project email]
- 💬 GitHub Issues: [Link to issues]
- 📋 Project Board: [Link to board if available]

---

**Last Updated**: September 2026
