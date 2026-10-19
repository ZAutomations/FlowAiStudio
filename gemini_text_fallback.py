"""Bounded retries for Gemini text analysis; no browser/account rotation."""
import time
import json
import hashlib
import requests
from ai_studio_pipeline import check_cancel
from gemini_quota import details as quota_details

TEXT_MODELS = (
    'gemini-3.8-flash', 'gemini-3.6-flash', 'gemini-3-flash-preview',
)


def generate(adapter,settings,keys,system,user,max_tokens,base,log=print,json_mode=False):
    selected=settings.get('zb_gemini_llm_model',TEXT_MODELS[0])
    configured=settings.get('zb_gemini_llm_models') or [selected]
    if isinstance(configured,str):configured=[configured]
    # Do not resurrect Lite/legacy models from an older saved pool.
    models=list(dict.fromkeys([str(m).strip() for m in [*configured,*TEXT_MODELS] if str(m).strip() in TEXT_MODELS]))
    unavailable=getattr(adapter,'_zb_unavailable_gemini_models',set())
    if not isinstance(unavailable,set):unavailable=set()
    working=getattr(adapter,'_zb_working_gemini_model',None)
    if working in models:models=[working]+[m for m in models if m!=working]
    models=[model for model in models if model not in unavailable]
    cancel=getattr(adapter,'_zb_cancel',None)
    availability=getattr(adapter,'_zb_gemini_availability',None)
    if not isinstance(availability,dict):availability={};adapter._zb_gemini_availability=availability
    def slot(model,key):return (model,hashlib.sha256(key.encode()).hexdigest())
    def wait(delay):
        remaining=delay
        while remaining>0:
            check_cancel(cancel);part=min(30,remaining)
            if cancel is not None:cancel.wait(part)
            else:time.sleep(part)
            remaining-=part
        check_cancel(cancel)
    deadline=time.monotonic()+300
    last='No available Gemini text models. Check the configured model names.'
    # First try every alternative. Only transient failures enter later rounds;
    # missing models, invalid credentials, quota walls and blocked content do not.
    for round_number in range(3):
        transient=[]
        for model in models:
            check_cancel(cancel)
            missing_keys=0
            log(f'[INFO] Gemini text: trying {model} (attempt {round_number+1}/3).')
            for key_number,key in enumerate(keys,1):
                check_cancel(cancel)
                blocked=availability.get(slot(model,key),{})
                if blocked.get('hard'):
                    last=blocked.get('reason',last);continue
                if blocked.get('until',0)>time.monotonic():
                    transient.append(model);continue
                remaining=deadline-time.monotonic()
                if remaining<=0:return None,'Gemini text retry budget exhausted (300s); saved analysis batches are retained. '+last
                try:
                    response=requests.post(f'{base}/models/{model}:generateContent',params={'key':key},
                        headers={'Content-Type':'application/json'},
                        json={'systemInstruction':{'parts':[{'text':system}]},
                              'contents':[{'role':'user','parts':[{'text':user}]}],
                              'generationConfig':{'maxOutputTokens':max_tokens,'temperature':0.2 if json_mode else 0.9,
                                                  **({'responseMimeType':'application/json'} if json_mode else {})}},
                        timeout=min(120,remaining))
                except requests.RequestException:
                    last=f'Gemini {model}, key #{key_number}: temporary network error.'
                    transient.append(model)
                    log('[WARN] '+last+' Trying the next available text model/key.')
                    continue
                code=response.status_code
                if code==200:
                    try:
                        data=response.json()
                        finish=data['candidates'][0].get('finishReason','')
                        parts=data['candidates'][0]['content']['parts']
                        text=''.join(part.get('text','') for part in parts if not part.get('thought'))
                    except (ValueError,KeyError,IndexError,TypeError):
                        last=f'Gemini {model}: response contained no usable text. No automatic content-refusal retry.'
                        return None,last
                    if not text.strip():return None,f'Gemini {model}: empty or blocked text response. Review the provider response before retrying.'
                    if finish in ('SAFETY','BLOCKLIST','PROHIBITED_CONTENT','SPII','RECITATION'):
                        return None,f'Gemini {model}: response stopped for {finish}. Review the provider response before retrying.'
                    if json_mode:
                        if finish=='MAX_TOKENS':
                            return None,f'[INVALID_JSON] Gemini {model}: output was truncated at its token limit. Retry a smaller scene batch.'
                        try:
                            if not isinstance(json.loads(text),dict):raise ValueError('Expected object')
                        except (ValueError,TypeError):
                            return None,f'[INVALID_JSON] Gemini {model}: output was not a complete JSON object. Retry a smaller scene batch.'
                    adapter._zb_working_gemini_model=model
                    availability[slot(model,key)]={'until':time.monotonic()+2}
                    log(f'[INFO] Gemini text: {model} completed successfully with key #{key_number}.')
                    usage=data.get('usageMetadata',{})
                    if isinstance(usage,dict) and type(usage.get('promptTokenCount')) is int:
                        log(f"[INFO] Gemini text usage: {usage['promptTokenCount']} input tokens for this request.")
                    return text,None
                detail=response.text[:220]
                for secret in keys:detail=detail.replace(secret,'[redacted]')
                last=f'Gemini {model} → HTTP {code}: {detail}'
                if code==404:
                    missing_keys+=1
                    log(f'[WARN] Gemini text: {model}, key #{key_number}: model unavailable; trying an alternative.')
                elif code in (408,500,502,503,504):
                    transient.append(model)
                    hint=quota_details(response)['retry_after']
                    delay=max((4,12,30)[round_number],hint or 0)
                    availability[slot(model,key)]={'until':time.monotonic()+delay}
                    log(f'[WARN] Gemini text: {model}, key #{key_number}: temporarily unavailable (HTTP {code}); trying the next model/key.')
                elif code==429:
                    quota=quota_details(response)
                    delay=quota['retry_after'] if quota['retry_after'] is not None else 60
                    if not quota['hard']:transient.append(model)
                    last=f"Gemini {model}, key #{key_number}: HTTP 429 — {quota['kind']}. "
                    last+=('Skipped for this worker; wait for quota reset or check the project tier.' if quota['hard'] else f'Retry after at least {delay:.1f}s.')
                    availability[slot(model,key)]={'hard':quota['hard'],'until':time.monotonic()+delay,'reason':last}
                    log('[WARN] '+last+' Checking another available key/model.')
                elif code in (401,403):
                    availability[slot(model,key)]={'hard':True,'reason':last}
                    log(f'[WARN] Gemini text: {model}, key #{key_number}: HTTP {code}; checking another configured key/model.')
                else:return None,last
            if missing_keys==len(keys):
                unavailable.add(model);adapter._zb_unavailable_gemini_models=unavailable
        models=list(dict.fromkeys(transient))
        if not models or round_number==2:break
        waits=[max(0,availability.get(slot(model,key),{}).get('until',0)-time.monotonic())
               for model in models for key in keys if not availability.get(slot(model,key),{}).get('hard')]
        delay=max((4,12)[round_number],min(waits) if waits else 0)
        if time.monotonic()+delay>=deadline:break
        log(f'[WARN] Gemini text: temporary errors across available models. Retrying in {delay:.1f}s; completed analysis batches remain saved.')
        wait(delay)
    return None,last
