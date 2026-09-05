from pathlib import Path
import re, json
from pypdf import PdfReader
from openpyxl import load_workbook

def clean(v): return re.sub(r'\s+',' ',str(v or '')).strip()
def parse_text(text, source):
    text=clean(text)
    ids=re.findall(r'\bIS\s+[0-9]{1,6}(?:\s*\([^)]*\))?(?:\s*:\s*\d{4})?',text,re.I)
    sid=clean(ids[0]).upper() if ids else source.stem.upper()
    def grab(pattern):
        m=re.search(pattern,text,re.I); return clean(m.group(1)) if m else None
    title=grab(r'(?:Title|Subject|Name)\s*[:\-]\s*(.{5,200}?)(?:\s{2,}|Status|Edition|Amendment|Publication|Scope|$)')
    status=grab(r'Status\s*[:\-]\s*([A-Za-z ]{2,40})')
    amend=grab(r'(?:Last\s+)?Amendment(?:\s+Date)?\s*[:\-]\s*([0-9A-Za-z./ -]{4,30})')
    pub=grab(r'(?:Publication\s+Date|Published\s+on)\s*[:\-]\s*([0-9A-Za-z./ -]{4,30})')
    edition=grab(r'(?:Edition|Revision)\s*[:\-]\s*([A-Za-z0-9./ -]{1,40})')
    scope=grab(r'Scope\s*[:\-]\s*(.{10,500}?)(?:\s{2,}|Committee|Status|$)')
    warnings=[]
    if not ids: warnings.append('No IS number found')
    if not title: warnings.append('Title not confidently extracted')
    return {'standard_id':sid,'title':title or sid,'status':status or 'UNKNOWN','last_amendment_date':amend,'publication_date':pub,'edition':edition,'scope':scope,'source_artifact':str(source),'raw_text_excerpt':text[:5000],'extraction_warnings':warnings}

def parse_artifact(p):
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
                    rec={'standard_id':sid.upper(),'title':d.get('title') or d.get('subject') or sid,'status':d.get('status') or 'UNKNOWN','last_amendment_date':d.get('last_amendment_date') or d.get('amendment_date'),'publication_date':d.get('publication_date'),'edition':d.get('edition'),'scope':d.get('scope'),'source_artifact':str(p),'raw_text_excerpt':json.dumps(d,ensure_ascii=False),'extraction_warnings':[]}
                    out.append(rec)
        return out
    return []
