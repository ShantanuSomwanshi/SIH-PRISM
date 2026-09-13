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
  * A file is skipped only when its chunks are verifiably in the index,
    not merely because the manifest lists it.
  * Re-ingesting a changed file removes the chunks its old version left
    behind, so a shorter replacement cannot leave stale pages searchable.

Run from the "rag" folder:
    python -m backend.rag_engine                # add new or changed files only
    python -m backend.rag_engine --prune        # also drop files removed from data/
    python -m backend.rag_engine --rebuild      # wipe and rebuild everything
    python -m backend.rag_engine --dry-run      # show the plan, extract + chunk, store nothing
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.catalog import load_catalog, metadata_for
from backend.config import (
    CHROMA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION_NAME,
    DATA_DIR,
    EMBED_BATCH_SIZE,
    EMBEDDING_MODEL,
    MANIFEST_PATH,
    REPORT_PATH,
)
from backend.pdf_extract import _file_hash, extract_pdf

# A page yielding less than this is worth flagging in the report.
LOW_YIELD_CHARS_PER_PAGE = 500

# Chroma is asked to delete at most this many ids per call.
DELETE_BATCH_SIZE = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Manifest --------------------------------------------------------
#
# processed_files.json is the list of ingested files: filename -> the
# SHA-256 it had, how many chunks it produced, and when. It is what lets a
# normal run skip the files already done.
#
# It is not trusted on its own, though. The manifest and chroma_db are two
# separate things on disk, and they can disagree: delete or restore
# chroma_db and the manifest still claims every file is indexed, so every
# file is skipped and the index stays empty. So the decision to skip is
# checked against what the index actually holds (see already_indexed).

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
    ordered = {name: manifest[name] for name in sorted(manifest)}
    MANIFEST_PATH.write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- What the index actually holds ------------------------------------
#
# Every chunk written from now on carries two extra metadata fields:
#
#   source_sha256   the hash of the PDF it came from
#   source_chunks   how many chunks that PDF produced in total
#
# Together they let the index vouch for itself. If every chunk of a file
# carries the file's current hash, and there are exactly source_chunks of
# them, that file is completely and currently indexed - whatever the
# manifest says. A run interrupted halfway through a file leaves fewer
# chunks than source_chunks, so it is caught too.
#
# Chunks from before this change have neither field. For those the
# manifest is still the record, checked against the chunk count.

def index_inventory(store) -> Dict[str, List[Tuple[str, dict]]]:
    """
    Every chunk in the index, grouped by source filename.

    Reads ids and metadata only - no text, no vectors - so it is cheap
    even for the whole corpus.
    """
    if store is None:
        return {}
    data = store.get(include=["metadatas"])
    inventory: Dict[str, List[Tuple[str, dict]]] = {}
    for chunk_id, meta in zip(data.get("ids") or [], data.get("metadatas") or []):
        source = (meta or {}).get("source")
        if source:
            inventory.setdefault(source, []).append((chunk_id, meta or {}))
    return inventory


def already_indexed(file_hash: str, entry: Optional[dict],
                    stored: List[Tuple[str, dict]]) -> Tuple[bool, str]:
    """
    Is this exact file already completely in the index?

    Returns (True, "unchanged") to skip it, or (False, reason) to ingest it.
    """
    count = len(stored)
    stamped = [meta for _, meta in stored if meta.get("source_sha256")]

    if stamped and len(stamped) != count:
        return False, ("the index holds a mix of old and new chunks for this "
                       "file - an earlier run was interrupted")

    # The index can answer for itself.
    if stamped:
        if {meta["source_sha256"] for meta in stamped} != {file_hash}:
            return False, "file has changed since it was indexed"
        totals = {meta.get("source_chunks") for meta in stamped}
        if totals != {count}:
            expected = max((t for t in totals if isinstance(t, int)), default="?")
            return False, (f"the index holds {count} of {expected} chunks - "
                           "an earlier run was interrupted")
        return True, "unchanged"

    # Chunks from before hashes were stamped on them: use the manifest.
    if entry is None:
        if count:
            return False, (f"{count} chunk(s) in the index but not in the "
                           "manifest - re-ingesting to be sure they are current")
        return False, "new file"
    if entry.get("sha256") != file_hash:
        return False, "file has changed since last run"
    expected = entry.get("chunks")
    if expected != count:
        if count == 0:
            return False, ("listed as ingested, but the index has none of its "
                           "chunks (was chroma_db deleted or replaced?)")
        return False, (f"the index holds {count} of {expected} chunks - "
                       "an earlier run was interrupted")
    return True, "unchanged"


def delete_chunks(store, ids: List[str]) -> None:
    for start in range(0, len(ids), DELETE_BATCH_SIZE):
        store.delete(ids=ids[start:start + DELETE_BATCH_SIZE])


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
        # A page marked "legacy-font" is Hindi set in a pre-Unicode font.
        # It extracts as a wall of characters that are not words in any
        # language ("Hkkjrh; ekud"), and OCR could not rescue it because
        # the Hindi language pack is not installed. Indexing it would put
        # noise into the vector store and into LLM prompts, so it is left
        # out. Install the pack and set OCR_LANG=eng+hin to include it.
        if page.method == "legacy-font":
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
    unreadable = sum(1 for p in result.pages if p.method == "legacy-font")
    if unreadable:
        warnings.append(
            f"{unreadable} Hindi page(s) use a legacy font and were left out - "
            "install the Tesseract Hindi pack and set OCR_LANG=eng+hin to read them"
        )
    if chunk_count == 0:
        warnings.append("produced no chunks - nothing from this file is searchable")
    report["warnings"] = warnings
    return report


def _totals(files: List[dict]) -> dict:
    return {
        "files": len(files),
        "pages": sum(f.get("total_pages", 0) for f in files),
        "chars": sum(f.get("total_chars", 0) for f in files),
        "chunks": sum(f.get("chunks", 0) for f in files),
        "ocr_pages": sum(f.get("ocr_pages", 0) for f in files),
        "legacy_font_pages": sum(f.get("legacy_font_pages", 0) for f in files),
        "boilerplate_chars_removed":
            sum(f.get("boilerplate_chars_removed", 0) for f in files),
    }


def load_report() -> dict:
    if not REPORT_PATH.exists():
        return {}
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def merge_report(previous: dict, run_files: List[dict], drop: set) -> dict:
    """
    The report describes the whole index, not just the last run.

    It used to be overwritten with only the files a run processed, so
    adding one PDF to an 18-file corpus left a report claiming the corpus
    was 1 file. Entries for files processed now replace their old ones;
    files removed from the index are dropped.
    """
    files = {f["filename"]: f for f in previous.get("files", []) if "filename" in f}
    for name in drop:
        files.pop(name, None)
    for item in run_files:
        files[item["filename"]] = item
    ordered = [files[name] for name in sorted(files)]
    return {"generated_at": _now(), "totals": _totals(ordered), "files": ordered}


def print_report(run_files: List[dict], corpus: Optional[dict] = None) -> None:
    totals = _totals(run_files)
    print(f"\n{'file':30} {'pages':>5} {'ch/page':>8} {'ocr':>4} {'chunks':>7}")
    print("-" * 60)
    for item in run_files:
        print(f"{item['filename']:30.30} {item['total_pages']:>5} "
              f"{item['chars_per_page']:>8.0f} {item['ocr_pages']:>4} "
              f"{item['chunks']:>7}")
    print("-" * 60)
    print(f"{'THIS RUN':30} {totals['pages']:>5} {'':>8} "
          f"{totals['ocr_pages']:>4} {totals['chunks']:>7}")
    print(f"\nWatermark characters removed: {totals['boilerplate_chars_removed']:,}")

    flagged = [f for f in run_files if f["warnings"]]
    if flagged:
        print("\nWarnings:")
        for item in flagged:
            for warning in item["warnings"]:
                print(f"  {item['filename']}: {warning}")
    else:
        print("\nNo warnings - every file extracted cleanly.")

    if corpus:
        c = corpus["totals"]
        print(f"\nWhole index: {c['files']} files, {c['pages']} pages, "
              f"{c['chunks']} chunks.")


# --- Main ------------------------------------------------------------

def ingest(rebuild: bool = False, dry_run: bool = False, prune: bool = False) -> int:
    if not DATA_DIR.exists():
        print(f"Data folder not found: {DATA_DIR}")
        return 1

    pdfs = sorted(p for p in DATA_DIR.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"No PDFs found in {DATA_DIR}")
        return 1
    pdf_names = {p.name for p in pdfs}

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
        if REPORT_PATH.exists():
            REPORT_PATH.unlink()
        print("Index cleared.\n")

    manifest = load_manifest()
    manifest_before = json.dumps(manifest, sort_keys=True)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, length_function=len
    )

    # Open the index WITHOUT the embedding model to see what it holds.
    # Deciding that nothing needs doing should take seconds, not the
    # minute it takes to load 2.2 GB of weights.
    from backend.embeddings import get_vector_store
    index = None
    if CHROMA_DIR.exists() or not dry_run:
        index = get_vector_store(with_model=False)
    inventory = index_inventory(index)

    # --- plan: which files need work -----------------------------------
    pending = []
    for pdf in pdfs:
        file_hash = _file_hash(pdf)
        stored = inventory.get(pdf.name, [])
        entry = manifest.get(pdf.name)
        done, reason = already_indexed(file_hash, entry, stored)

        if done:
            print(f"  {pdf.name}: unchanged, skipping")
            # The index vouched for a file the manifest does not describe
            # correctly (e.g. the manifest was lost). Write down the truth.
            if (entry is None or entry.get("sha256") != file_hash
                    or entry.get("chunks") != len(stored)):
                manifest[pdf.name] = {
                    "sha256": file_hash,
                    "chunks": len(stored),
                    "standard_id": (stored[0][1].get("standard_id")
                                    if stored else catalog.get(pdf.name, {}).get("standard_id")),
                    "ingested_at": (entry or {}).get("ingested_at"),
                    "recovered_from_index_at": _now(),
                }
            continue

        print(f"  {pdf.name}: {reason}")
        pending.append((pdf, file_hash, [chunk_id for chunk_id, _ in stored]))

    # --- files that are no longer in data/ ------------------------------
    # Their chunks are still searchable until they are removed. That is
    # the same stale-content problem as a shrunken replacement, but
    # deleting is not done by default: pointing DOCUMENTS_DIR at the wrong
    # folder would otherwise empty the index in one run.
    removed_from_index = set()
    gone = sorted((set(inventory) | set(manifest)) - pdf_names)
    for name in gone:
        ids = [chunk_id for chunk_id, _ in inventory.get(name, [])]
        if not ids:
            manifest.pop(name, None)        # listed, but nothing to remove
            removed_from_index.add(name)
        elif prune and not dry_run:
            delete_chunks(index, ids)
            manifest.pop(name, None)
            removed_from_index.add(name)
            print(f"  {name}: no longer in {DATA_DIR.name}/ - removed its {len(ids)} chunk(s)")
        elif prune:
            print(f"  {name}: no longer in {DATA_DIR.name}/ - would remove its {len(ids)} chunk(s)")
        else:
            print(f"  WARNING {name}: no longer in {DATA_DIR.name}/, but its "
                  f"{len(ids)} chunk(s) are still searchable. "
                  "Run with --prune to remove them.")

    manifest_changed = json.dumps(manifest, sort_keys=True) != manifest_before

    if not pending:
        if not dry_run and manifest_changed:
            save_manifest(manifest)
        if not dry_run and removed_from_index and REPORT_PATH.exists():
            REPORT_PATH.write_text(json.dumps(
                merge_report(load_report(), [], removed_from_index),
                indent=2, ensure_ascii=False), encoding="utf-8")
        print("\nEverything is already indexed. Nothing to do.")
        return 0

    print(f"\nProcessing {len(pending)} file(s)...\n")

    # Load the model ONCE, before the loop, unless this is a dry run.
    # Embedding happens per file so that a crash - or a Ctrl+C - costs you
    # one file, not the whole corpus. Previously everything was embedded
    # at the end and the manifest was written after that, so an
    # interrupted run left the index half-populated and the manifest
    # empty: the next run started again from zero.
    store = None
    if not dry_run:
        print(f"Loading embedding model ({EMBEDDING_MODEL})...")
        print("The first run downloads about 2.2 GB - later runs are fast.")
        store = get_vector_store()
        print(f"Embedding {EMBED_BATCH_SIZE} chunks at a time.\n")

    file_reports = []
    first_texts, first_metadatas = [], []
    stored_total = stale_total = 0

    for position, (pdf, file_hash, old_ids) in enumerate(pending, 1):
        print(f"  [{position}/{len(pending)}] {pdf.name}")
        result = extract_pdf(pdf, verbose=True)
        entry = catalog.get(pdf.name, {})
        base_metadata = metadata_for(pdf.name, catalog)

        texts, metadatas, ids = chunk_document(result, base_metadata, splitter)
        for meta in metadatas:
            meta["source_sha256"] = file_hash
            meta["source_chunks"] = len(texts)
        if texts and not first_texts:
            first_texts, first_metadatas = texts, metadatas

        # Chunk ids are "<file>::p<page>::c<n>", and Chroma UPSERTS by id.
        # So a new version overwrites the chunks whose ids it reproduces -
        # but if it has fewer pages, or a page now splits into fewer
        # pieces, the old version's extra chunks are never touched and
        # stay searchable. Those are the ones listed here.
        new_ids = set(ids)
        stale = [chunk_id for chunk_id in old_ids if chunk_id not in new_ids]

        file_reports.append(build_file_report(result, entry, len(texts)))
        print(f"     -> {len(texts)} chunks "
              f"({result.chars_per_page:.0f} chars/page, "
              f"{result.ocr_pages} page(s) via OCR)")

        if store is None:
            if stale:
                print(f"        would remove {len(stale)} stale chunk(s) "
                      "left by the previous version")
            continue

        if texts:
            for start in range(0, len(texts), EMBED_BATCH_SIZE):
                stop = min(start + EMBED_BATCH_SIZE, len(texts))
                store.add_texts(
                    texts=texts[start:stop],
                    metadatas=metadatas[start:stop],
                    ids=ids[start:stop],
                )
                stored_total += stop - start
                print(f"        embedded {stop}/{len(texts)}", end="\r", flush=True)
            print(f"        embedded {len(texts)}/{len(texts)}   ")

        # Remove leftovers only AFTER the new chunks are stored. If the run
        # dies in between, the file is briefly over-represented rather than
        # missing, and the next run sees the mixed hashes and redoes it.
        if stale:
            delete_chunks(store, stale)
            stale_total += len(stale)
            print(f"        removed {len(stale)} stale chunk(s) left by the previous version")

        # Record this file only once its chunks are actually in the store,
        # so the manifest never claims work that was not finished.
        manifest[pdf.name] = {
            "sha256": file_hash,
            "chunks": len(texts),
            "standard_id": entry.get("standard_id"),
            "ingested_at": _now(),
        }
        save_manifest(manifest)

    if dry_run:
        print_report(file_reports)
        print("\nDRY RUN - nothing was embedded, stored or deleted, and the "
              "manifest and report were left as they were.")
        if first_metadatas:
            print("\nExample chunk metadata:")
            print(json.dumps(first_metadatas[0], indent=2, ensure_ascii=False))
            print("\nExample chunk text (first 300 chars):")
            print(first_texts[0][:300])
        return 0

    save_manifest(manifest)
    corpus = merge_report(load_report(), file_reports, removed_from_index)
    REPORT_PATH.write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print_report(file_reports, corpus)
    print(f"\nDone. {stored_total} chunks indexed"
          + (f", {stale_total} stale chunks removed." if stale_total else "."))
    print(f"Report written to {REPORT_PATH.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest BIS PDFs into Chroma.")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete the existing index and start over")
    parser.add_argument("--dry-run", action="store_true",
                        help="extract and chunk, but do not embed, store or delete")
    parser.add_argument("--prune", action="store_true",
                        help="remove chunks of PDFs that are no longer in the data folder")
    args = parser.parse_args()
    return ingest(rebuild=args.rebuild, dry_run=args.dry_run, prune=args.prune)


if __name__ == "__main__":
    sys.exit(main())
