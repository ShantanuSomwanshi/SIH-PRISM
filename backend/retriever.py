import os
import re
import warnings
from typing import List, Tuple
from sentence_transformers import CrossEncoder
from rank_bm25 import BM25Okapi

warnings.filterwarnings("ignore", category=DeprecationWarning)

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

BASE_DIR = os.path.dirname(__file__)
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")

def clean_tokenize(text: str) -> List[str]:
    """Lowercase and remove punctuation so '1001?' matches '1001'."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return [word for word in text.split() if word]

class PrismHybridRetriever:
    def __init__(self):
        print("Initializing PRISM Hybrid Retriever (Vector + BM25)...")

        #Initialize the Cross-Encoder for reranking
        print("Initializing Cross-Encoder Reranker...")
        self.reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        
        self.embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")
        self.vector_store = Chroma(
            persist_directory=CHROMA_PATH, 
            collection_name="prism_standards",
            embedding_function=self.embeddings
        )
        
        db_data = self.vector_store.get(include=["documents", "metadatas"])
        self.documents = db_data["documents"]
        self.metadatas = db_data["metadatas"]
        
        if not self.documents:
            print("Warning: Database is empty. Please run rag_engine.py first.")
            self.bm25 = None
            return

        # Augment BM25 text with source filename so asking for '1001' matches 1001.pdf chunks
        tokenized_corpus = []
        for doc, meta in zip(self.documents, self.metadatas):
            src = os.path.basename(meta.get("source", ""))
            augmented_text = f"{src} {doc}"
            tokenized_corpus.append(clean_tokenize(augmented_text))
            
        self.bm25 = BM25Okapi(tokenized_corpus)
        print(f"✅ BM25 Index built successfully with {len(self.documents)} chunks.")

    def keyword_search(self, query: str, top_k: int = 20) -> List[Tuple[str, dict]]:
        if not self.bm25:
            return []
            
        tokens = clean_tokenize(query)
        scores = self.bm25.get_scores(tokens)
        
        scored_docs = [
            (scores[i], self.documents[i], self.metadatas[i])
            for i in range(len(self.documents))
        ]
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [(doc[1], doc[2]) for doc in scored_docs[:top_k]]

    def vector_search(self, query: str, top_k: int = 20) -> List[Tuple[str, dict]]:
        results = self.vector_store.similarity_search_with_score(query, k=top_k)
        return [(doc.page_content, doc.metadata) for doc, score in results]

    def rrf_fusion(self, vector_results: list, bm25_results: list, k=60) -> List[dict]:
        rrf_scores = {}
        doc_info = {}

        for rank, (doc_content, metadata) in enumerate(vector_results, start=1):
            if doc_content not in rrf_scores:
                rrf_scores[doc_content] = 0.0
                doc_info[doc_content] = {"content": doc_content, "metadata": metadata}
            rrf_scores[doc_content] += 1.0 / (k + rank)

        for rank, (doc_content, metadata) in enumerate(bm25_results, start=1):
            if doc_content not in rrf_scores:
                rrf_scores[doc_content] = 0.0
                doc_info[doc_content] = {"content": doc_content, "metadata": metadata}
            rrf_scores[doc_content] += 1.0 / (k + rank)

        fused_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        
        return [
            {
                "content": doc_info[content]["content"],
                "metadata": doc_info[content]["metadata"],
                "rrf_score": score
            }
            for content, score in fused_docs
        ]

    def search(self, query: str, top_k: int = 4, candidate_pool: int = 20):
        print(f"\n--- Searching candidate pool ({candidate_pool} docs) for: '{query}' ---")
        
        # 1. Retrieve wider candidate pools first
        vec_results = self.vector_search(query, top_k=candidate_pool)
        bm25_results = self.keyword_search(query, top_k=candidate_pool)
        
        # 2. Fuse with Reciprocal Rank Fusion
        fused_results = self.rrf_fusion(vec_results, bm25_results, k=60)
        
        # 3. Cross-Encoder Reranking
        print("--- Reranking top candidates ---")
        # Create pairs of [User Query, Document Chunk] for the reranker to read together
        cross_inp = [[query, doc["content"]] for doc in fused_results]
        
        # The model scores how well the chunk answers the query
        cross_scores = self.reranker.predict(cross_inp)
        
        # Attach the new scores to our results
        for i in range(len(cross_scores)):
            fused_results[i]["rerank_score"] = float(cross_scores[i])
            
        # Sort the results by the new, highly accurate rerank score
        fused_results.sort(key=lambda x: x["rerank_score"], reverse=True)
        
        # Return the absolute best top_k
        return fused_results[:top_k]

# --- Interactive Q&A System with Groq LLM ---
if __name__ == "__main__":
    from dotenv import load_dotenv
    from langchain_groq import ChatGroq
    from langchain_core.prompts import PromptTemplate
    
    load_dotenv()
    
    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0.1,
    )
    
    qa_prompt = PromptTemplate(
        input_variables=["context", "question"],
        template="""
        You are PRISM, a Procurement Recommendation engine for Indian Standards (BIS).
        Answer the user's question based strictly on the provided context below.
        If the context does not contain the answer, say "I cannot find the answer in the provided standards."
        Cite the standard name and clause/table numbers whenever available.
        
        CONTEXT:
        {context}
        
        USER QUESTION:
        {question}
        
        ANSWER:
        """
    )
    
    retriever = PrismHybridRetriever()
    
    print("\n" + "="*60)
    print("🤖 PRISM Hybrid Engine + Groq LLM Initialized!")
    print("Type 'exit' or 'quit' to stop.")
    print("="*60)
    
    while True:
        user_query = input("\n❓ Ask a question about the standards: ")
        
        if user_query.lower() in ['exit', 'quit']:
            print("Shutting down PRISM. Goodbye!")
            break
            
        if not user_query.strip():
            continue
            
        print("\n⏳ Searching standards and generating answer...")
        results = retriever.search(user_query, top_k=4, candidate_pool=20)
        
        formatted_context = ""
        for i, res in enumerate(results, 1):
            filename = os.path.basename(res['metadata'].get('source', 'Unknown'))
            clean_content = res['content'].replace('\n', ' ').strip()
            formatted_context += f"--- Source: {filename} (Rank {i}) ---\n{clean_content}\n\n"
            
        chain = qa_prompt | llm
        response = chain.invoke({"context": formatted_context, "question": user_query})
        
        print("\n" + "-"*60)
        print("💡 PRISM'S ANSWER:")
        print(response.content)
        print("-" * 60)
        
        print("\n📚 SOURCES USED:")
        for res in results:
            filename = os.path.basename(res['metadata'].get('source', 'Unknown'))
            # Print the new rerank score instead!
            print(f"- {filename} (Rerank Score: {res['rerank_score']:.4f})")