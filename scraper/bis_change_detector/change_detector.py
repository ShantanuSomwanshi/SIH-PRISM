import argparse
import logging
import uuid
from datetime import datetime, timezone

from filelock import FileLock, Timeout

from .artifact_parser import parse_artifact
from .config import ROOT, Settings
from .db import Database
from .fingerprint import REVISION_FIELDS, revision_fingerprint, row_fingerprint
from .logging_config import setup_logging
from .revised_client import PUBLIC_REVISED_URL, fetch_selected

log = logging.getLogger(__name__)


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


class ChangeDetector:
    def __init__(self, settings):
        self.settings = settings
        self.db = Database(settings.database_url, ROOT)

    def run_once(self, limit=None):
        lock = FileLock(str(self.settings.lock_file), timeout=1)
        try:
            lock.acquire()
        except Timeout:
            log.warning('Another selected-standard run is already running; skipping')
            return {'status': 'SKIPPED', 'selected': 0, 'checked': 0, 'failed': 0, 'changes': 0}
        try:
            return self._run(limit)
        finally:
            lock.release()

    def _load_selected(self, limit):
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
        self.db.prune_missing_baselines(paths, [record['standard_id'] for record in records])
        return records

    def _run(self, limit):
        selected_records = self._load_selected(limit)
        if not selected_records:
            raise RuntimeError(f'No PDFs with extractable standard IDs found in {self.settings.selected_standards_dir}')
        for record in selected_records:
            self.db.insert_baseline(record)

        selected = {record['standard_id']: record for record in selected_records}
        run_id = str(uuid.uuid4())
        self.db.start_run(run_id, None)
        self.db.set_state('last_checked', datetime.now(timezone.utc).isoformat())
        try:
            revised = fetch_selected(list(selected), self.settings.request_timeout)
        except Exception:
            log.exception('BIS revised-standards lookup failed')
            self.db.finish_run(run_id, 'CHECK_FAILED', 'Revised-standards endpoint failed', 0)
            return {'status': 'CHECK_FAILED', 'selected': len(selected), 'checked': 0, 'failed': len(selected), 'changes': 0}

        failures = len(set(selected) - set(revised))
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
        for standard_id, revised_item in revised.items():
            current = revised_item.as_record()
            current['standard_id'] = standard_id
            current_fp = revision_fingerprint(current)
            previous = self.db.latest_observation(standard_id)
            if previous is None:
                self.db.insert_observation(current, current_fp)
                checked += 1
                baseline = self.db.get_baselines([standard_id])[0]
                for field, old_value, new_value in _baseline_comparisons(baseline, current):
                    if _normal(old_value) == _normal(new_value):
                        continue
                    self.db.record_change(
                        run_id, standard_id, field, old_value, new_value, baseline['fingerprint'],
                        current_fp, PUBLIC_REVISED_URL,
                        {'baseline_pdf': baseline['source_pdf'], 'type': 'BASELINE_VS_BIS_FIRST_CHECK'},
                    )
                    note_change(standard_id, field, old_value, new_value)
                if standard_id in changed_standards:
                    log.info('%s: older baseline compared with newer BIS revised row', standard_id)
                log.info('%s: baseline revision state established', standard_id)
                continue

            checked += 1
            for field in REVISION_FIELDS:
                old_value = previous[field]
                new_value = current.get(field)
                if ' '.join(str(old_value or '').split()) == ' '.join(str(new_value or '').split()):
                    continue
                if not self.db.change_exists(standard_id, field, previous['fingerprint'], current_fp):
                    self.db.record_change(
                        run_id, standard_id, field, old_value, new_value,
                        previous['fingerprint'], current_fp, PUBLIC_REVISED_URL,
                        {'aspect': current.get('aspect'), 'equivalence': current.get('equivalence'),
                         'document_path': current.get('document_path')},
                    )
                    note_change(standard_id, field, old_value, new_value)
            self.db.insert_observation(current, current_fp)

        changes = len(changed_standards)
        status = 'NO_CHANGE' if not failures and not changes else ('CHANGE_DETECTED' if not failures else 'PARTIAL_FAILURE')
        message = f'Selected: {len(selected)}; Checked: {checked}; Failed: {failures}; Changes: {changes}'
        self.db.finish_run(run_id, status, message, checked)
        log.info(message)
        log.info('Status: %s', status)
        return {'status': status, 'selected': len(selected), 'checked': checked, 'failed': failures,
            'changes': changes, 'changed_standards': changed_standards}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Monitor selected PDFs against BIS revised standards')
    parser.add_argument('--limit', type=int, help='check only the first N selected PDFs')
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    setup_logging(settings.log_dir)
    try:
        result = ChangeDetector(settings).run_once(args.limit)
        for key in ('selected', 'checked', 'failed', 'changes'):
            print(f'{key.title()}: {result[key]}')
        if result.get('changed_standards'):
            print('Changed standards:')
            for standard_id, details in result['changed_standards'].items():
                print(f'  {standard_id}: {", ".join(details)}')
        print(f"Status: {result['status']}")
        return 0 if result['status'] in {'NO_CHANGE', 'CHANGE_DETECTED'} else 1
    except Exception:
        log.exception('Selected-standard cycle failed')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
