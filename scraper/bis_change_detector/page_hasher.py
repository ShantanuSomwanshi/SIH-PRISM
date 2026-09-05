import hashlib, re
from bs4 import BeautifulSoup
import requests

def fetch_normalized(url, timeout=45):
    r=requests.get(url,timeout=timeout,headers={'User-Agent':'BIS-Change-Detector/1.0'})
    r.raise_for_status()
    soup=BeautifulSoup(r.text,'html.parser')
    for x in soup(['script','style','noscript','iframe']): x.decompose()
    for tag in soup.find_all(True):
        for a in list(tag.attrs):
            al=a.lower()
            if al in {'style','onclick','onload','onchange','nonce'} or 'csrf' in al or 'token' in al or 'session' in al:
                del tag.attrs[a]
        if tag.string: tag.string=re.sub(r'\b(?:csrf|session|token|timestamp|time)\s*[=:]\s*[\w./+-]+','',tag.string,flags=re.I)
    text=soup.decode(formatter='minimal')
    text=re.sub(r'\s+',' ',text).strip()
    return hashlib.sha256(text.encode()).hexdigest(), text, soup
