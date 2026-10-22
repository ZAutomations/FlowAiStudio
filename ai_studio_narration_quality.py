"""Local narration preflight. Never rewrite source text or existing media."""
import re
import unicodedata
from collections import Counter

def repeated_passages(text):
    found={};counts=Counter()
    for part in re.findall(r'[^۔.!?؟]+[۔.!?؟]?',str(text)):
        normalized=unicodedata.normalize('NFKC',part).casefold().replace('ي','ی').replace('ك','ک')
        normalized=''.join(c for c in normalized if unicodedata.category(c)!='Mn')
        words=re.findall(r'[^\W_]+',normalized,re.UNICODE)
        if len(words)<10:continue
        key=' '.join(words);counts[key]+=1;found.setdefault(key,part.strip())
    return [{'count':count,'text':found[key]} for key,count in counts.items() if count>=3]

def validate_narration(text):
    issues=repeated_passages(text)
    if issues:
        examples='; '.join(f"{row['count']} times: {row['text'][:160]}" for row in issues[:3])
        raise ValueError('Repeated narration detected before generation. Review and correct the source script/JSON; no text was removed automatically. '+examples)
