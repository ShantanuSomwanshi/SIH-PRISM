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

import os
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from backend.config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBED_BATCH_SIZE,
    EMBED_MAX_TOKENS,
    EMBED_SPARE_CORES,
    EMBEDDING_MODEL,
)


def _limit_cpu_threads() -> int:
    """
    Leave the machine usable while the model runs.

    Torch defaults to one thread per core and pins all of them. On a
    laptop that is the difference between "ingestion is running" and
    "the editor has frozen". Returns the thread count actually set.
    """
    try:
        import torch
    except ImportError:
        return 0

    cores = os.cpu_count() or 4
    threads = cores if EMBED_SPARE_CORES <= 0 else max(1, cores - EMBED_SPARE_CORES)
    torch.set_num_threads(threads)
    return threads


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    """
    The embedding model, loaded once per process.

    Cached because the model is about 2.2 GB - loading it twice wastes
    time and memory for no benefit.

    Two settings keep it off the machine's knees; see config.py for why.
    Neither changes the vectors for text that fits, so an index built
    before this was added stays valid.
    """
    _limit_cpu_threads()

    # Only batch_size is set here. normalize_embeddings is deliberately
    # left alone: turning it on would change every vector this project
    # produces, and the whole point of this file is that stored vectors
    # and query vectors never drift apart. Batch size changes how the
    # numbers are computed, not what they are.
    model = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        encode_kwargs={"batch_size": EMBED_BATCH_SIZE},
    )

    # Cap the sequence length on the underlying SentenceTransformer.
    # Wrapped in try/except because this reaches through the langchain
    # wrapper into the model object, and that attribute path is not part
    # of the public API - a library upgrade could move it. Losing the cap
    # makes ingestion heavy again; it does not make it wrong.
    try:
        client = model._client
        if getattr(client, "max_seq_length", 0) > EMBED_MAX_TOKENS:
            client.max_seq_length = EMBED_MAX_TOKENS
    except Exception:
        pass

    return model


def get_vector_store(with_model: bool = True) -> Chroma:
    """
    The Chroma collection, wired to the shared embedding model.

    with_model=False opens the same collection without loading the 2.2 GB
    model. That is enough to list, count and delete chunks - which is all
    ingestion needs to decide there is nothing to do - but not to add
    text or search.
    """
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings() if with_model else None,
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
