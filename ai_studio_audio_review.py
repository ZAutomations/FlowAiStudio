"""Checkpointed, bounded repairs for imported narration; no synthesis."""
import base64,copy,io,json,math,wave
from pathlib import Path
from ai_studio_pipeline import atomic_json,check_cancel,fingerprint

def partial_boundaries(scenes,candidates,duration):
    from ai_studio_continuous_voice import align
    tables=[]
    for words in candidates:
        try:tables.append(align(scenes,words,duration,partial=True))
        except RuntimeError:pass
    bounds=[0.0]+[None]*(len(scenes)-1)+[duration]
    for i in range(1,len(scenes)):
        for table in tables:
            value=table[i]
            prev=next((v for v in reversed(bounds[:i]) if v is not None),0)
            if value is not None and prev<value<duration:
                bounds[i]=value;break
    return bounds

def valid_bounds(bounds):
    return all(v is not None and math.isfinite(v) for v in bounds) and all(b>a for a,b in zip(bounds,bounds[1:]))

def targeted_repair(scenes,candidates,duration,pcm,root,model,recognize,cancel,log,language=None):
    from ai_studio_existing_audio import verify_coverage
    from ai_studio_continuous_voice import align,transcribe
    qualified=[]
    for w in candidates:
        try:verify_coverage(scenes,w);qualified.append(w)
        except ValueError:pass
    # Global transcript mismatch must remain visible, not patched with guessed timing.
    bounds=partial_boundaries(scenes,qualified+[w for w in candidates if all(w is not q for q in qualified)],duration)
    words=qualified[0] if qualified else (candidates[0] if candidates else [])
    state={'version':1,'duration':duration,'scene_key':fingerprint([s['narration'] for s in scenes]),'coverage_verified':bool(qualified),'boundaries':bounds}
    review=root/'boundary_review.json'
    if review.exists():
        old=json.loads(review.read_text('utf-8'))
        if old.get('scene_key')==state['scene_key']:
            state['manual']=old.get('manual',{})
            for i,v in enumerate(old.get('boundaries',[])):
                if 0<i<len(bounds)-1 and bounds[i] is None and v is not None:bounds[i]=v
    atomic_json(review,state)  # Preserve verified anchors even if a repair is cancelled.
    if qualified:
        # Repair bounded windows only. Cache each exact source/audio window.
        for i in range(1,len(scenes)):
            if bounds[i] is not None:continue
            check_cancel(cancel)
            lo=next(j for j in range(i-1,-1,-1) if bounds[j] is not None)
            hi=next(j for j in range(i+1,len(bounds)) if bounds[j] is not None)
            a,b=bounds[lo],bounds[hi]
            if b-a>60:continue  # Human review instead of another full-story pass.
            key=fingerprint(state['scene_key'],lo,hi,a,b)[:16]
            clip=root/f'repair_{key}.wav'
            if not clip.exists():
                with wave.open(str(pcm),'rb') as src:
                    rate=src.getframerate();src.setpos(round(a*rate))
                    with wave.open(str(clip),'wb') as dst:dst.setparams(src.getparams());dst.writeframes(src.readframes(round(b*rate)-round(a*rate)))
            models=['small','medium'] if model=='base' else ['medium']
            for name in models:
                cache=root/f'repair_{key}_{name}.json'
                if cache.exists():local=json.loads(cache.read_text('utf-8'))['words']
                else:
                    log(f'Repairing only scene boundaries {lo+1}–{hi}: {a:.1f}–{b:.1f}s with {name}.')
                    local=recognize(clip,name,cancel,language=language) if recognize is transcribe else recognize(clip,name,cancel)
                    atomic_json(cache,{'words':local})
                try:
                    verify_coverage(scenes[lo:hi],local)
                    cuts=align(scenes[lo:hi],local,b-a,partial=True)
                except (ValueError,RuntimeError):continue
                for j,v in enumerate(cuts[1:-1],lo+1):
                    if bounds[j] is None and v is not None:bounds[j]=a+v
                state['boundaries']=bounds;atomic_json(review,state)
                if bounds[i] is not None:break
    missing=[]
    for i in range(1,len(scenes)):
        if bounds[i] is not None:continue
        lo=next(j for j in range(i-1,-1,-1) if bounds[j] is not None);hi=next(j for j in range(i+1,len(bounds)) if bounds[j] is not None)
        a,b=bounds[lo],bounds[hi]
        missing.append({'boundary':i,'next_scene':i+1,'earliest':a,'latest':b,'before':scenes[i-1]['narration'],'after':scenes[i]['narration'],
                        'recognized':' '.join(w.get('word','') for w in words if a<=float(w.get('offset',0))<b)})
    state.update(boundaries=bounds,unresolved=missing)
    atomic_json(review,state)
    if not qualified:raise ValueError('Recording/script coverage failed. Review the recording; manual boundary edits cannot override missing or repeated narration.')
    if not valid_bounds(bounds):raise ValueError(f'{len(missing)} boundaries need review. Open Voice → Review audio boundaries, listen and set exact seconds, then Retry. Verified timings are saved.')
    return bounds,words

def locate(project):
    project=Path(project).resolve()
    pointer=json.loads((project/'voice/imported/active_alignment.json').read_text('utf-8'))
    key=pointer.get('cache','')
    import re
    if not re.fullmatch('[a-f0-9]{16}',key):raise ValueError('Invalid alignment cache')
    root=project/'voice/imported'/key
    data=json.loads((root/'boundary_review.json').read_text('utf-8'))
    story=json.loads((project/'project.json').read_text('utf-8'))
    from ai_studio_existing_audio import audio_hash
    recording=story.get('options',{}).get('existing_audio_path','')
    if recording:
        expected=fingerprint('imported-audio-v1',audio_hash(recording),[s['narration'] for s in story['scenes']])
        if expected!=pointer.get('identity'):raise ValueError('Recording changed; run alignment again before review.')
    if data['scene_key']!=fingerprint([s['narration'] for s in story['scenes']]):raise ValueError('Story changed; run alignment again before review.')
    return root,data,story

def review_data(project):
    try:_,data,_=locate(project);return data
    except FileNotFoundError:return None

def save_review(project,corrections):
    root,data,story=locate(project)
    if any(s.get('image_path') or s.get('video_path') for s in story['scenes']):raise ValueError('Generated media exists; boundary edits are locked to preserve its timing.')
    if not data.get('coverage_verified'):raise ValueError('Recording/script mismatch must be fixed before boundary corrections.')
    if not isinstance(corrections,dict) or not corrections:raise ValueError('Enter at least one boundary time in seconds.')
    allowed={r['boundary']:r for r in data.get('unresolved',[])}
    bounds=list(data['boundaries']);manual=dict(data.get('manual',{}))
    for key,value in corrections.items():
        i=int(key)
        if str(i)!=str(key) or i not in allowed or isinstance(value,bool):raise ValueError('Only unresolved boundaries can be edited.')
        value=float(value);row=allowed[i]
        if not math.isfinite(value) or not row['earliest']<value<row['latest']:raise ValueError(f'Boundary {i}: enter seconds strictly between its verified neighbours.')
        bounds[i]=value;manual[str(i)]=value
    known=[v for v in bounds if v is not None]
    if any(b<=a for a,b in zip(known,known[1:])):raise ValueError('Boundary times must increase in scene order.')
    data.update(boundaries=bounds,manual=manual,unresolved=[r for r in data['unresolved'] if bounds[r['boundary']] is None])
    atomic_json(root/'boundary_review.json',data)
    return {'saved':len(corrections),'remaining':len(data['unresolved'])}

def preview(project,boundary):
    root,data,_=locate(project);row=next((r for r in data.get('unresolved',[]) if r['boundary']==boundary),None)
    if not row:raise ValueError('Select an unresolved boundary.')
    a=row['earliest'];b=min(row['latest'],a+60)
    buffer=io.BytesIO()
    with wave.open(str(root/'narration.wav'),'rb') as src:
        rate=src.getframerate();src.setpos(round(a*rate))
        with wave.open(buffer,'wb') as dst:dst.setparams(src.getparams());dst.writeframes(src.readframes(round(b*rate)-round(a*rate)))
    return {'audio':'data:audio/wav;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii'),'start':a,'end':b}
