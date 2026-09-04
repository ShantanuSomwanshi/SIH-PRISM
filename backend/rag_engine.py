import os
import json
import warnings

# Suppress LangChain's deprecation warnings so our terminal stays clean
warnings.filterwarnings("ignore", category=DeprecationWarning)


from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import PDFPlumberLoader

# Define paths
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")
MANIFEST_PATH = os.path.join(BASE_DIR, "processed_files.json")

def load_manifest():
    """Loads the list of already processed files from the JSON manifest."""
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            return set(json.load(f))
    return set()

def save_manifest(processed_files):
    """Saves the updated list of files back to the JSON manifest."""
    with open(MANIFEST_PATH, "w") as f:
        json.dump(list(processed_files), f, indent=4)

def ingest_pdfs_from_data_folder():
    print("--- Starting PRISM Ingestion Engine (JSON Manifest Mode) ---")
    
    if not os.path.exists(DATA_DIR):
        print(f"Error: The directory {DATA_DIR} does not exist.")
        return

    all_pdf_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.pdf')]
    if not all_pdf_files:
        print(f"Error: No PDF files found inside {DATA_DIR}.")
        return

    # 1. Check the JSON list instantly
    processed_files = load_manifest()
    new_files = [f for f in all_pdf_files if f not in processed_files]

    if not new_files:
        print("\nAll files are already tracked in processed_files.json. Nothing to do!")
        return

    print(f"\nFound {len(new_files)} NEW files to process. Starting extraction...")
    
    # 2. Load the NEW PDFs
    all_docs = []
    for filename in new_files:
        file_path = os.path.join(DATA_DIR, filename)
        loader = PDFPlumberLoader(file_path)
        all_docs.extend(loader.load())
        print(f"  -> Successfully read: {filename}")

    # 3. Chunk the text
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len
    )
    chunks = text_splitter.split_documents(all_docs)
    print(f"Split new documents into {len(chunks)} text chunks.")

    # Generate unique IDs for the new chunks
    chunk_ids = []
    for i, chunk in enumerate(chunks):
        filename = os.path.basename(chunk.metadata.get('source', 'unknown_doc'))
        chunk_ids.append(f"{filename}_chunk_{i}")

    # 4. Initialize Embeddings ONLY if we have new files
    print("\nInitializing Embedding Model...")
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")
    
    db = Chroma(
        persist_directory=CHROMA_PATH, 
        collection_name="prism_standards",
        embedding_function=embeddings
    )

    # 5. Store the new chunks in Chroma
    print("Embedding new chunks and adding them to ChromaDB...")
    db.add_documents(documents=chunks, ids=chunk_ids)
    
    # 6. Update the JSON file so we don't process these again
    processed_files.update(new_files)
    save_manifest(processed_files)
    
    print(f"\n✅ Success! Added {len(chunks)} new chunks. Updated processed_files.json.")

if __name__ == "__main__":
    ingest_pdfs_from_data_folder()