import logging
from pathlib import Path

def setup_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        handlers=[logging.StreamHandler(), logging.FileHandler(log_dir / 'bis_change_detector.log', encoding='utf-8')],
        force=True,
    )
