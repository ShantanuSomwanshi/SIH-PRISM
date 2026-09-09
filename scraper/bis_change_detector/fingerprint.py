import hashlib
import json
import re

MEANINGFUL_FIELDS = (
    'standard_id', 'title', 'status', 'last_amendment_date',
    'publication_date', 'amendment', 'reaffirmation', 'edition', 'scope',
)

REVISION_FIELDS = ('observed_standard_id', 'title', 'publication_date', 'aspect', 'equivalence')


def normalize_id(value):
    value = ' '.join(str(value or '').split()).upper()
    value = value.replace('IS/ISO ', 'IS ')
    value = re.sub(r'\s*:\s*', ' : ', value)
    return value.replace('IS:', 'IS ').replace('IS  ', 'IS ')


def comparable_record(record):
    return {field: ' '.join(str(record.get(field) or '').split())
            for field in MEANINGFUL_FIELDS}


def row_fingerprint(record):
    payload = json.dumps(comparable_record(record), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def revision_fingerprint(record):
    payload = json.dumps(
        {field: ' '.join(str(record.get(field) or '').split()) for field in REVISION_FIELDS},
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
