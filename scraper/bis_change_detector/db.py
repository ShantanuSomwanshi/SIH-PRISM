import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, url: str, root: Path):
        if not url.startswith('sqlite:///'):
            raise ValueError('This build is SQLite-only. Use DATABASE_URL=sqlite:///./bis_monitor.db')
        raw = url[len('sqlite:///'):]
        self.path = Path(raw)
        if not self.path.is_absolute():
            self.path = root / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def conn(self):
        connection = sqlite3.connect(self.path, timeout=60)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA busy_timeout=60000')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init_schema(self):
        with self.conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS monitor_state (
              key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS crawl_runs (
              run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
              tier1_hash TEXT, status TEXT NOT NULL, message TEXT,
              standards_processed INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS baseline_standards (
              standard_id TEXT PRIMARY KEY, title TEXT, status TEXT,
              last_amendment_date TEXT, publication_date TEXT, amendment TEXT,
              reaffirmation TEXT, edition TEXT, scope TEXT,
              fingerprint TEXT NOT NULL, source_pdf TEXT NOT NULL,
              raw_text_excerpt TEXT, extraction_warnings TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS standard_versions (
              id INTEGER PRIMARY KEY AUTOINCREMENT, standard_id TEXT NOT NULL,
              version_type TEXT NOT NULL, title TEXT, status TEXT,
              last_amendment_date TEXT, publication_date TEXT, amendment TEXT,
              reaffirmation TEXT, edition TEXT, scope TEXT, aspect TEXT,
              equivalence TEXT, fingerprint TEXT NOT NULL, source_url TEXT,
              source_artifact TEXT, document_path TEXT, observed_at TEXT NOT NULL,
              UNIQUE(standard_id, fingerprint)
            );
            CREATE TABLE IF NOT EXISTS current_standards (
              standard_id TEXT PRIMARY KEY, version_id INTEGER NOT NULL,
              fingerprint TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS standard_changes (
              id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
              standard_id TEXT NOT NULL, changed_field TEXT NOT NULL,
              old_value TEXT, new_value TEXT, old_fingerprint TEXT NOT NULL,
              new_fingerprint TEXT NOT NULL, bis_source_url TEXT,
              details TEXT, detected_at TEXT NOT NULL,
              UNIQUE(standard_id, changed_field, old_fingerprint, new_fingerprint)
            );
            CREATE TABLE IF NOT EXISTS standard_subscriptions (
              id INTEGER PRIMARY KEY AUTOINCREMENT, standard_id TEXT NOT NULL,
              recipient TEXT NOT NULL, channel TEXT NOT NULL DEFAULT 'email',
              enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
              UNIQUE(standard_id, recipient, channel)
            );
            CREATE TABLE IF NOT EXISTS notifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT, change_id INTEGER,
              standard_id TEXT NOT NULL, recipient TEXT NOT NULL,
              channel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
              created_at TEXT NOT NULL, sent_at TEXT, details TEXT,
              UNIQUE(change_id, recipient, channel)
            );
            CREATE INDEX IF NOT EXISTS idx_versions_standard
              ON standard_versions(standard_id, observed_at);
            CREATE INDEX IF NOT EXISTS idx_changes_standard
              ON standard_changes(standard_id, detected_at);
            ''')
            try:
                c.execute('ALTER TABLE standard_versions ADD COLUMN observed_standard_id TEXT')
            except sqlite3.OperationalError:
                pass
            c.execute('''DELETE FROM standard_versions
              WHERE version_type='BASELINE'
                AND id NOT IN (
                  SELECT v.id
                  FROM standard_versions v
                  JOIN baseline_standards b
                    ON b.standard_id=v.standard_id AND b.fingerprint=v.fingerprint
                  WHERE v.version_type='BASELINE'
                )''')

    def set_state(self, key, value):
        with self.conn() as c:
            c.execute('''INSERT INTO monitor_state(key,value,updated_at) VALUES(?,?,?)
              ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at''',
                      (key, value, now()))

    def start_run(self, run_id, tier1_hash):
        with self.conn() as c:
            c.execute('''INSERT INTO crawl_runs(run_id,started_at,tier1_hash,status)
              VALUES(?,?,?,?)''', (run_id, now(), tier1_hash, 'RUNNING'))

    def finish_run(self, run_id, status, message='', count=0):
        with self.conn() as c:
            c.execute('''UPDATE crawl_runs SET finished_at=?, status=?, message=?,
              standards_processed=? WHERE run_id=?''',
                      (now(), status, message, count, run_id))

    def insert_baseline(self, record):
        with self.conn() as c:
            c.execute('''INSERT INTO baseline_standards
              (standard_id,title,status,last_amendment_date,publication_date,amendment,
               reaffirmation,edition,scope,fingerprint,source_pdf,raw_text_excerpt,
               extraction_warnings,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(standard_id) DO NOTHING''',
                      (record['standard_id'], record.get('title'), record.get('status'),
                       record.get('last_amendment_date'), record.get('publication_date'),
                       record.get('amendment'), record.get('reaffirmation'), record.get('edition'),
                       record.get('scope'), record['row_fingerprint'], record.get('source_artifact'),
                       record.get('raw_text_excerpt'), json.dumps(record.get('extraction_warnings', [])), now()))
            baseline = c.execute('''SELECT * FROM baseline_standards WHERE standard_id=?''',
                                  (record['standard_id'],)).fetchone()
            c.execute('''INSERT OR IGNORE INTO standard_versions
              (standard_id,version_type,title,status,last_amendment_date,publication_date,
               amendment,reaffirmation,edition,scope,fingerprint,source_artifact,observed_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (baseline['standard_id'], 'BASELINE', baseline['title'], baseline['status'],
                       baseline['last_amendment_date'], baseline['publication_date'],
                       baseline['amendment'], baseline['reaffirmation'], baseline['edition'],
                       baseline['scope'], baseline['fingerprint'], baseline['source_pdf'], now()))

    def prune_missing_baselines(self, source_paths, selected_ids=None):
        paths = {str(Path(path).resolve()) for path in source_paths}
        selected_ids = set(selected_ids or ())
        with self.conn() as c:
            rows = c.execute('SELECT standard_id, source_pdf FROM baseline_standards').fetchall()
            removed = []
            for row in rows:
                if (str(Path(row['source_pdf']).resolve()) not in paths or
                  (selected_ids and row['standard_id'] not in selected_ids)):
                    removed.append(row['standard_id'])
                    c.execute('DELETE FROM baseline_standards WHERE standard_id=?', (row['standard_id'],))
                    c.execute('DELETE FROM standard_versions WHERE standard_id=? AND version_type=?',
                              (row['standard_id'], 'BASELINE'))
                    c.execute('DELETE FROM current_standards WHERE standard_id=?', (row['standard_id'],))
            return removed

    def latest_observation(self, standard_id):
        with self.conn() as c:
            return c.execute('''SELECT * FROM standard_versions
              WHERE standard_id=? AND version_type='BIS_REVISED_LIST'
              ORDER BY observed_at DESC, id DESC LIMIT 1''', (standard_id,)).fetchone()

    def get_baselines(self, ids=None):
        with self.conn() as c:
            if not ids:
                return c.execute('SELECT * FROM baseline_standards').fetchall()
            placeholders = ','.join('?' * len(ids))
            return c.execute(
                f'SELECT * FROM baseline_standards WHERE standard_id IN ({placeholders})',
                list(ids),
            ).fetchall()

    def insert_observation(self, record, fingerprint):
        with self.conn() as c:
            c.execute('''INSERT OR IGNORE INTO standard_versions
              (standard_id,version_type,title,status,last_amendment_date,publication_date,
               amendment,reaffirmation,edition,scope,aspect,equivalence,observed_standard_id,fingerprint,
               source_url,document_path,observed_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (record['standard_id'], 'BIS_REVISED_LIST', record.get('title'), record.get('status'),
                       record.get('last_amendment_date'), record.get('publication_date'),
                       record.get('amendment'), record.get('reaffirmation'), record.get('edition'),
                       record.get('scope'), record.get('aspect'), record.get('equivalence'),
                       record.get('observed_standard_id'), fingerprint,
                       record.get('source_url'), record.get('document_path'), now()))
            version = c.execute('''SELECT id FROM standard_versions
              WHERE standard_id=? AND fingerprint=?''',
              (record['standard_id'], fingerprint)).fetchone()
            c.execute('''INSERT INTO current_standards(standard_id,version_id,fingerprint,updated_at)
              VALUES(?,?,?,?) ON CONFLICT(standard_id) DO UPDATE SET
              version_id=excluded.version_id, fingerprint=excluded.fingerprint,
              updated_at=excluded.updated_at''',
              (record['standard_id'], version['id'], fingerprint, now()))

    def change_exists(self, standard_id, field, old_fingerprint, new_fingerprint):
        with self.conn() as c:
            return c.execute('''SELECT 1 FROM standard_changes
              WHERE standard_id=? AND changed_field=? AND old_fingerprint=? AND new_fingerprint=?''',
                      (standard_id, field, old_fingerprint, new_fingerprint)).fetchone() is not None

    def record_change(self, run_id, standard_id, field, old_value, new_value,
                      old_fingerprint, new_fingerprint, source_url, details):
        with self.conn() as c:
            c.execute('''INSERT OR IGNORE INTO standard_changes
              (run_id,standard_id,changed_field,old_value,new_value,old_fingerprint,
               new_fingerprint,bis_source_url,details,detected_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)''',
                      (run_id, standard_id, field, old_value, new_value, old_fingerprint,
                       new_fingerprint, source_url, json.dumps(details, sort_keys=True), now()))

    def add_notification_placeholders(self, change_id, standard_id):
        with self.conn() as c:
            recipients = c.execute('''SELECT recipient,channel FROM standard_subscriptions
              WHERE standard_id=? AND enabled=1''', (standard_id,)).fetchall()
            for recipient in recipients:
                c.execute('''INSERT OR IGNORE INTO notifications
                  (change_id,standard_id,recipient,channel,status,created_at)
                  VALUES(?,?,?,?,?,?)''',
                          (change_id, standard_id, recipient['recipient'], recipient['channel'],
                           'PENDING', now()))
