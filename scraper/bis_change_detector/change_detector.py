import argparse
import logging
import uuid
from datetime import datetime, timezone

from filelock import FileLock, Timeout

from .artifact_parser import parse_artifact
from .config import ROOT, Settings
from .db import Database
from .fingerprint import REVISION_FIELDS, revision_fingerprint, row_fingerprint, standard_identity
from .logging_config import setup_logging
from .revised_client import PUBLIC_REVISED_URL, fetch_selected
from .whats_new_detector import WhatsNewDetector
from .whats_new_downloader import download_pdf

log = logging.getLogger(__name__)


def _section(title):
    print(f'\n=== {title} ===', flush=True)


def _result_line(label, value):
    print(f'{label:<24} {value}', flush=True)


def _normal(value):
    return ' '.join(str(value or '').split())


def _baseline_comparisons(baseline, current):
    comparisons = [
        ('standard_id', baseline['standard_id'], current.get('observed_standard_id')),
        ('title', baseline['title'], current.get('title')),
    ]
    if baseline['publication_date']:
        comparisons.append(('publication_date', baseline['publication_date'], current.get('publication_date')))
    return comparisons


def _short_value(value, limit=72):
    text = _normal(value)
    return text if len(text) <= limit else text[:limit - 3] + '...'


def _merge_records(*records):
    """Merge non-empty source records, preferring the first source's values."""
    merged = {}
    sources = 0
    for record in records:
        if not record:
            continue
        sources += 1
        for key, value in record.items():
            if key not in merged or not merged[key]:
                merged[key] = value
            elif key == 'raw_text_excerpt' and value:
                merged[key] = value
    if sources > 1:
        merged['source_type'] = 'MERGED'
    return merged or None


class ChangeDetector:
    def __init__(self, settings):
        self.settings = settings
        self.db = Database(settings.database_url, ROOT)
        self._active_run_id = None

    def _fetch_whats_new_standards(self):
        """
        Fetch standards mentioned in BIS What's New page.
        
        Returns:
            dict: Mapping of standard_id to metadata (dates, titles, etc.)
                  Empty dict if disabled or fetch fails
        """
        if not self.settings.whats_new_enabled:
            print('What\'s New source       disabled', flush=True)
            return {}
        
        try:
            print('Fetching BIS What\'s New...', flush=True)
            detector = WhatsNewDetector(
                timeout=self.settings.request_timeout,
                retries=self.settings.retries,
                retry_base_seconds=self.settings.retry_base_seconds,
            )
            standards = detector.get_standards_from_whats_new(
                include_archive=self.settings.whats_new_include_archive,
                max_archive_pages=self.settings.whats_new_max_pages,
            )
            
            if standards:
                print(f'What\'s New standards    {len(standards)} found', flush=True)
                top_standards = sorted(
                    standards.items(),
                    key=lambda x: x[1]['count'],
                    reverse=True
                )[:5]
                for std_id, info in top_standards:
                    print(f'  {std_id:<22} {info["count"]} mention(s); latest {info["latest_date"]}', flush=True)
            else:
                print('What\'s New standards    none found', flush=True)
            
            return standards
        
        except Exception as e:
            log.error(f'What\'s New detector failed: {e}')
            return {}

    def _fetch_whats_new_entries(self):
        if not self.settings.whats_new_enabled:
            return []
        detector = WhatsNewDetector(
            timeout=self.settings.request_timeout,
            retries=self.settings.retries,
            retry_base_seconds=self.settings.retry_base_seconds,
        )
        return detector.get_all_entries(
            include_archive=self.settings.whats_new_include_archive,
            max_archive_pages=self.settings.whats_new_max_pages,
        )

    def _download_whats_new_pdfs(self, entries):
        if not self.settings.whats_new_download_pdfs:
            return 0
        downloaded = 0
        for entry in entries:
            if not entry.standard_id or entry.confidence != 'high':
                continue
            try:
                path, digest = download_pdf(
                    entry, self.settings.scraper_output_dir,
                    timeout=self.settings.request_timeout,
                )
                self.db.update_whats_new_artifact(entry.standard_id, path, digest)
                self.db.update_lifecycle_status(
                    entry.standard_id, 'DOCUMENT_RETRIEVED', 'DOWNLOADED', path, digest
                )
                downloaded += 1
                print(f'  Downloaded            {entry.standard_id} -> {path.name}', flush=True)
            except Exception as exc:
                log.warning("What's New PDF download skipped for %s: %s", entry.standard_id, exc)
        return downloaded

    def run_once(self, limit=None, reconcile=False):
        lock = FileLock(str(self.settings.lock_file), timeout=1)
        try:
            lock.acquire()
        except Timeout:
            log.warning('Another run is already in progress; skipping this cycle')
            return {'status': 'SKIPPED', 'selected': 0, 'checked': 0, 'failed': 0, 'changes': 0}
        try:
            return self._run(limit, reconcile=reconcile)
        except Exception as exc:
            if self._active_run_id:
                self.db.finish_run(
                    self._active_run_id, 'FAILED',
                    f'Unexpected {type(exc).__name__}: {exc}', 0,
                )
            raise
        finally:
            self._active_run_id = None
            lock.release()

    def _load_selected(self, limit):
        """Load selected standards from PDF directory (API path)."""
        paths = sorted(self.settings.selected_standards_dir.glob('*.pdf'))
        if limit is not None:
            paths = paths[:limit]
        records = []
        for path in paths:
            parsed = parse_artifact(path)
            if not parsed or 'No standard ID found' in parsed[0].get('extraction_warnings', []):
                log.warning('Skipping %s because no standard ID was extracted', path)
                continue
            record = parsed[0]
            record['row_fingerprint'] = row_fingerprint(record)
            records.append(record)
        return records

    def _run(self, limit, reconcile=False):
        """Check selected standards against BIS revised data and What's New evidence."""
        _section('BIS CHANGE DETECTION')
        _result_line('Selected PDF limit', limit if limit is not None else 'all')
        _result_line('Database', self.settings.database_url)
        _result_line('Archive pages', self.settings.whats_new_max_pages if self.settings.whats_new_include_archive else 'disabled')
        _result_line('Baseline reconcile', 'enabled' if reconcile else 'disabled')

        _section('1. BASELINE PDFs')
        selected_records = self._load_selected(limit)
        if not selected_records:
            raise RuntimeError(f'No PDFs with extractable standard IDs found in {self.settings.selected_standards_dir}')
        for record in selected_records:
            self.db.insert_baseline(record)
        if reconcile and limit is None:
            self.db.prune_missing_baselines(
                self.settings.selected_standards_dir.glob('*.pdf')
            )
        print(f'Loaded {len(selected_records)} baseline PDF(s)', flush=True)
        for record in selected_records:
            title = _short_value(record.get('title') or '(title unavailable)', 96)
            print(f'  {record["standard_id"]:<22} {title}', flush=True)

        selected = {record['standard_id']: record for record in selected_records}
        _section('2. WHAT\'S NEW')
        try:
            whats_new_entries = self._fetch_whats_new_entries()
            self.db.record_whats_new_entries(whats_new_entries)
            whats_new_standards = WhatsNewDetector.summarize_entries(whats_new_entries)
            print(f'What\'s New entries      {len(whats_new_entries)} saved', flush=True)
            confidence_counts = {level: sum(1 for entry in whats_new_entries if entry.confidence == level)
                                 for level in ('high', 'medium', 'low')}
            print('Confidence             ' + ', '.join(
                f'{level}={count}' for level, count in confidence_counts.items()
            ), flush=True)
            for entry in whats_new_entries:
                print(f'  [{entry.confidence.upper():6}] {entry.standard_id or "(no IS ID)"}: '
                      f'{_short_value(entry.title, 72)} | {entry.published_date or "no date"} | '
                      f'{entry.content_type} | {entry.url or "no URL"}', flush=True)
            if self.settings.whats_new_download_pdfs:
                print('PDF retrieval           enabled', flush=True)
                print(f'PDFs downloaded         {self._download_whats_new_pdfs(whats_new_entries)}', flush=True)
        except Exception:
            log.exception("What's New persistence failed")
            whats_new_entries = []
            whats_new_standards = {}
        selected_by_identity = {
            standard_identity(standard_id): standard_id for standard_id in selected
        }
        matching_whats_new = {
            selected_by_identity[standard_identity(standard_id)]: metadata
            for standard_id, metadata in whats_new_standards.items()
            if standard_identity(standard_id) in selected_by_identity
        }
        candidates = {
            standard_id for standard_id in whats_new_standards
            if standard_identity(standard_id) not in selected_by_identity
        }
        if candidates:
            print(f'New candidates not in selected PDFs: {len(candidates)}', flush=True)
            print('  ' + ', '.join(sorted(candidates)), flush=True)
            if self.settings.whats_new_download_pdfs:
                print('  Note: only high-confidence BIS PDFs are downloaded.', flush=True)
            else:
                print('  Note: candidates are reported only; no download is automatic.', flush=True)
            for candidate in candidates:
                self.db.update_lifecycle_status(candidate, 'DISCOVERED', 'PENDING')
        elif whats_new_standards:
            print('No new candidates outside selected PDFs', flush=True)

        _section('3. REVISED-STANDARDS SERVICE')
        print('Querying BIS revised-standards service...', flush=True)
        run_id = str(uuid.uuid4())
        self._active_run_id = run_id
        self.db.start_run(run_id, None)
        self.db.set_state('last_checked', datetime.now(timezone.utc).isoformat())
        candidate_ids = sorted(candidates)
        query_ids = list(selected) + candidate_ids
        try:
            revised = fetch_selected(
                query_ids, self.settings.request_timeout,
                retries=self.settings.retries,
                retry_base_seconds=self.settings.retry_base_seconds,
            )
        except Exception:
            log.exception('BIS revised-standards lookup failed')
            self.db.finish_run(run_id, 'CHECK_FAILED', 'Revised-standards endpoint failed', 0)
            print('BIS service            FAILED', flush=True)
            return {'status': 'CHECK_FAILED', 'selected': len(selected), 'checked': 0,
                    'failed': len(selected), 'changes': 0, 'whats_new': len(matching_whats_new)}

        selected_revised = {
            standard_id: item for standard_id, item in revised.items()
            if standard_id in selected
        }
        candidate_revised = {
            standard_id: item for standard_id, item in revised.items()
            if standard_id not in selected
        }
        failures = len(set(selected) - set(selected_revised))
        print(f'BIS records matched     {len(selected_revised)} selected; {len(candidate_revised)} candidates', flush=True)
        print(f'BIS records missing     {failures}', flush=True)
        for standard_id in matching_whats_new:
            self.db.update_lifecycle_status(
                standard_id, 'VERIFIED_IN_REVISED_LIST', 'VERIFIED'
            )
        for standard_id, revised_item in candidate_revised.items():
            current = revised_item.as_record()
            current['standard_id'] = standard_id
            current_fp = revision_fingerprint(current)
            self.db.insert_observation(current, current_fp)
            self.db.update_lifecycle_status(
                standard_id, 'VERIFIED_IN_REVISED_LIST', 'VERIFIED'
            )
            print(f'  New standard saved      {standard_id}', flush=True)
        changed_standards = {}

        def note_change(standard_id, field, old_value, new_value):
            details = changed_standards.setdefault(standard_id, [])
            if field == 'standard_id':
                details.append(f'ID: {_short_value(old_value)} -> {_short_value(new_value)}')
            elif field == 'title':
                details.append('title updated')
            else:
                details.append(f'{field} updated')

        checked = 0
        for standard_id, revised_item in selected_revised.items():
            current = revised_item.as_record()
            current['standard_id'] = standard_id
            if standard_id in matching_whats_new:
                current = _merge_records(current, {
                    'whats_new_titles': matching_whats_new[standard_id]['titles'],
                    'whats_new_latest_date': matching_whats_new[standard_id]['latest_date'],
                    'whats_new_count': matching_whats_new[standard_id]['count'],
                    'source_type': 'WHATS_NEW',
                })
            current_fp = revision_fingerprint(current)
            previous = self.db.latest_observation(standard_id)
            if previous is None:
                self.db.insert_observation(current, current_fp)
                checked += 1
                baseline = self.db.get_baselines([standard_id])[0]
                for field, old_value, new_value in _baseline_comparisons(baseline, current):
                    if _normal(old_value) == _normal(new_value):
                        continue
                    self.db.record_change(run_id, standard_id, field, old_value, new_value,
                                          baseline['fingerprint'], current_fp, PUBLIC_REVISED_URL,
                                          {'baseline_pdf': baseline['source_pdf'], 'type': 'BASELINE_VS_BIS_FIRST_CHECK'})
                    note_change(standard_id, field, old_value, new_value)
                continue

            checked += 1
            for field in REVISION_FIELDS:
                old_value = previous[field]
                new_value = current.get(field)
                if _normal(old_value) == _normal(new_value):
                    continue
                if not self.db.change_exists(standard_id, field, previous['fingerprint'], current_fp):
                    self.db.record_change(run_id, standard_id, field, old_value, new_value,
                                          previous['fingerprint'], current_fp, PUBLIC_REVISED_URL,
                                          {'aspect': current.get('aspect'), 'equivalence': current.get('equivalence'),
                                           'document_path': current.get('document_path')})
                    note_change(standard_id, field, old_value, new_value)
            self.db.insert_observation(current, current_fp)

        changes = len(changed_standards)
        status = 'NO_CHANGE' if not failures and not changes else ('CHANGE_DETECTED' if not failures else 'PARTIAL_FAILURE')
        message = (f'Selected: {len(selected)}; Checked: {checked}; '
               f'New candidates saved: {len(candidate_revised)}; '
               f'Failed: {failures}; Changes: {changes}')
        self.db.finish_run(run_id, status, message, checked + len(candidate_revised))
        log.info(message)
        _section('4. RESULT')
        _result_line('Selected', len(selected))
        _result_line('Checked', checked)
        _result_line('Failed', failures)
        _result_line('Changes', changes)
        _result_line('What\'s New matches', len(matching_whats_new))
        _result_line('What\'s New candidates', len(candidates))
        _result_line('New standards saved', len(candidate_revised))
        _result_line('Status', status)
        with self.db.conn() as connection:
            current_rows = connection.execute('''SELECT standard_id, latest_standard_id,
              latest_title, latest_publication_date FROM current_standards
              ORDER BY standard_id''').fetchall()
        print('Current standards:', flush=True)
        for row in current_rows:
            print(f'  {row["standard_id"]} -> {row["latest_standard_id"]}; '
              f'{_short_value(row["latest_title"] or "(no title)", 72)}; '
              f'{row["latest_publication_date"] or "no publication date"}', flush=True)
        if changed_standards:
            print('Changed standards:', flush=True)
            for standard_id, details in changed_standards.items():
                print(f'  {standard_id}: {", ".join(details)}', flush=True)
        return {'status': status, 'selected': len(selected), 'checked': checked, 'failed': failures,
                'changes': changes, 'changed_standards': changed_standards,
                'whats_new': len(matching_whats_new), 'whats_new_candidates': len(candidates),
                'new_standards_saved': len(candidate_revised)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Monitor selected PDFs against BIS revised standards')
    parser.add_argument('--limit', type=int, help='check only the first N selected PDFs')
    parser.add_argument('--reconcile', action='store_true',
                        help='explicitly remove baselines whose PDF no longer exists')
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    setup_logging(settings.log_dir)
    try:
        if args.reconcile and args.limit is not None:
            parser.error('--reconcile cannot be combined with --limit')
        result = ChangeDetector(settings).run_once(args.limit, reconcile=args.reconcile)
        return 0 if result['status'] in {'NO_CHANGE', 'CHANGE_DETECTED'} else 1
    except Exception:
        log.exception('Selected-standard cycle failed')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
