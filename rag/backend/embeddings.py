"""
One definition of the embedding model and the vector store.

Why this file exists: main.py used to import HuggingFaceEmbeddings from
langchain_community while rag_engine.py and retriever.py imported it from
langchain_huggingface. Two different wrapper classes around the same model.
If their defaults ever differ, the vectors you SEARCH with stop matching the
vectors you STORED - and the failure is silent. Search just quietly returns
nonsense.

Everything now imports from here, so they cannot drift apart.
"""

from functools import lru_cache

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from backend.config import CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    """
    The embedding model, loaded once per process.

    Cached because the model is about 2.2 GB - loading it twice wastes
    time and memory for no benefit.
    """
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def get_vector_store() -> Chroma:
    """The Chroma collection, wired to the shared embedding model."""
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
    )


def collection_size(store: Chroma) -> int:
    """
    How many chunks are stored. Cheap - it does not fetch the chunks.

    Used to notice that the index changed without reading all of it.
    """
    try:
        return store._collection.count()
    except Exception:
        return -1
