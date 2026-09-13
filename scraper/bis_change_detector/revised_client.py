import logging
import re
import random
import time
from dataclasses import dataclass

import requests

from .fingerprint import normalize_id

log = logging.getLogger(__name__)

DEPARTMENT_COUNT_URL = 'https://standardsadmin.bis.gov.in/master-service//getRevisedStandardsDepartmentCount'
REVISED_LIST_URL = 'https://standardsadmin.bis.gov.in/master-service//getRevisedStandardsList'
PUBLIC_REVISED_URL = 'https://standards.bis.gov.in/website/revised-standards'

# The department-count endpoint currently returns these IDs. They are also
# refreshed at runtime, so a BIS department addition is picked up automatically.
BASE_PAYLOAD = {
    'token': None,
    'refreshToken': None,
    'clientId': None,
    'clientSecret': None,
    'sub': None,
}


@dataclass(frozen=True)
class RevisedStandard:
    standard_id: str
    observed_standard_id: str
    title: str | None
    published_on: str | None
    aspect: str | None
    equivalence: str | None
    document_path: str | None
    source_url: str = PUBLIC_REVISED_URL

    def as_record(self):
        return {
            'standard_id': self.standard_id,
            'observed_standard_id': self.observed_standard_id,
            'title': self.title,
            'status': 'REVISED',
            'publication_date': self.published_on,
            'edition': None,
            'amendment': None,
            'reaffirmation': None,
            'scope': None,
            'source_url': self.source_url,
            'document_path': self.document_path,
            'aspect': self.aspect,
            'equivalence': self.equivalence,
        }


def _post(session, url, payload, timeout, retries=3, retry_base_seconds=2):
    for attempt in range(retries + 1):
        try:
            response = session.post(url, json=payload, timeout=timeout)
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            body = response.json()
            if body.get('status') != 'SUCCESS':
                raise RuntimeError(body.get('msg') or f'BIS revised endpoint failed: {url}')
            return body
        except (requests.RequestException, ValueError) as exc:
            if attempt >= retries:
                raise
            delay = retry_base_seconds * (2 ** attempt) + random.uniform(0, 0.5)
            log.warning('BIS request failed (%s), retrying in %.1fs', exc, delay)
            time.sleep(delay)


def _id_aliases(value):
    normalized = normalize_id(value)
    sectionless = re.sub(r'\s*\(PART\s+([0-9IVX]+)\s*/\s*SEC\s+[0-9IVX]+\)', r' (PART \1)', normalized, flags=re.I)
    compact = re.sub(r'\s+', '', normalized)
    part_form = re.sub(r'\s*\(PART\s+([0-9IVX]+)\)', r'-\1', normalized, flags=re.I)
    aliases = {normalized, sectionless, re.sub(r'\s+', '', part_form), re.sub(r'\s+', '', sectionless)}
    aliases.add(part_form)
    aliases.update(re.sub(r':\s*(?:19|20)\d{2}', '', alias).strip() for alias in list(aliases))
    identity = re.search(r'IS(?:/ISO(?:/IEC(?:/IEEE)?)?)?\s*:?[ ]*(\d{1,6})'
                         r'(?:\s*(?:\(\s*PART\s*([0-9IVX]+)\s*\)|[-/]\s*([0-9IVX]+)[A-Z]?))?',
                         normalized, re.I)
    if identity:
        part = identity.group(2) or identity.group(3)
        aliases.add(f'IS{identity.group(1)}-{part}' if part else f'IS{identity.group(1)}')
    if '8802-1' in compact:
        base = compact.replace('8802-1X', '8802-1')
        aliases.update({base, base.replace('8802-1', '8802-1X')})
    return aliases


def fetch_selected(selected_ids, timeout=45, per_page=1000, retries=3, retry_base_seconds=2):
    wanted = {normalize_id(value) for value in selected_ids}
    wanted_aliases = {alias: standard_id for standard_id in wanted for alias in _id_aliases(standard_id)}
    if not wanted:
        return {}
    session = requests.Session()
    session.headers.update({'Content-Type': 'application/json', 'User-Agent': 'BIS-Selected-Standards-Monitor/1.0'})
    count_payload = {'fromDate': '', 'toDate': '', 'departmentIds': [], **BASE_PAYLOAD}
    departments = _post(session, DEPARTMENT_COUNT_URL, count_payload, timeout, retries, retry_base_seconds).get('data', [])
    found = {}
    for department in departments:
        department_id = department.get('departmentId')
        total = int(department.get('totalStandards') or 0)
        pages = max(1, (total + per_page - 1) // per_page)
        for page in range(1, pages + 1):
            payload = {'departmentId': department_id, 'page': page, 'per_page': per_page, **BASE_PAYLOAD}
            rows = _post(session, REVISED_LIST_URL, payload, timeout, retries, retry_base_seconds).get('data', [])
            for row in rows:
                row_id = normalize_id(row.get('standardNumber'))
                matching_id = next((wanted_aliases[alias] for alias in _id_aliases(row_id)
                                    if alias in wanted_aliases), None)
                if matching_id:
                    found[matching_id] = RevisedStandard(
                        standard_id=matching_id,
                        observed_standard_id=row_id,
                        title=row.get('standardName'),
                        published_on=row.get('publishedOn'),
                        aspect=row.get('typeOfStandardName'),
                        equivalence=row.get('equivalenceTypeName'),
                        document_path=row.get('is_documents'),
                    )
            if len(found) == len(wanted):
                return found
    return found
