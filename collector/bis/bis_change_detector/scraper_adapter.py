import os, shutil, subprocess, sys, tempfile, logging
from pathlib import Path
from openpyxl import Workbook

log=logging.getLogger(__name__)

class ScraperAdapter:
    def __init__(self, settings): self.s=settings
    def run_for_ids(self, ids):
        if not ids: return []
        # Fail naming the path that was actually tried. The legacy scraper
        # was briefly nested inside sql/, which left this pointing at
        # nothing and surfaced as an unexplained subprocess error several
        # layers up.
        if not self.s.scraper_script.exists():
            raise FileNotFoundError(
                f'Legacy scraper not found at {self.s.scraper_script}. '
                f'Set SCRAPER_SCRIPT in collectors/bis/.env, or put '
                f'download_standards.py in {self.s.scraper_cwd}.')
        with tempfile.TemporaryDirectory(prefix='bis_scrape_') as td:
            work=Path(td); shutil.copy2(self.s.scraper_script,work/'download_standards.py')
            wb=Workbook(); ws=wb.active; ws.title='Sheet1'; ws.append(['IS_Number'])
            for sid in ids: ws.append([sid])
            wb.save(work/'Book 2.xlsx'); (work/'downloads').mkdir()
            env=os.environ.copy()
            proc=subprocess.run([sys.executable,'download_standards.py'],cwd=work,env=env,text=True,capture_output=True,timeout=self.s.scraper_timeout)
            log.info('Existing scraper exit=%s\n%s',proc.returncode,proc.stdout[-5000:])
            if proc.stderr: log.warning('Scraper stderr:\n%s',proc.stderr[-5000:])
            files=list((work/'downloads').glob('*'))
            if proc.returncode != 0: raise RuntimeError(f'Existing scraper failed with exit code {proc.returncode}')
            # Copy artifacts out before temp directory disappears.
            self.s.scraper_output_dir.mkdir(parents=True,exist_ok=True)
            copied=[]
            for f in files:
                dest=self.s.scraper_output_dir/(f'{f.stem}_{os.getpid()}_{len(copied)}{f.suffix}')
                shutil.copy2(f,dest); copied.append(dest)
            return copied
