from pathlib import Path
import re, json
import logging
from pypdf import PdfReader
from openpyxl import load_workbook
from .fingerprint import normalize_id

logging.getLogger('pypdf._cmap').setLevel(logging.ERROR)

STANDARD_ID_RE = re.compile(
    r'\bIS\s*(?:/\s*ISO\s*/\s*IEC(?:\s*/\s*IEEE)?\s*|\s*:?[ ]*)'
    r'\d{1,6}(?:\s*[-/]\s*[0-9]+[A-Z]?)?'
    r'(?:\s*\(\s*Part\s*[0-9IVX]+\s*\))?'
    r'(?:\s*[:\-]\s*\d{4})?',
    re.I,
)


def clean(v): return re.sub(r'\s+',' ',str(v or '')).strip()


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
    raw_text = text
    text=clean(text)
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
    if p.suffix.lower()=='.json':
        data=json.loads(p.read_text(encoding='utf-8'))
        return [{
            'standard_id': normalize_id(data.get('standard_id')),
            'title': clean(data.get('title')) or data.get('standard_id'),
            'status': clean(data.get('status')) or 'UNKNOWN',
            'last_amendment_date': data.get('last_amendment_date'),
            'publication_date': data.get('publication_date'),
            'amendment': data.get('amendment'),
            'reaffirmation': data.get('reaffirmation'),
            'edition': data.get('edition'),
            'scope': data.get('scope'),
            'source_artifact': str(p),
            'source_url': data.get('source_url'),
            'raw_text_excerpt': data.get('raw_text_excerpt', ''),
            'extraction_warnings': [],
        }]
    if p.suffix.lower()=='.pdf':
        reader=PdfReader(str(p)); text='\n'.join((x.extract_text() or '') for x in reader.pages)
        return [parse_text(text,p)]
    if p.suffix.lower() in {'.xlsx','.xlsm'}:
        wb=load_workbook(p,read_only=True,data_only=True)
        out=[]
        for ws in wb.worksheets:
            headers=[clean(x.value) for x in next(ws.iter_rows(min_row=1,max_row=1))]
            for row in ws.iter_rows(min_row=2,values_only=True):
                d={headers[i].lower().replace(' ','_'):clean(v) for i,v in enumerate(row) if i<len(headers) and v is not None}
                sid=d.get('is_number') or d.get('standard_id')
                if sid:
                    amendment=d.get('last_amendment_date') or d.get('amendment_date')
                    rec={'standard_id':normalize_id(sid),'title':d.get('title') or d.get('subject') or sid,'status':d.get('status') or 'UNKNOWN','last_amendment_date':amendment,'publication_date':d.get('publication_date'),'amendment':amendment,'reaffirmation':d.get('reaffirmation') or d.get('reaffirmed_year'),'edition':d.get('edition'),'scope':d.get('scope'),'source_artifact':str(p),'raw_text_excerpt':json.dumps(d,ensure_ascii=False),'extraction_warnings':[]}
                    out.append(rec)
        return out
    return []
