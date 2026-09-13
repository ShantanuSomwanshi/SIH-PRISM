import hashlib

def row_fingerprint(r):
    # Exact requested formula: SHA-256(Standard_ID + Title + Status + Last_Amendment_Date)
    payload=''.join(str(r.get(k) or '') for k in ['standard_id','title','status','last_amendment_date'])
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
