import os, shutil, subprocess, sys, tempfile, logging, time
from pathlib import Path
from openpyxl import Workbook

log=logging.getLogger(__name__)

class ScraperAdapter:
    def __init__(self, settings): self.s=settings
    def run_for_ids(self, ids):
        if not ids: return []
        self._scrapy_gate(ids)
        with tempfile.TemporaryDirectory(prefix='bis_scrape_') as td:
            work=Path(td); shutil.copy2(self.s.scraper_script,work/'download_standards.py')
            wb=Workbook(); ws=wb.active; ws.title='Sheet1'; ws.append(['IS_Number'])
            for sid in ids: ws.append([sid])
            wb.save(work/'Book 2.xlsx'); (work/'downloads').mkdir()
            env=os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            env['BIS_WAIT_SECONDS'] = str(min(10, max(5, self.s.request_timeout // 5)))
            proc=subprocess.Popen([sys.executable,'-u','download_standards.py'],cwd=work,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=1)
            started = time.monotonic()
            output = []
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    output.append(line)
                    print(f'[Selenium] {line}', flush=True)
                    if time.monotonic() - started > self.s.scraper_timeout:
                        proc.kill()
                        raise subprocess.TimeoutExpired(proc.args, self.s.scraper_timeout)
                return_code = proc.wait()
            except Exception:
                proc.kill()
                proc.wait()
                raise
            log.info('Existing scraper exit=%s', return_code)
            files=list((work/'downloads').glob('*'))
            if return_code != 0: raise RuntimeError(f'Existing scraper failed with exit code {return_code}')
            # Copy artifacts out before temp directory disappears.
            self.s.scraper_output_dir.mkdir(parents=True,exist_ok=True)
            copied=[]
            for f in files:
                dest=self.s.scraper_output_dir/(f'{f.stem}_{os.getpid()}_{len(copied)}{f.suffix}')
                shutil.copy2(f,dest); copied.append(dest)
            if not copied:
                print('[Selenium] No BIS artifact was downloaded for the selected standards', flush=True)
            return copied

    def _scrapy_gate(self, ids):
        """Use Scrapy for scoped requests/retries before Selenium performs UI work."""
        env = os.environ.copy()
        env['BIS_SELECTED_IDS'] = ','.join(ids)
        proc = subprocess.run(
            [sys.executable, '-m', 'scrapy', 'runspider', str(self.s.scrapy_spider),
             '-a', f'start_url={self.s.monitored_url}', '-s', 'LOG_ENABLED=False'],
            env=env, text=True, capture_output=True, timeout=self.s.request_timeout,
        )
        if proc.stdout:
            for line in proc.stdout.splitlines():
                print(f'[Scrapy] {line}', flush=True)
        if proc.returncode != 0:
            raise RuntimeError(f'Scrapy selected-standard request failed: {proc.stderr[-2000:]}')
