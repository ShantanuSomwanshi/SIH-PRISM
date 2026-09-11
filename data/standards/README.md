# data/standards/

**The corpus.** Indian Standards documents, ingested and made searchable.

Put the PDFs directly in this folder - not in sub-folders. Ingestion only
reads the top level.

```powershell
cd rag
python -m backend.build_catalog          # filename + cover -> IS number and title
python -m backend.rag_engine             # extract, OCR where needed, embed
python -m backend.build_reference_graph  # which standard cites which
```

## Naming matters

The catalogue reads the standard number, part and year from the FILENAME
before it looks at the cover page, because OCR mangles digits. One cover
in the original set has a text layer reading "IS 10 ( Part 1 ): 1910" when
the standard is from 1990 - the filename is what got it right.

The pattern understood today:

```
10_1_1990_reff2020.pdf   ->  IS 10 (Part 1) : 1990, reaffirmed 2020
1863_1979_reff2019.pdf   ->  IS 1863 : 1979, reaffirmed 2019
1001.pdf                 ->  IS 1001
sp42_2008_reff2021.pdf   ->  SP 42 : 2008, reaffirmed 2021
```

If your files are named differently, say so before ingesting - adjusting
the parser takes minutes, re-ingesting a large corpus does not.

## What happens to them

Scanned pages are detected per page and read with OCR. The BIS download
watermark is stripped. Text is chunked per page so citations carry a real
page number. Nothing is rejected for being a scan.

`ingestion_report.json` records characters per page and OCR counts for
every file, and flags anything that extracted poorly. Read it after a run.

## Not committed

These are gitignored. They are large, and the BIS watermark on a portal
download carries the downloader's email address and IP.
