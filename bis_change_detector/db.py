import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()

class Database:
    def __init__(self, url: str, root: Path):
        if not url.startswith('sqlite:///'):
            raise ValueError('This build is SQLite-only. Use DATABASE_URL=sqlite:///./bis_monitor.db')
        raw = url[len('sqlite:///'):]
        self.path = Path(raw)
        if not self.path.is_absolute(): self.path = root / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=60)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA busy_timeout=60000')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback(); raise
        finally: c.close()

    def init_schema(self):
        with self.conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS monitor_state (
              key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS crawl_runs (
              run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
              tier1_hash TEXT, status TEXT NOT NULL, message TEXT, standards_processed INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS standards (
              standard_id TEXT PRIMARY KEY, title TEXT, status TEXT, last_amendment_date TEXT,
              publication_date TEXT, edition TEXT, scope TEXT, is_active INTEGER NOT NULL DEFAULT 1,
              row_fingerprint TEXT, page_fingerprint TEXT, source_artifact TEXT, raw_text_excerpt TEXT,
              extraction_warnings TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS standard_delta_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, standard_id TEXT NOT NULL,
              change_type TEXT NOT NULL, old_fingerprint TEXT, new_fingerprint TEXT,
              old_status TEXT, new_status TEXT, created_at TEXT NOT NULL, details TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_delta_run ON standard_delta_log(run_id);
            CREATE INDEX IF NOT EXISTS idx_standard_active ON standards(is_active);
            ''')

    def state(self, key):
        with self.conn() as c:
            r=c.execute('SELECT value FROM monitor_state WHERE key=?',(key,)).fetchone()
            return r['value'] if r else None
    def set_state(self,key,value):
        with self.conn() as c:
            c.execute('INSERT INTO monitor_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at',(key,value,now()))
    def start_run(self, run_id, tier1_hash):
        with self.conn() as c: c.execute('INSERT INTO crawl_runs(run_id,started_at,tier1_hash,status) VALUES(?,?,?,?)',(run_id,now(),tier1_hash,'RUNNING'))
    def finish_run(self, run_id, status, message='', count=0):
        with self.conn() as c: c.execute('UPDATE crawl_runs SET finished_at=?,status=?,message=?,standards_processed=? WHERE run_id=?',(now(),status,message,count,run_id))
    def get_standards(self):
        with self.conn() as c: return c.execute('SELECT * FROM standards').fetchall()
    def get_by_ids(self, ids):
        if not ids: return []
        q=','.join('?'*len(ids))
        with self.conn() as c: return c.execute(f'SELECT * FROM standards WHERE standard_id IN ({q})',list(ids)).fetchall()
    def upsert_standard(self, run_id, rec):
        with self.conn() as c:
            old=c.execute('SELECT * FROM standards WHERE standard_id=?',(rec['standard_id'],)).fetchone()
            ts=now()
            if old is None:
                c.execute('''INSERT INTO standards(standard_id,title,status,last_amendment_date,publication_date,edition,scope,is_active,row_fingerprint,page_fingerprint,source_artifact,raw_text_excerpt,extraction_warnings,first_seen_at,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',tuple(rec.get(k) for k in ['standard_id','title','status','last_amendment_date','publication_date','edition','scope'])+(1,rec.get('row_fingerprint'),rec.get('page_fingerprint'),rec.get('source_artifact'),rec.get('raw_text_excerpt'),json.dumps(rec.get('extraction_warnings',[])),ts,ts,ts))
                self._delta(c,run_id,rec['standard_id'],'NEW',None,rec.get('row_fingerprint'),None,rec.get('status'))
                return 'NEW'
            change = old['row_fingerprint'] != rec.get('row_fingerprint') or old['is_active']==0
            c.execute('''UPDATE standards SET title=?,status=?,last_amendment_date=?,publication_date=?,edition=?,scope=?,is_active=1,row_fingerprint=?,page_fingerprint=?,source_artifact=?,raw_text_excerpt=?,extraction_warnings=?,last_seen_at=?,updated_at=? WHERE standard_id=?''',(rec.get('title'),rec.get('status'),rec.get('last_amendment_date'),rec.get('publication_date'),rec.get('edition'),rec.get('scope'),rec.get('row_fingerprint'),rec.get('page_fingerprint'),rec.get('source_artifact'),rec.get('raw_text_excerpt'),json.dumps(rec.get('extraction_warnings',[])),ts,ts,rec['standard_id']))
            if change: self._delta(c,run_id,rec['standard_id'],'UPDATED',old['row_fingerprint'],rec.get('row_fingerprint'),old['status'],rec.get('status'))
            return 'UPDATED' if change else 'UNCHANGED'
    def mark_removed(self, run_id, expected_ids):
        with self.conn() as c:
            rows=c.execute('SELECT standard_id,row_fingerprint,status FROM standards WHERE is_active=1').fetchall()
            expected=set(expected_ids)
            for r in rows:
                if r['standard_id'] not in expected:
                    c.execute('UPDATE standards SET is_active=0,status=?,updated_at=? WHERE standard_id=?',('WITHDRAWN',now(),r['standard_id']))
                    self._delta(c,run_id,r['standard_id'],'WITHDRAWN',r['row_fingerprint'],r['row_fingerprint'],r['status'],'WITHDRAWN')
    def _delta(self,c,*args):
        run_id,sid,typ,oldfp,newfp,olds,news=args
        c.execute('INSERT INTO standard_delta_log(run_id,standard_id,change_type,old_fingerprint,new_fingerprint,old_status,new_status,created_at) VALUES(?,?,?,?,?,?,?,?)',(run_id,sid,typ,oldfp,newfp,olds,news,now()))
