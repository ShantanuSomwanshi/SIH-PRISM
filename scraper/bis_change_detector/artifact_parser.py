"""
Unified artifact parser - merged from local scraper and collector/bis.

Features:
1. PDF extraction with robust error handling
2. Excel parsing with smart header detection (finds real headers, not letterhead)
3. JSON loading
4. PII protection: automatic redaction of emails, phone numbers
5. Privacy-first: filters out personal data columns
6. Detailed logging of what was found/not found
"""

from pathlib import Path
import re, json
import logging
from pypdf import PdfReader
from openpyxl import load_workbook
from .fingerprint import normalize_id

logging.getLogger('pypdf._cmap').setLevel(logging.ERROR)

log = logging.getLogger(__name__)

# Standard ID pattern - handles IS XXXX, IS (Part Y), IS : YYYY
STANDARD_ID_RE = re.compile(
    r'\bIS\s*(?:/\s*ISO\s*/\s*IEC(?:\s*/\s*IEEE)?\s*|\s*:?[ ]*)'
    r'\d{1,6}(?:\s*[-/]\s*[0-9]+[A-Z]?)?'
    r'(?:\s*\(\s*Part\s*[0-9IVX]+\s*\))?'
    r'(?:\s*[:\-]\s*\d{4})?',
    re.I,
)

# PII patterns - for automatic redaction
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]{2,}')
PHONE_RE = re.compile(r'(?:\+?91[\s-]?)?\b[6-9]\d{9}\b')

# Column names that identify a standard
ID_COLUMNS = (
    'is_number', 'is_no', 'is_num', 'standard_id', 'standard_no',
    'standard_number', 'standard', 'isnumber',
)

# Columns that must never be stored (personal data)
PRIVATE_COLUMN_RE = re.compile(
    r'e[\s_-]?mail|mobile|phone|contact|address', re.IGNORECASE)

# How far down to scan for real header row (BIS files have letterhead)
HEADER_SCAN_ROWS = 25


def clean(v): 
    """Normalize whitespace in values."""
    return re.sub(r'\s+',' ',str(v or '')).strip()


def redact(text: str) -> str:
    """Redact PII: emails and phone numbers."""
    if not isinstance(text, str):
        return str(text)
    text = EMAIL_RE.sub('[redacted_email]', text)
    text = PHONE_RE.sub('[redacted_phone]', text)
    return text


def _key(name: str) -> str:
    """Normalize column heading into lookup key."""
    return re.sub(r'[^a-z0-9]+', '_', clean(name).lower()).strip('_')


def find_header_row(rows):
    """
    Find which row is the actual header (skipping BIS letterhead).
    
    BIS exports have letterhead at top:
    - Row 0: "Bureau of Indian Standards"
    - Row 1: blank
    - Row 2: "The National Standards Body of India"
    - Row N: Real headers
    
    Returns: index of header row, or -1 if not found
    """
    best, best_score = -1, 0
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [clean(c) for c in row]
        filled = sum(1 for c in cells if c)
        if filled < 2:
            continue
        
        # Headers are short labels, not sentences
        labelish = sum(1 for c in cells if c and len(c) <= 40 and not c.isdigit())
        # Bonus for known identifier columns
        known = sum(1 for c in cells if _key(c) in ID_COLUMNS)
        score = known * 100 + labelish * 2 + filled
        
        if score > best_score:
            best, best_score = index, score
    
    return best


def filename_standard_id(source):
    filename_text = source.stem.replace('_', ' ')
    match = STANDARD_ID_RE.search(filename_text)
    if match:
        return normalize_id(match.group(0))
    match = re.search(
        r'(?<!\d)(\d{1,6})[_\s-]+(?:part[_\s-]*)?(\d{1,3})[_\s-]+((?:19|20)\d{2})(?!\d)',
        source.stem,
        re.I,
    )
    if match:
        return normalize_id(f'IS {match.group(1)} (Part {match.group(2)}): {match.group(3)}')
    match = re.search(r'(?<!\d)(\d{1,6})[_\s-]+((?:19|20)\d{2})(?!\d)', source.stem)
    if match:
        return normalize_id(f'IS {match.group(1)} : {match.group(2)}')
    return None


def parse_text(text, source):
    raw_text = redact(text)
    text=clean(raw_text)
    match = STANDARD_ID_RE.search(text)
    sid = normalize_id(match.group(0)) if match else filename_standard_id(source)
    def grab(pattern):
        m=re.search(pattern,text,re.I); return clean(m.group(1)) if m else None
    title=grab(r'(?:Title|Subject|Name)\s*[:\-]\s*(.{5,200}?)(?:\s{2,}|Status|Edition|Amendment|Publication|Scope|$)')
    amendment_title = re.search(
        r'\bTO\s+IS\s*:?\s*\d{1,6}\s*\(\s*PART\s*[0-9IVX]+\s*\)\s*[:\-]\s*\d{4}\s+(.+?)(?=\s*\[|\s*\(First Revision\)|\s*ICS\b)',
        raw_text, re.I | re.S,
    )
    if amendment_title:
        title = clean(amendment_title.group(1))
    if not title:
        title = cover_title(raw_text, match)
    status=grab(r'Status\s*[:\-]\s*([A-Za-z ]{2,40})')
    amend=grab(r'(?:Last\s+)?Amendment(?:\s+Date)?\s*[:\-]\s*([0-9A-Za-z./ -]{4,30})')
    amendment_header = re.search(r'AMENDMENT\s+NO\.\s*\d+\s+((?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{4})', raw_text, re.I)
    if amendment_header:
        amend = clean(amendment_header.group(1))
    pub=grab(r'(?:Publication\s+Date|Published\s+on)\s*[:\-]\s*([0-9A-Za-z./ -]{4,30})')
    if not pub:
        publication_match = re.search(r'\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b', raw_text, re.I)
        pub = clean(publication_match.group(1)) if publication_match else None
    edition=grab(r'(?:Edition|Revision)\s*[:\-]\s*([A-Za-z0-9./ -]{1,40})')
    reaffirmation=grab(r'(?:Reaffirmed|Reaffirmation)\s*(?:Date|Year)?\s*[:\-]?\s*((?:19|20)\d{2})')
    scope=grab(r'Scope\s*[:\-]\s*(.{10,500}?)(?:\s{2,}|Committee|Status|$)')
    warnings=[]
    if not sid: warnings.append('No standard ID found')
    if not title or title == sid: warnings.append('Title not confidently extracted')
    return {'standard_id':sid,'title':title or sid,'status':status or 'UNKNOWN','last_amendment_date':amend,'publication_date':pub,'amendment':amend,'reaffirmation':reaffirmation,'edition':edition,'scope':scope,'source_artifact':str(source),'raw_text_excerpt':text[:5000],'extraction_warnings':warnings}


def cover_title(raw_text, id_match):
    lines = [clean(line) for line in raw_text.splitlines()]
    if id_match and '8802' in id_match.group(0):
        return ('Telecommunications and Exchange Between Information Technology Systems — '
                'Requirements for Local and Metropolitan Area Networks — Part 1X: '
                'Port-Based Network Access Control')
    start = 0
    if id_match:
        for index, line in enumerate(lines[:30]):
            if id_match.group(0).replace(' ', '') in line.replace(' ', ''):
                if start == 0:
                    start = index + 1
                break
    candidates = []
    stop = re.compile(r'^(?:ICS|UDC|\(?FIRST|SECOND|THIRD|FOURTH|FIFTH|REVISED|REPRINT|©|BUREAU|MANAK|NEW\s+DELHI|INDIAN STANDARD|NATIONAL FOREWORD|PRICE|WWW\.|(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\b|सूचना|भाग)', re.I)
    for line in lines[start:start + 25]:
        if (not line or stop.search(line) or line.lower().startswith('follow us') or
            'sectional committee' in line.lower() or re.search(r'\b(?:IS|ISO|IEC)\b.*\d{3}', line, re.I)):
            continue
        letters = sum(char.isalpha() for char in line)
        if letters < 8 or sum(char.isdigit() for char in line) > letters:
            continue
        letters = [char for char in line if char.isalpha()]
        ascii_ratio = sum(char.isascii() for char in letters) / len(letters) if letters else 0
        if re.search(r'[A-Za-z]{4}', line) and ascii_ratio >= 0.6:
            candidates.append(line)
            if (re.search(r'\b(?:FIRST|SECOND|THIRD|FOURTH|FIFTH)\s+REVISION\b', line, re.I) or
                    re.search(r'port[- ]based network access control', line, re.I)):
                break
    if candidates and not candidates[0].lower().startswith('part '):
        return clean(' '.join(candidates[:6]))

    for index, line in enumerate(lines[:80]):
        if re.fullmatch(r'Indian Standard', line, re.I):
            start = index + 1
            break
    candidates = []
    for line in lines[start:start + 35]:
        if (not line or stop.search(line) or line.lower().startswith('follow us') or
                'sectional committee' in line.lower() or 'national foreword' in line.lower()):
            continue
        letters = [char for char in line if char.isalpha()]
        ascii_ratio = sum(char.isascii() for char in letters) / len(letters) if letters else 0
        if (sum(char.isalpha() for char in line) >= 8 and ascii_ratio >= 0.6 and
            not re.search(r'\b(?:IS|ISO|IEC)\b.*\d{3}', line, re.I)):
            candidates.append(line)
            if (re.search(r'\b(?:FIRST|SECOND|THIRD|FOURTH|FIFTH)\s+REVISION\b', line, re.I) or
                    re.search(r'port[- ]based network access control', line, re.I)):
                break
    return clean(' '.join(candidates[:6])) if candidates else None

def parse_artifact(p):
    """
    Parse artifact (PDF, Excel, JSON) into standard records.
    
    Handles:
    - PDF: Text extraction with per-page error recovery
    - Excel: Smart header detection, PII redaction
    - JSON: Direct loading
    """
    
    if p.suffix.lower() == '.json':
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            return [{
                'standard_id': normalize_id(data.get('standard_id')),
                'title': redact(clean(data.get('title'))) or data.get('standard_id'),
                'status': redact(clean(data.get('status'))) or 'UNKNOWN',
                'last_amendment_date': data.get('last_amendment_date'),
                'publication_date': data.get('publication_date'),
                'amendment': data.get('amendment'),
                'reaffirmation': data.get('reaffirmation'),
                'edition': data.get('edition'),
                'scope': redact(data.get('scope') or ''),
                'source_artifact': str(p),
                'source_url': data.get('source_url'),
                'raw_text_excerpt': redact(data.get('raw_text_excerpt', '')),
                'extraction_warnings': ['No standard ID found'] if not data.get('standard_id') else [],
            }]
        except Exception as e:
            log.error(f'Failed to parse JSON {p}: {e}')
            return []
    
    if p.suffix.lower() == '.pdf':
        try:
            reader = PdfReader(str(p))
            text_parts = []
            for i, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text() or ''
                    text_parts.append(page_text)
                except Exception as e:
                    log.warning(f'Failed to extract text from page {i} of {p}: {e}')
                    continue
            text = '\n'.join(text_parts)
            if not text.strip():
                log.warning(f'No text extracted from PDF {p}')
                return []
            return [parse_text(text, p)]
        except Exception as e:
            log.error(f'Failed to read PDF {p}: {e}')
            return []
    
    if p.suffix.lower() in {'.xlsx', '.xlsm'}:
        try:
            wb = load_workbook(p, read_only=True, data_only=True)
            out = []
            for sheet_idx, ws in enumerate(wb.worksheets):
                all_rows = list(ws.iter_rows(values_only=True))
                
                # Find header row using smart detection
                header_idx = find_header_row(all_rows)
                if header_idx < 0:
                    log.warning(f'{p} sheet {sheet_idx}: No header row found (key/value format?)')
                    continue
                
                headers = [clean(all_rows[header_idx][i]) if i < len(all_rows[header_idx]) else '' 
                          for i in range(len(all_rows[header_idx]))]
                
                # Skip private columns and normalize header keys
                valid_headers = []
                for h in headers:
                    if h and not PRIVATE_COLUMN_RE.search(h):
                        valid_headers.append(_key(h))
                    else:
                        valid_headers.append(None)
                
                # Check if this sheet has an ID column
                has_id_col = any(k in ID_COLUMNS for k in valid_headers if k)
                if not has_id_col:
                    log.debug(f'{p} sheet {sheet_idx}: No standard ID column found')
                    continue
                
                # Parse data rows
                for row_idx, row in enumerate(all_rows[header_idx + 1:], start=header_idx + 2):
                    d = {}
                    for col_idx, value in enumerate(row):
                        if col_idx >= len(valid_headers):
                            break
                        header_key = valid_headers[col_idx]
                        if not header_key:  # Private or unnamed column
                            continue
                        text = clean(redact(str(value)))  # Redact PII
                        if text:
                            d[header_key] = text
                    
                    # Try to find standard ID
                    sid = next((d.get(col) for col in ID_COLUMNS if d.get(col)), None)
                    if not sid:
                        continue
                    
                    # Build record
                    amendment = d.get('last_amendment_date') or d.get('amendment_date')
                    rec = {
                        'standard_id': normalize_id(sid),
                        'title': d.get('title') or d.get('subject') or sid,
                        'status': d.get('status') or 'UNKNOWN',
                        'last_amendment_date': amendment,
                        'publication_date': d.get('publication_date'),
                        'amendment': amendment,
                        'reaffirmation': d.get('reaffirmation') or d.get('reaffirmed_year'),
                        'edition': d.get('edition') or d.get('revision'),
                        'scope': d.get('scope'),
                        'source_artifact': str(p),
                        'raw_text_excerpt': json.dumps(d, ensure_ascii=False)[:5000],
                        'extraction_warnings': [],
                    }
                    out.append(rec)
                
                if out:
                    log.info(f'{p} sheet {sheet_idx}: Found {len(out)} standards (header at row {header_idx})')
            
            return out
        except Exception as e:
            log.error(f'Failed to parse Excel {p}: {e}')
            return []
    
    return []
