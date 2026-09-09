from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


def path(v: str | None, default: str) -> Path:
    p = Path(v or default)
    return p if p.is_absolute() else ROOT / p

@dataclass(frozen=True)
class Settings:
    database_url: str
    monitored_url: str
    scraper_script: Path
    scrapy_spider: Path
    scraper_cwd: Path
    scraper_input_file: Path
    scraper_output_dir: Path
    selected_standards_dir: Path
    state_dir: Path
    log_dir: Path
    lock_file: Path
    check_interval_hours: float = 1.0
    request_timeout: int = 45
    scraper_timeout: int = 3600
    retries: int = 3
    retry_base_seconds: int = 10

    @classmethod
    def from_env(cls):
        required = ['MONITORED_URL', 'SCRAPER_SCRIPT']
        missing = [x for x in required if not os.getenv(x)]
        if missing:
            raise RuntimeError('Missing required environment variables: ' + ', '.join(missing))
        scraper_cwd = path(os.getenv('SCRAPER_CWD'), 'legacy_scraper')
        scraper_input = path(os.getenv('SCRAPER_INPUT_FILE'), 'legacy_scraper/Book 2.xlsx')
        return cls(
            database_url=os.getenv('DATABASE_URL', 'sqlite:///./bis_monitor.db'),
            monitored_url=os.environ['MONITORED_URL'],
            scraper_script=path(os.environ['SCRAPER_SCRIPT'], 'legacy_scraper/download_standards.py'),
            scrapy_spider=path(os.getenv('SCRAPY_SPIDER'), 'bis_change_detector/selected_spider.py'),
            scraper_cwd=scraper_cwd,
            scraper_input_file=scraper_input,
            scraper_output_dir=path(os.getenv('SCRAPER_OUTPUT_DIR'), 'downloads'),
            selected_standards_dir=path(os.getenv('SELECTED_STANDARDS_DIR'), 'selected_standards'),
            state_dir=path(os.getenv('STATE_DIR'), 'state'),
            log_dir=path(os.getenv('LOG_DIR'), 'logs'),
            lock_file=path(os.getenv('LOCK_FILE'), 'state/change_detector.lock'),
            check_interval_hours=float(os.getenv('CHECK_INTERVAL_HOURS', '1')),
            request_timeout=int(os.getenv('REQUEST_TIMEOUT_SECONDS', '45')),
            scraper_timeout=int(os.getenv('SCRAPER_TIMEOUT_SECONDS', '3600')),
            retries=int(os.getenv('RETRIES', '3')),
            retry_base_seconds=int(os.getenv('RETRY_BASE_SECONDS', '10')),
        )
