import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document

app = FastAPI(title="PRISM RAG Pipeline Prototype")

# Initialize Embeddings (bge-m3 for multilingual support without API keys)
# Note: The first run will download the model weights (~2.2GB)
embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

# Initialize Chroma vector store pointing directly to your local folder
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
vector_store = Chroma(
    collection_name="prism_standards",
    embedding_function=embeddings,
    persist_directory=CHROMA_PATH
)

# Pydantic model for our ingestion payload
class DocumentIngest(BaseModel):
    id: str
    content: str
    metadata: Optional[dict] = {}

@app.post("/ingest")
async def ingest_documents(docs: List[DocumentIngest]):
    """
    Ingest a list of standard documents, embed them, and store them locally in Chroma.
    """
    try:
        langchain_docs = [
            Document(page_content=doc.content, metadata=doc.metadata) for doc in docs
        ]
        ids = [doc.id for doc in docs]
        
        # Chroma handles the embedding and saving to the chroma_db folder
        vector_store.add_documents(documents=langchain_docs, ids=ids)
        
        return {
            "status": "success", 
            "message": f"Successfully ingested {len(docs)} documents into local Chroma DB."
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def health_check():
    return {"status": "PRISM API is running without Docker!"}