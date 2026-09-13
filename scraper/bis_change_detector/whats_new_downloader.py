"""Controlled downloader for BIS What's New PDF artifacts."""

import hashlib
from pathlib import Path
from urllib.parse import urlparse

import requests

from .whats_new_detector import WhatsNewEntry


class WhatsNewDownloadError(RuntimeError):
    """Raised when a What's New artifact fails validation."""


def download_pdf(entry: WhatsNewEntry, output_dir: Path, timeout: int = 45,
                 max_bytes: int = 25 * 1024 * 1024) -> tuple[Path, str]:
    """Download one verified BIS-hosted PDF using an immutable hash filename."""
    if not entry.url:
        raise WhatsNewDownloadError('entry has no URL')
    if entry.confidence != 'high':
        raise WhatsNewDownloadError(f'entry confidence is {entry.confidence}, not high')
    parsed = urlparse(entry.url)
    if parsed.scheme != 'https' or parsed.netloc.lower() not in {
        'bis.gov.in', 'www.bis.gov.in'
    }:
        raise WhatsNewDownloadError(f'URL is not a BIS HTTPS URL: {entry.url}')
    if entry.content_type.lower() != 'pdf' and not parsed.path.lower().endswith('.pdf'):
        raise WhatsNewDownloadError(f'entry is not a PDF: {entry.url}')

    response = requests.get(
        entry.url,
        timeout=timeout,
        headers={'User-Agent': 'BIS-Standards-Monitor/1.0'},
        stream=True,
    )
    response.raise_for_status()
    content_length = int(response.headers.get('Content-Length') or 0)
    if content_length > max_bytes:
        raise WhatsNewDownloadError('PDF exceeds configured size limit')

    digest = hashlib.sha256()
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=1024 * 128):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise WhatsNewDownloadError('PDF exceeds configured size limit')
        digest.update(chunk)
        chunks.append(chunk)
    content = b''.join(chunks)
    if not content.startswith(b'%PDF-'):
        raise WhatsNewDownloadError('response is not a PDF')

    output_dir.mkdir(parents=True, exist_ok=True)
    standard = (entry.standard_id or 'unknown').replace('/', '_').replace(' ', '_')
    destination = output_dir / f'{standard}_{digest.hexdigest()[:16]}.pdf'
    if not destination.exists():
        temporary = destination.with_suffix('.part')
        temporary.write_bytes(content)
        temporary.replace(destination)
    return destination, digest.hexdigest()
