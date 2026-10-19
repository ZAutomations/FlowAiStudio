"""Safe Gemini quota classification and Retry-After parsing."""
import re
import time
from email.utils import parsedate_to_datetime


def details(response):
    try:data=response.json()
    except (ValueError,TypeError):data={}
    error=data.get('error',{}) if isinstance(data,dict) else {}
    entries=error.get('details',[]) if isinstance(error,dict) else []
    message=str(error.get('message','')) if isinstance(error,dict) else ''
    signals=[message];violations=[];delays=[]
    for entry in entries if isinstance(entries,list) else []:
        if not isinstance(entry,dict):continue
        match=re.fullmatch(r'(\d+(?:\.\d+)?)s',str(entry.get('retryDelay','')))
        if match:delays.append(float(match[1]))
        for value in entry.get('violations',[]) if isinstance(entry.get('violations',[]),list) else []:
            if not isinstance(value,dict):continue
            violations.append(value)
            signals.extend(str(value.get(key,'')) for key in ('quotaMetric','quotaId'))
    headers=getattr(response,'headers',{})
    retry=headers.get('Retry-After') if isinstance(headers,dict) or hasattr(headers,'get') else None
    if isinstance(retry,str):
        try:delays.append(max(0,float(retry)))
        except ValueError:
            try:delays.append(max(0,parsedate_to_datetime(retry).timestamp()-time.time()))
            except (ValueError,TypeError,OverflowError):pass
    signal=' '.join(signals).lower()
    zero=any(str(value.get('quotaValue',''))=='0' for value in violations) or bool(re.search(r'limit\s*:\s*0\b',signal))
    daily=bool(re.search(r'per[_ ]?day|daily|requestsperday|tokensperday',signal))
    kind=('zero quota / unavailable tier' if zero else 'daily quota' if daily
          else 'tokens per minute' if 'token' in signal and re.search(r'per[_ ]?minute',signal)
          else 'requests per minute' if 'request' in signal and re.search(r'per[_ ]?minute',signal)
          else 'quota/rate limit (provider did not identify the limit)')
    return {'kind':kind,'hard':zero or daily,'retry_after':max(delays) if delays else None}
