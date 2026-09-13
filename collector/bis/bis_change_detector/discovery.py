import hashlib, re
from collections import OrderedDict

def normalize_id(x):
    return re.sub(r'\s+',' ',x.strip()).upper()

def discover(soup):
    found=OrderedDict()
    for row in soup.select('tr'):
        txt=' '.join(row.stripped_strings)
        ids=re.findall(r'\bIS\s+[0-9]{1,6}(?:\s*\([^)]*\))?(?:\s*:\s*\d{4})?(?:\s*[-/]\s*\d+)?',txt,re.I)
        for sid in ids:
            sid=normalize_id(sid)
            found[sid]=hashlib.sha256(re.sub(r'\s+',' ',txt).encode()).hexdigest()
    if not found:
        text=' '.join(soup.stripped_strings)
        for sid in re.findall(r'\bIS\s+[0-9]{1,6}(?:\s*\([^)]*\))?(?:\s*:\s*\d{4})?',text,re.I):
            sid=normalize_id(sid); found.setdefault(sid,hashlib.sha256(text.encode()).hexdigest())
    # Do not infer removals from a paginated view.
    pagination = bool(soup.select('.pagination, .paginate, [aria-label*=pagination i], a[href*=page i]'))
    complete = bool(found) and not pagination
    return found, complete
