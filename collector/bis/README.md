# BIS Change Detector ΓÇö SQLite Edition

No Docker and no PostgreSQL are required. SQLite is created automatically.

## 1. Put your existing scraper here

`legacy_scraper/download_standards.py`

It is intentionally kept unchanged.

## 2. Optional Book 2.xlsx

The original scraper expects `Book 2.xlsx` with an `IS_Number` column. The wrapper now generates a temporary `Book 2.xlsx` for each targeted run, so the permanent workbook is **not required for normal discovered-page operation**. It is only a safe fallback if BIS page discovery cannot find standard IDs, and is useful as a first-run seed if desired.

## 3. Install

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## 4. Run one cycle

```powershell
.\.venv\Scripts\python.exe -m bis_change_detector.change_detector
```

## 5. Run continuously

```powershell
.\.venv\Scripts\python.exe -m bis_change_detector.scheduler
```

## Behavior

- Tier 1 fetches the monitored page, removes scripts and obvious dynamic attributes, and hashes normalized HTML with SHA-256.
- If the hash is unchanged, no scraper is invoked.
- If changed, the wrapper discovers standard IDs and lightweight per-row page fingerprints.
- Only new standards or standards whose visible page row changed are sent to the **unchanged** Selenium scraper.
- A temporary `Book 2.xlsx` containing only those IDs is created for the scraper.
- Downloads are isolated in a temporary directory, so old files are never reprocessed.
- Artifacts are parsed into structured records and row fingerprints use exactly `SHA-256(Standard_ID + Title + Status + Last_Amendment_Date)`.
- Missing standards are marked WITHDRAWN only when discovery produced a complete standard set and all selected artifacts were accounted for.
- SQLite state survives restarts.
