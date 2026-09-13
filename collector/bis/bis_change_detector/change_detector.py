import logging, uuid, time
from filelock import FileLock, Timeout
from .config import Settings, ROOT
from .logging_config import setup_logging
from .db import Database
from .page_hasher import fetch_normalized
from .discovery import discover
from .scraper_adapter import ScraperAdapter
from .artifact_parser import parse_artifact
from .fingerprint import row_fingerprint

log=logging.getLogger(__name__)

class ChangeDetector:
    def __init__(self,s):
        self.s=s; self.db=Database(s.database_url,ROOT); self.scraper=ScraperAdapter(s)
    def run_once(self):
        lock=FileLock(str(self.s.lock_file),timeout=1)
        try: lock.acquire()
        except Timeout: log.warning('Another crawl is already running; skipping this cycle'); return
        try: return self._run()
        finally: lock.release()
    def _run(self):
        tier1,text,soup=fetch_normalized(self.s.monitored_url,self.s.request_timeout)
        old=self.db.state('tier1_hash'); run_id=str(uuid.uuid4()); self.db.start_run(run_id,tier1)
        self.db.set_state('last_checked',__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
        if old==tier1:
            log.info('No changes detected')
            self.db.finish_run(run_id,'NO_CHANGE','Tier-1 hash unchanged',0); return {'status':'NO_CHANGE'}
        ids_map, discovery_complete = discover(soup) if self.s.discovery_enabled else ({}, False)
        dbrows={r['standard_id']:r for r in self.db.get_standards()}
        if ids_map:
            # New IDs or IDs whose visible page row changed. On first run, scrape all discovered IDs.
            if not dbrows: target=list(ids_map)
            else: target=[sid for sid,sig in ids_map.items() if sid not in dbrows or dbrows[sid]['page_fingerprint']!=sig]
            expected=set(ids_map)
        else:
            # Safe fallback: use existing workbook, but only first run or if page discovery is unavailable.
            if not self.s.scraper_input_file.exists(): raise RuntimeError('Could not discover standard IDs from monitored page and Book 2.xlsx is missing')
            from openpyxl import load_workbook
            wb=load_workbook(self.s.scraper_input_file,read_only=True,data_only=True); ws=wb.active
            target=[]
            for row in ws.iter_rows(min_row=2,values_only=True):
                if row and row[0]: target.append(str(row[0]).strip())
            target = target if not dbrows else []
            expected=set(dbrows) | set(target)
        log.info('Tier-2 required. Standards selected for download: %d',len(target))
        if not target:
            # Page changed but no standard row changed. Advance hash safely.
            self.db.set_state('tier1_hash',tier1); self.db.finish_run(run_id,'PAGE_CHANGE_NO_STANDARD_CHANGE','Page changed outside discovered standard rows',0); return {'status':'PAGE_CHANGE_NO_STANDARD_CHANGE'}
        artifacts=self.scraper.run_for_ids(target)
        records=[]
        for a in artifacts:
            records.extend(parse_artifact(a))
        byid={r['standard_id']:r for r in records}
        for sid in target:
            if sid not in byid: log.warning('No parsed artifact found for %s',sid)
        for sid,rec in byid.items():
            rec['row_fingerprint']=row_fingerprint(rec)
            rec['page_fingerprint']=ids_map.get(sid)
            self.db.upsert_standard(run_id,rec)
        # Only infer withdrawals if we have a complete, non-empty discovery set.
        if ids_map and discovery_complete and all(sid in byid or sid in dbrows for sid in expected): self.db.mark_removed(run_id,expected)
        self.db.set_state('tier1_hash',tier1)
        self.db.finish_run(run_id,'SUCCESS',f'{len(records)} structured records',len(records))
        return {'status':'SUCCESS','processed':len(records)}

def main():
    s=Settings.from_env(); setup_logging(s.log_dir); d=ChangeDetector(s)
    back=s.retry_base_seconds
    for attempt in range(s.retries):
        try: d.run_once(); return 0
        except Exception as e:
            log.exception('Cycle failed attempt %d/%d',attempt+1,s.retries)
            if attempt+1<s.retries: time.sleep(min(back,300)); back*=2
    return 1
if __name__=='__main__': raise SystemExit(main())
