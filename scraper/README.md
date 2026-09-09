# BIS Change Detector — SQLite Edition

No Docker and no PostgreSQL are required. SQLite is created automatically.

## 1. Put your existing scraper here

The monitor now reads the BIS Revised Standards listing directly. The legacy Selenium scraper is retained only as a separate document-retrieval tool and is not used during normal change checks.

It is intentionally kept unchanged.

## 2. Selected baseline PDFs

Place the manually selected original PDFs in `selected_standards/`. The detector extracts IDs and metadata from these files and stores them in immutable `baseline_standards`.

The monitored BIS route is:

```text
https://standards.bis.gov.in/website/revised-standards
```

The page first shows department counts. Each department opens a list checkpoint such as `revised-standards-list?departmentId=62`. The application uses the public request made by that page:

```text
POST https://standardsadmin.bis.gov.in/master-service//getRevisedStandardsList
```

with `departmentId`, `page`, and `per_page`. It checks only rows whose normalized `standardNumber` matches an ID extracted from the selected PDFs.

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

Test 5 selected PDFs:

```powershell
.\.venv\Scripts\python.exe -m bis_change_detector.change_detector --limit 5
```

Run the complete selected folder:

```powershell
.\.venv\Scripts\python.exe -m bis_change_detector.change_detector
```

## Behavior

- Every run reads only PDFs in `selected_standards/`.
- The revised-standards department counts and paginated lists are read through the verified BIS JSON service.
- No `Know Your Standards` download, CAPTCHA interaction, or document replacement occurs during monitoring.
- Baselines remain immutable in `baseline_standards`.
- Each revised-list observation is appended to `standard_versions`.
- The first BIS observation is compared with the selected PDF baseline, and later observations are compared with the previous BIS observation. All detected differences are written to `standard_changes`; repeated identical changes are ignored.
- `standard_subscriptions` and `notifications` are present for future notification delivery, but no notifications are sent yet.
- SQLite state survives restarts.

Results are printed as `Selected`, `Checked`, `Failed`, `Changes`, and `Status`. `Changes` counts unique standards, not individual changed fields. When changes are detected, the terminal also prints each standard and a short field summary. An unchanged successful run reports `NO_CHANGE`; a successful difference reports `CHANGE_DETECTED`.

The first check establishes the current revised-list observation for each selected standard and reports `CHANGE_DETECTED` when the BIS row differs from the selected PDF baseline. Later checks compare against the latest stored observation. A standard missing from the current revised list is counted as failed, not automatically treated as withdrawn.
