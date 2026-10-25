"""Opt-in imported narration. Never calls TTS or modifies the source recording."""
import copy, difflib, hashlib, json, re, wave
from pathlib import Path
from ai_studio_pipeline import atomic_json, check_cancel, fingerprint, run_ffmpeg, valid_audio

def audio_hash(path):
    p=Path(str(path or ''))
    if not p.is_file():raise ValueError('Select an existing narration audio file (WAV, MP3, M4A or FLAC).')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def verify_coverage(scenes,words):
    from ai_studio_continuous_voice import tokens
    expected=tokens(' '.join(s['narration'] for s in scenes))
    heard=tokens(' '.join(w.get('word',w.get('text','')) for w in words))
    matches=sum(b.size for b in difflib.SequenceMatcher(None,expected,heard,autojunk=False).get_matching_blocks())
    # Both directions matter: duplicated audio must not pass just because script words exist.
    if not expected or not heard or matches/len(expected)<.90 or matches/len(heard)<.90:
        raise ValueError('Imported audio/script mismatch: missing, repeated or different speech detected by local recognition. Review the recording/script; existing media unchanged.')
    return matches/len(expected),matches/len(heard)

def verify(scenes,words,duration):
    from ai_studio_continuous_voice import align
    verify_coverage(scenes,words)
    return align(scenes,words,duration)

def recover_saved_boundaries(scenes,candidates,duration):
    from ai_studio_continuous_voice import combine_verified_boundaries
    qualified=[]
    for words in candidates:
        try:verify_coverage(scenes,words);qualified.append(words)
        except ValueError:pass
    if not qualified:raise ValueError('No recognition result passed the recording/script coverage check.')
    # A globally verified transcript supplies the timing words; other saved ASR
    # results supply only actual matched anchors for its unresolved boundaries.
    others=[w for w in candidates if all(w is not q for q in qualified)]
    return combine_verified_boundaries(scenes,qualified+others,duration)


def generate(adapter,q,config,recognize=None):
    from ai_studio_continuous_voice import transcribe
    recognize=recognize or transcribe
    scenes=adapter.zb_scenes
    if not scenes:raise ValueError('Import or parse the complete story before aligning existing audio.')
    from ai_studio_continuous_voice import tokens
    if config.get('script') and tokens(config['script'])!=tokens(' '.join(s['narration'] for s in scenes)):
        raise ValueError('Scene narration differs from the full Script. Review/import the complete matching story before audio alignment.')
    source=Path(str(config.get('existing_audio_path',''))).expanduser()
    digest=audio_hash(source)
    identity=fingerprint('imported-audio-v1',digest,[s['narration'] for s in scenes])
    # Keep generated projects intact; switching workflow after media creation needs a fresh project.
    if any((s.get('image_path') or s.get('video_path')) and s.get('audio_key')!=identity for s in scenes):
        raise ValueError('Use Existing Audio + Script in a fresh project before generating media. Current images, clips and narration are preserved.')
    root=Path(config['project'])/'voice'/'imported'/identity[:16];root.mkdir(parents=True,exist_ok=True)
    pcm=root/'narration.wav'
    if not valid_audio(pcm):
        tmp=root/'narration.importing.wav'
        run_ffmpeg(['-i',str(source),'-vn','-ar','48000','-ac','1','-c:a','pcm_s16le',str(tmp)],adapter._zb_cancel)
        tmp.replace(pcm)
    with wave.open(str(pcm),'rb') as f:rate=f.getframerate();frames=f.getnframes();duration=frames/rate
    language='hi' if re.search('[\u0900-\u097f]',config['script']) else 'ur' if re.search('[\u0600-\u06ff]',config['script']) else None
    model=config.get('narration_alignment_model','base')
    if model not in ('base','small','medium'):raise ValueError('Choose base, small or medium alignment.')
    q.put(('log','info','Existing Audio + Script: local alignment only; no TTS or Gemini planning request. Source recording retained.'))
    atomic_json(root.parent/'active_alignment.json',{'cache':root.name,'identity':identity})
    from ai_studio_audio_review import targeted_repair
    candidates=[]
    for name in ('medium','small','base'):
        file=root/f'words_{name}.json'
        if file.exists():candidates.append(json.loads(file.read_text('utf-8'))['words'])
    qualified=[]
    for candidate in candidates:
        try:verify_coverage(scenes,candidate);qualified.append(candidate)
        except ValueError:pass
    if not qualified:
        def recognition_progress(done,total,message):
            # Recognition is only part of alignment; reserve completion for
            # verified boundaries and saved scene audio, not ASR alone.
            if total>0:q.put(('progress',min(85,int(done/total*85))))
            q.put(('status',message))
        for name in ['base','small','medium'][['base','small','medium'].index(model):]:
            check_cancel(adapter._zb_cancel)
            file=root/f'words_{name}.json'
            if file.exists():words=json.loads(file.read_text('utf-8'))['words']
            else:
                q.put(('log','info',f'Checking full recording/script coverage with {name} ({duration:.1f}s); subsequent boundary repairs use short segments only.'))
                q.put(('status',f'Loading {name} alignment model; waiting for the first recognized segment.'))
                q.put(('progress',0))
                words=recognize(pcm,name,adapter._zb_cancel,language=language,progress=recognition_progress) if recognize is transcribe else recognize(pcm,name,adapter._zb_cancel)
                atomic_json(file,{'words':words});candidates.append(words)
            try:verify_coverage(scenes,words);qualified.append(words);break
            except ValueError as error:q.put(('log','warning',f'{name}: {error}'))
    candidates=qualified+[w for w in candidates if all(w is not v for v in qualified)]
    q.put(('status','Checking script coverage and repairing scene boundaries'))
    bounds,words=targeted_repair(scenes,candidates,duration,pcm,root,model,recognize,adapter._zb_cancel,
        lambda message:q.put(('log','info',message)),language)

    rows=copy.deepcopy(scenes)
    with wave.open(str(pcm),'rb') as f:
        for i,row in enumerate(rows):
            check_cancel(adapter._zb_cancel)
            start,end=round(bounds[i]*rate),round(bounds[i+1]*rate)
            out=root/f'scene_{i+1:04d}.wav';f.setpos(start)
            with wave.open(str(out),'wb') as target:target.setparams(f.getparams());target.writeframes(f.readframes(end-start))
            local=[]
            for w in words:
                a=float(w.get('offset',w.get('start',0)));b=a+float(w.get('duration',float(w.get('end',a))-a))
                if start/rate<=a<end/rate:local.append({'word':w.get('word',w.get('text','')),'offset':a-start/rate,'duration':max(0,min(b,end/rate)-a)})
            row.update(audio_path=str(out),audio_key=identity,audio_status='done',voice_engine='imported_audio',word_timings=local,timing_source='existing-audio-aligned',continuous_voice_key=identity)
            q.put(('progress',85+int((i+1)/len(rows)*14)))
    atomic_json(root/'manifest.json',{'identity':identity,'source_sha256':digest,'source_audio':str(source),'duration':duration,'boundaries':bounds})
    adapter.zb_scenes=rows;adapter._zb_save_project(config)
    q.put(('log','success',f'Imported narration verified for {len(rows)} scenes. Original performance reused; no voice generation.'))
    q.put(('refresh',));q.put(('progress',100))
