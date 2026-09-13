"""Offline regression tests for scraper safety and source integration."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

from bis_change_detector.artifact_parser import parse_text
from bis_change_detector.change_detector import _merge_records
from bis_change_detector.change_detector import ChangeDetector
from bis_change_detector.db import Database
from bis_change_detector.fingerprint import row_fingerprint, standard_identity
from bis_change_detector.revised_client import RevisedStandard
from bis_change_detector.whats_new_detector import WhatsNewDetector, WhatsNewEntry
from bis_change_detector.whats_new_downloader import WhatsNewDownloadError, download_pdf


def test_standard_identity_ignores_year():
    assert standard_identity("IS 19497: 2026") == "IS 19497"
    assert standard_identity("IS 19497") == "IS 19497"
    assert standard_identity("IS 17017 (Part 23) : 2021") == "IS 17017 (PART 23)"


def test_three_source_merge_prefers_api_and_keeps_evidence():
    merged = _merge_records(
        {"standard_id": "IS 1", "title": "API title"},
        {"standard_id": "IS 1", "scope": "scope"},
        {"standard_id": "IS 1", "whats_new_count": 2},
    )
    assert merged["title"] == "API title"
    assert merged["scope"] == "scope"
    assert merged["whats_new_count"] == 2
    assert merged["source_type"] == "MERGED"


def test_whats_new_card_metadata_stays_with_card():
    html = BeautifulSoup("""
      <div class="card">
        <h2><a href="https://bis.test/a.pdf">Revision of IS 1234</a></h2>
        <p>Type: pdf</p><p>Published On: 2 Sep, 2026</p>
      </div>
      <div class="card">
        <h2><a href="https://bis.test/b.pdf">Revision of IS 5678</a></h2>
        <p>Type: pdf</p><p>Published On: 3 Sep, 2026</p>
      </div>
    """, "html.parser")
    entries = WhatsNewDetector().parse_entries_from_html(html)
    assert [(entry.standard_id, entry.published_date.day) for entry in entries] == [
        ("IS 1234", 2), ("IS 5678", 3)
    ]


def test_pdf_text_is_redacted_before_persistence():
    record = parse_text("IS 1234\nContact test@example.com\nPhone +91-9876543210", Path("x.pdf"))
    assert "test@example.com" not in record["raw_text_excerpt"]
    assert "+91-9876543210" not in record["raw_text_excerpt"]


def test_whats_new_entries_persist_with_lifecycle():
    db_path = Path("test_scraper_lifecycle.sqlite")
    if db_path.exists():
        db_path.unlink()
    try:
        database = Database("sqlite:///test_scraper_lifecycle.sqlite", Path("."))
        database.record_whats_new_entries([
            WhatsNewEntry(
                "Revision of IS 1234", "IS 1234", "pdf",
                datetime(2026, 9, 13), "https://bis.test/a.pdf", "1 MB", "main"
            )
        ])
        with database.conn() as connection:
            assert connection.execute("SELECT COUNT(*) FROM whats_new_entries").fetchone()[0] == 1
            row = connection.execute(
                "SELECT lifecycle_status, verification_status FROM standard_lifecycle"
            ).fetchone()
            assert tuple(row) == ("DISCOVERED", "PENDING")
    finally:
        if db_path.exists():
            db_path.unlink()


def test_confirmed_whats_new_candidate_becomes_current_observation():
    database_url = 'sqlite:///test_candidate_promotion.sqlite'
    db_path = Path('test_candidate_promotion.sqlite')
    if db_path.exists():
        db_path.unlink()
    settings = SimpleNamespace(
        database_url=database_url,
        lock_file=Path('test_candidate_promotion.lock'),
        selected_standards_dir=Path('.'),
        whats_new_enabled=True,
        whats_new_include_archive=False,
        whats_new_max_pages=0,
        whats_new_download_pdfs=False,
        request_timeout=1,
        retries=0,
        retry_base_seconds=0,
        scraper_output_dir=Path('.'),
    )
    baseline = {
        'standard_id': 'IS 1000 : 2020', 'title': 'Existing', 'status': 'ACTIVE',
        'last_amendment_date': None, 'publication_date': '2020',
        'amendment': None, 'reaffirmation': None, 'edition': None,
        'scope': None, 'source_artifact': 'baseline.pdf',
        'raw_text_excerpt': '', 'extraction_warnings': [],
    }
    baseline['row_fingerprint'] = row_fingerprint(baseline)
    candidate = RevisedStandard(
        'IS 2000', 'IS 2000 : 2026', 'New standard', '2026',
        'New', 'None', '/docs/is-2000.pdf'
    )
    entry = WhatsNewEntry(
        'New IS 2000', 'IS 2000', 'pdf', datetime(2026, 9, 13),
        'https://www.bis.gov.in/is-2000.pdf', '1 MB', 'main'
    )
    detector = ChangeDetector(settings)
    try:
        with patch.object(detector, '_load_selected', return_value=[baseline]), \
             patch.object(detector, '_fetch_whats_new_entries', return_value=[entry]), \
             patch('bis_change_detector.change_detector.fetch_selected', return_value={
                 'IS 1000 : 2020': RevisedStandard(
                     'IS 1000 : 2020', 'IS 1000 : 2020', 'Existing', '2020',
                     'Current', 'None', '/docs/is-1000.pdf'
                 ),
                 'IS 2000': candidate,
             }):
            result = detector._run(limit=None)
        with detector.db.conn() as connection:
            observation = connection.execute(
                "SELECT version_type FROM standard_versions WHERE standard_id='IS 2000'"
            ).fetchone()
            lifecycle = connection.execute(
                "SELECT lifecycle_status FROM standard_lifecycle WHERE standard_id='IS 2000'"
            ).fetchone()
        assert result['new_standards_saved'] == 1
        assert observation[0] == 'BIS_REVISED_LIST'
        assert lifecycle[0] == 'VERIFIED_IN_REVISED_LIST'
    finally:
        if db_path.exists():
            db_path.unlink()


def test_download_rejects_low_confidence_entry():
    entry = WhatsNewEntry(
        'IS 1234 announcement', 'IS 1234', 'pdf', datetime(2026, 9, 13),
        'https://www.bis.gov.in/is-1234.pdf', '1 MB', 'main'
    )
    try:
        download_pdf(entry, Path('.'))
    except WhatsNewDownloadError as exc:
        assert 'confidence is low' in str(exc)
    else:
        raise AssertionError('low-confidence entry was accepted for download')


def test_downloaded_lifecycle_cannot_be_downgraded():
    db_path = Path('test_lifecycle_monotonic.sqlite')
    if db_path.exists():
        db_path.unlink()
    try:
        database = Database('sqlite:///test_lifecycle_monotonic.sqlite', Path('.'))
        database.record_whats_new_entries([
            WhatsNewEntry('IS 1234', 'IS 1234', 'pdf', datetime(2026, 9, 13),
                          'https://www.bis.gov.in/is-1234.pdf', '1 MB', 'main', 'high')
        ])
        database.update_lifecycle_status('IS 1234', 'DOCUMENT_RETRIEVED', 'DOWNLOADED',
                                         Path('artifact.pdf'), 'hash')
        database.update_lifecycle_status('IS 1234', 'DISCOVERED', 'PENDING')
        with database.conn() as connection:
            row = connection.execute(
                'SELECT lifecycle_status, verification_status FROM standard_lifecycle'
            ).fetchone()
        assert tuple(row) == ('DOCUMENT_RETRIEVED', 'DOWNLOADED')
    finally:
        if db_path.exists():
            db_path.unlink()


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} offline scraper regression tests passed")
