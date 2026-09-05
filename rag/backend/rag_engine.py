"""
PRISM ingestion: turn the PDFs in backend/data into searchable chunks.

What changed from the first version:
  * Scanned pages are read with OCR instead of being silently skipped.
  * The BIS download watermark is stripped from every page.
  * Text is chunked PER PAGE, so every chunk keeps its page number.
  * Every chunk carries its real standard number and title from
    standards_catalog.json - not just a filename.
  * File paths are stored as bare filenames, never "C:\\Users\\...".
  * Every chunk gets a stable, unique id.
  * The manifest records a file hash, so replacing a PDF re-ingests it.
  * An ingestion report is written so bad extractions are visible.

Run from the "rag" folder:
    python -m backend.rag_engine                # add new files only
    python -m backend.rag_engine --rebuild      # wipe and rebuild everything
    python -m backend.rag_engine --dry-run      # extract + chunk, no embedding
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.catalog import load_catalog, metadata_for
from backend.config import (
    CHROMA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION_NAME,
    DATA_DIR,
    EMBEDDING_MODEL,
    MANIFEST_PATH,
    REPORT_PATH,
)
from backend.pdf_extract import _file_hash, extract_pdf

# A page yielding less than this is worth flagging in the report.
LOW_YIELD_CHARS_PER_PAGE = 500


# --- Manifest --------------------------------------------------------

def load_manifest() -> dict:
    """
    Which files are already in the index, and what they hashed to.

    The original version stored a plain list of filenames, which could not
    tell that a PDF had been replaced. A list is treated as empty so the
    corpus gets rebuilt properly.
    """
    if not MANIFEST_PATH.exists():
        return {}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Chunking --------------------------------------------------------

def chunk_document(result, base_metadata: dict, splitter) -> tuple:
    """
    Split one PDF into chunks, page by page.

    Chunking per page means a chunk never straddles a page boundary, so the
    page number attached to it is always correct. That is what makes
    citations like "IS 33, page 12" trustworthy.

    Each chunk's text is prefixed with the standard number and title, so a
    search for "IS 33" or "antimony oxide" can match the chunk directly
    rather than relying on the filename.
    """
    texts, metadatas, ids = [], [], []
    standard_id = base_metadata.get("standard_id", result.filename)
    title = base_metadata.get("title", "")
    header = f"[{standard_id}] {title}".strip()

    for page in result.pages:
        if not page.text:
            continue
        for index, piece in enumerate(splitter.split_text(page.text)):
            texts.append(f"{header}\n\n{piece}" if header else piece)
            metadatas.append({
                **base_metadata,
                "source": result.filename,          # bare filename, no paths
                "page": page.page,
                "total_pages": result.total_pages,
                "extraction_method": page.method,
                "chunk_id": f"{result.filename}::p{page.page:04d}::c{index:03d}",
            })
            ids.append(metadatas[-1]["chunk_id"])

    return texts, metadatas, ids


# --- Reporting -------------------------------------------------------

def build_file_report(result, entry: dict, chunk_count: int) -> dict:
    report = result.summary()
    report["standard_id"] = entry.get("standard_id")
    report["catalog_confidence"] = entry.get("confidence")
    report["chunks"] = chunk_count

    warnings = []
    if not entry:
        warnings.append("no entry in standards_catalog.json - run build_catalog")
    if result.chars_per_page < LOW_YIELD_CHARS_PER_PAGE:
        warnings.append(
            f"only {result.chars_per_page:.0f} characters per page - "
            "check whether this PDF extracted properly"
        )
    if result.empty_pages:
        warnings.append(f"{result.empty_pages} page(s) produced no text at all")
    if chunk_count == 0:
        warnings.append("produced no chunks - nothing from this file is searchable")
    report["warnings"] = warnings
    return report


def print_report(report: dict) -> None:
    totals = report["totals"]
    print(f"\n{'file':30} {'pages':>5} {'ch/page':>8} {'ocr':>4} {'chunks':>7}")
    print("-" * 60)
    for item in report["files"]:
        print(f"{item['filename']:30.30} {item['total_pages']:>5} "
              f"{item['chars_per_page']:>8.0f} {item['ocr_pages']:>4} "
              f"{item['chunks']:>7}")
    print("-" * 60)
    print(f"{'TOTAL':30} {totals['pages']:>5} {'':>8} "
          f"{totals['ocr_pages']:>4} {totals['chunks']:>7}")
    print(f"\nWatermark characters removed: {totals['boilerplate_chars_removed']:,}")

    flagged = [f for f in report["files"] if f["warnings"]]
    if flagged:
        print("\nWarnings:")
        for item in flagged:
            for warning in item["warnings"]:
                print(f"  {item['filename']}: {warning}")
    else:
        print("\nNo warnings - every file extracted cleanly.")


# --- Main ------------------------------------------------------------

def ingest(rebuild: bool = False, dry_run: bool = False) -> int:
    if not DATA_DIR.exists():
        print(f"Data folder not found: {DATA_DIR}")
        return 1

    pdfs = sorted(p for p in DATA_DIR.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"No PDFs found in {DATA_DIR}")
        return 1

    catalog = load_catalog()
    if not catalog:
        print("WARNING: standards_catalog.json is missing or empty.")
        print("         Chunks will only know their filename.")
        print("         Run: python -m backend.build_catalog\n")

    if rebuild and not dry_run:
        if CHROMA_DIR.exists():
            print(f"Removing existing index at {CHROMA_DIR} ...")
            shutil.rmtree(CHROMA_DIR)
        if MANIFEST_PATH.exists():
            MANIFEST_PATH.unlink()
        print("Index cleared.\n")

    manifest = load_manifest()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, length_function=len
    )

    pending = []
    for pdf in pdfs:
        file_hash = _file_hash(pdf)
        known = manifest.get(pdf.name)
        if known and known.get("sha256") == file_hash:
            print(f"  {pdf.name}: unchanged, skipping")
            continue
        if known:
            print(f"  {pdf.name}: file has changed since last run - re-ingesting")
        pending.append((pdf, file_hash))

    if not pending:
        print("\nEverything is already indexed. Nothing to do.")
        return 0

    print(f"\nProcessing {len(pending)} file(s)...\n")

    all_texts, all_metadatas, all_ids, file_reports = [], [], [], []

    for pdf, file_hash in pending:
        print(f"  {pdf.name}")
        result = extract_pdf(pdf, verbose=True)
        entry = catalog.get(pdf.name, {})
        base_metadata = metadata_for(pdf.name, catalog)

        texts, metadatas, ids = chunk_document(result, base_metadata, splitter)
        all_texts.extend(texts)
        all_metadatas.extend(metadatas)
        all_ids.extend(ids)

        file_reports.append(build_file_report(result, entry, len(texts)))
        manifest[pdf.name] = {
            "sha256": file_hash,
            "chunks": len(texts),
            "standard_id": entry.get("standard_id"),
            "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        print(f"     -> {len(texts)} chunks "
              f"({result.chars_per_page:.0f} chars/page, "
              f"{result.ocr_pages} page(s) via OCR)")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totals": {
            "files": len(file_reports),
            "pages": sum(f["total_pages"] for f in file_reports),
            "chars": sum(f["total_chars"] for f in file_reports),
            "chunks": len(all_texts),
            "ocr_pages": sum(f["ocr_pages"] for f in file_reports),
            "boilerplate_chars_removed":
                sum(f["boilerplate_chars_removed"] for f in file_reports),
        },
        "files": file_reports,
    }
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if dry_run:
        print_report(report)
        print(f"\nDRY RUN - nothing was embedded or stored.")
        print(f"Report written to {REPORT_PATH.name}")
        if all_metadatas:
            print("\nExample chunk metadata:")
            print(json.dumps(all_metadatas[0], indent=2, ensure_ascii=False))
            print("\nExample chunk text (first 300 chars):")
            print(all_texts[0][:300])
        return 0

    # --- embed and store ---
    print(f"\nLoading embedding model ({EMBEDDING_MODEL})...")
    print("The first run downloads about 2.2 GB - later runs are fast.")
    from backend.embeddings import get_vector_store
    store = get_vector_store()

    print(f"Embedding and storing {len(all_texts)} chunks...")
    batch = 200
    for start in range(0, len(all_texts), batch):
        store.add_texts(
            texts=all_texts[start:start + batch],
            metadatas=all_metadatas[start:start + batch],
            ids=all_ids[start:start + batch],
        )
        print(f"  stored {min(start + batch, len(all_texts))}/{len(all_texts)}")

    save_manifest(manifest)
    print_report(report)
    print(f"\nDone. {len(all_texts)} chunks indexed.")
    print(f"Report written to {REPORT_PATH.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest BIS PDFs into Chroma.")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete the existing index and start over")
    parser.add_argument("--dry-run", action="store_true",
                        help="extract and chunk, but do not embed or store")
    args = parser.parse_args()
    return ingest(rebuild=args.rebuild, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
