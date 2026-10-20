"""Audio-first Animate planning; source narration and generation checkpoints stay immutable."""
import copy
import difflib
import json
import math
import re
import wave
from pathlib import Path
from types import SimpleNamespace

from ai_studio_pipeline import atomic_json, check_cancel, fingerprint, probe, run_ffmpeg, valid_audio, valid_image
from ai_studio_continuous_voice import generate as continuous_voice, transcribe, tokens


def enabled(config):
    return config.get('animate_narration_mode','scene') == 'cinematic'


def measured_words(scenes):
    """Keep original text/punctuation, using ASR matches to place source words."""
    source=[]; spoken=[]; expected=[]; original=[]; durations=[]; cursor=0
    for scene in scenes:
        duration=probe(scene['audio_path'])[0];durations.append(duration)
        for word in re.findall(r'\S+',scene['narration']):
            original.append(word)
            expected.extend((token,len(original)-1) for token in tokens(word))
        for word in scene.get('word_timings',[]):
            for token in tokens(word['word']):
                spoken.append(token)
                source.append((cursor+float(word['offset']),float(word.get('duration',.1))))
        cursor+=duration
    mapping={}
    for block in difflib.SequenceMatcher(None,[v[0] for v in expected],spoken,autojunk=False).get_matching_blocks():
        for i in range(block.size):
            mapping.setdefault(expected[block.a+i][1],source[block.b+i])
    if len(mapping)/max(1,len(original))<.65:
        raise RuntimeError('Cinematic word alignment is uncertain. Saved narration retained; try stronger alignment before planning clips.')
    result=[]
    for i,word in enumerate(original):
        if i in mapping:
            start,length=mapping[i];origin='matched'
        else:
            left=max((j for j in mapping if j<i),default=None)
            right=min((j for j in mapping if j>i),default=None)
            a=mapping[left][0]+mapping[left][1] if left is not None else 0
            b=mapping[right][0] if right is not None else cursor
            count=(right if right is not None else len(original))-(left if left is not None else -1)
            length=max(.01,(b-a)/max(1,count))
            start=a+length*(i-(left if left is not None else -1)-1);origin='interpolated'
        start=max(result[-1]['offset'] if result else 0,min(cursor,start))
        result.append({'word':word,'offset':start,'duration':max(.001,min(length,cursor-start)), 'alignment':origin})
    return result,durations


def clip_rows(source,config,folder):
    words,durations=measured_words(source)
    master=Path(source[0]['audio_path']).parent/'narration.wav'
    with wave.open(str(master),'rb') as stream:
        rate=stream.getframerate();frames=stream.getnframes();total=frames/rate
    mode=config.get('animation_mode','partial')
    from ai_studio_animate_options import partial_options
    unit,value=partial_options(config)
    cutoff=total if mode=='full' else min(total,value if unit=='seconds' else value*8)
    cuts=[0.0]
    while cuts[-1]+8 < cutoff-1e-6:cuts.append(cuts[-1]+8)
    if cutoff>0:cuts.append(cutoff)
    cursor=0
    for duration in durations:
        cursor+=duration
        if cursor>cutoff+1e-6:cuts.append(min(total,cursor))
    if cuts[-1]<total-1e-6:cuts.append(total)
    cuts=sorted(set(round(t*rate) for t in cuts));cuts[-1]=frames
    rows=[];word_index=0;source_edges=[];cursor=0
    for scene,duration in zip(source,durations):
        source_edges.append((cursor,cursor+duration,scene));cursor+=duration
    with wave.open(str(master),'rb') as stream:
        for i,(a,b) in enumerate(zip(cuts,cuts[1:])):
            start,end=a/rate,b/rate
            selected=[]
            while word_index<len(words) and (words[word_index]['offset']<end or i==len(cuts)-2):
                selected.append(words[word_index]);word_index+=1
            audio=folder/f'clip_{i+1:04d}.wav'
            with wave.open(str(audio),'wb') as target:
                target.setparams(stream.getparams());stream.setpos(a);target.writeframes(stream.readframes(b-a))
            rows.append({'id':i+1,'narration':' '.join(w['word'] for w in selected),'visual_prompt':'','caption':'',
                'audio_path':str(audio),'audio_status':'done','audio_key':folder.name,'voice_engine':config['voice_engine'],
                'timing_source':'continuous-aligned','cinematic_start':start,'cinematic_end':end,
                'cinematic_kind':'video' if start<cutoff-1e-6 else 'image',
                'word_timings':[{**w,'offset':max(0,w['offset']-start),'duration':min(w['duration'],max(.001,end-w['offset']))} for w in selected]})
            overlapping=[s for left,right,s in source_edges if left<end-1e-6 and right>start+1e-6]
            rows[-1]['source_visuals']=[{'visual_prompt':s.get('visual_prompt',''),'shots':s.get('shots',[]),
                'continuity':s.get('cinematic_continuity',{}),'references':s.get('reference_names',[])} for s in overlapping]
    if ' '.join(' '.join(r['narration'] for r in rows).split()) != ' '.join(' '.join(s['narration'] for s in source).split()):
        raise RuntimeError('Cinematic narration partition failed; original scenes retained.')
    return rows


SYSTEM='''You are a film continuity director planning visuals to EXISTING continuous off-screen narration.
Return ONLY a JSON array, one row per requested clip, in order. Each row must have:
clip (the exact supplied number), visual_prompt, location, start_state, end_state,
continues_previous (boolean), references (array of supplied exact reference names), shots.
For videos shots must contain 2-4 objects {start,end,visual_prompt}, contiguous 0 to 8 seconds.
One row means ONE generated eight-second clip with several sequential shots, never a collage or separate output per shot.
The last clip may be trimmed to its supplied used duration; put its narrated events BEFORE that duration ends.
For still-image rows use shots=[] and describe one concrete still; do not turn the remaining image section into videos.
Do NOT rewrite, translate or return narration. Narration already exists and must never be synthesized again per clip.
Read the full story, nearby narration and PREVIOUS END STATE. Show the actual topic/events, never unrelated keyword metaphors.
Keep faces, wardrobe, props, handedness, screen direction, spatial layout, lighting and time consistent.
Choose a meaningful 2-4-shot rhythm from the narrated events, rather than a separate image for each sentence.
When this continues the same moment/location: set continues_previous=true and copy the preceding end_state EXACTLY
into start_state; use the supplied previous last-frame reference as the visual starting point, then progress the action.
When the narration genuinely changes time or place, set continues_previous=false and clearly establish the new scene.
Never invent clues, suspects, dramatic events or transitions not supported by the story.
Use only assigned reference identities that actually appear. No invented recurring couple in documentaries.
All characters stay silent; no lip-sync, speaking, narration to camera, generated voice, music, subtitles or embedded text.
Use natural camera cuts; no arbitrary costume/location resets, no flashing montage or flashy transitions.'''


def validate_plan(raw,rows,allowed,previous=None):
    raw=re.sub(r'^```(?:json)?\s*|\s*```$','',str(raw).strip(),flags=re.I)
    try:items=json.loads(raw)
    except ValueError as exc:raise RuntimeError('Cinematic director returned incomplete JSON. Audio and completed planning batches retained.') from exc
    if not isinstance(items,list) or len(items)!=len(rows):raise RuntimeError('Cinematic director omitted clips; no scene plan replaced.')
    result=[]
    for item,row in zip(items,rows):
        if not isinstance(item,dict) or item.get('clip')!=row['id']:raise RuntimeError('Cinematic clip order changed.')
        for key in ('visual_prompt','location','start_state','end_state'):
            if not isinstance(item.get(key),str) or not item[key].strip():raise RuntimeError('Cinematic plan needs visual direction and start/end continuity states.')
        if type(item.get('continues_previous')) is not bool:raise RuntimeError('Cinematic plan needs an explicit continuity decision.')
        refs=item.get('references')
        if not isinstance(refs,list) or any(not isinstance(r,str) or r not in allowed for r in refs):raise RuntimeError('Cinematic planner used unknown references.')
        if item['continues_previous']:
            if previous is None or item['start_state']!=previous['end_state'] or item['location']!=previous['location']:
                raise RuntimeError('Cinematic continuity states do not join. Planning checkpoint retained; retry this batch.')
        shots=item.get('shots')
        if row['cinematic_kind']=='video':
            if not isinstance(shots,list) or not 2<=len(shots)<=4:raise RuntimeError('Each cinematic video clip needs 2-4 shots.')
            end=0
            for shot in shots:
                try:a=float(shot['start']);b=float(shot['end'])
                except (KeyError,ValueError,TypeError):raise RuntimeError('Cinematic shot timings are invalid.')
                if not math.isfinite(a+b) or abs(a-end)>1e-6 or not a<b<=8 or not str(shot.get('visual_prompt','')).strip():raise RuntimeError('Cinematic shots must cover 0-8 seconds without gaps.')
                end=b
            if abs(end-8)>1e-6:raise RuntimeError('Cinematic shots must cover eight seconds.')
        elif shots!=[]:raise RuntimeError('Still-image rows cannot contain animated shots.')
        result.append(item);previous=item
    return result


def prepare(adapter,q,config,tts,recognize=transcribe):
    if getattr(adapter,'_cinematic_ready',False):return
    root=Path(config['project']);file=root/'cinematic_source.json'
    committed=(root/'animate_media.json').exists() or any(s.get('video_path') or s.get('image_path') for s in adapter.zb_scenes)
    if file.exists():
        stored=json.loads(file.read_text('utf-8'))
        if stored['script']!=config['script']:raise ValueError('Cinematic source narration changed. Use a new Animate project; existing work retained.')
        source=stored['scenes']
    else:
        if committed:raise ValueError('Use a new empty Animate project for Narration-first cinematic mode. Existing media/checkpoints are preserved.')
        source=copy.deepcopy(adapter.zb_scenes)
        atomic_json(file,{'script':config['script'],'scenes':source})
    legacy_source=copy.deepcopy(source)
    if config.get('character_consistency'):
        from ai_studio_animate_cast import reviewed
        reviewed(config,source)
    config.update(animate_clip_seconds=8,animate_multishot=True)
    from ai_studio_narration import settings_for
    settings,_=settings_for(config)
    public_voice={k:v for k,v in settings.items() if k.startswith(('tts_','gemini_tts_','kokoro_','piper_','cloud_tts_')) or k=='use_cloud_tts'}
    identity=fingerprint('cinematic-v1',config['script'],public_voice,config['voice_engine'],config['style'],
        config.get('continuity',''),config.get('reference_design',''),config.get('character_names',''),config.get('place_name',''),
        config.get('animation_mode','partial'),config.get('partial_animation_unit','scenes'),config.get('animate_count',3),config.get('animate_seconds',80))
    legacy_identity=identity
    if config.get('cinematic_ready_prompts'):legacy_identity=fingerprint(legacy_identity,'ready-source-prompts-v1',legacy_source)
    if config.get('character_consistency'):identity=fingerprint(identity,'full-cast-v1',config['cast_assets'],config['scene_reference_map'])
    if config.get('cinematic_ready_prompts'):identity=fingerprint(identity,'ready-source-prompts-v1',source)
    folder=root/'cinematic'/identity[:16];folder.mkdir(parents=True,exist_ok=True)
    cache_file=folder/'storyboard.json'
    legacy_cache=root/'cinematic'/legacy_identity[:16]/'storyboard.json'
    if config.get('character_consistency') and not cache_file.exists() and legacy_cache.exists():
        cache_file=legacy_cache;folder=legacy_cache.parent
        q.put(('log','info','Adding cast metadata to the existing reviewed cinematic timeline; saved narration, shots and images are reused.'))
    if cache_file.exists():
        cache=json.loads(cache_file.read_text('utf-8'))
        rows=cache['scenes']
        if all(valid_audio(s['audio_path']) for s in rows):
            current={s.get('id'):s for s in adapter.zb_scenes}
            for row in rows:
                old=current.get(row['id'],{})
                if old.get('audio_key')==row['audio_key']:
                    row.update({k:v for k,v in old.items() if k.startswith(('image_','video_','manual_'))})
            if config.get('character_consistency'):reviewed(config,rows)
            adapter.zb_scenes=rows;config['scene_reference_map']=[s['reference_names'] for s in rows]
            adapter._cinematic_ready=True;adapter._zb_save_project(config)
            q.put(('log','info','Reusing the locked cinematic narration, eight-second timeline and continuity storyboard.'))
            return
    if committed:raise ValueError('Cinematic timing/design changed after media generation. Restore its settings or use a new Animate project; saved clips retained.')
    voice_adapter=SimpleNamespace(zb_scenes=copy.deepcopy(source),_zb_cancel=adapter._zb_cancel,_zb_save_project=lambda c:None)
    continuous_voice(voice_adapter,q,config,tts,recognize)
    rows=clip_rows(voice_adapter.zb_scenes,config,folder)
    if config.get('character_consistency'):reviewed(config,rows)
    from ai_studio_animate_setup import reference_plan
    from ai_studio_animate_options import reference_mode
    definitions=[] if reference_mode(config)=='none' else (
        [{'name':Path(p).stem,'kind':'image','prompt':'Use the exact approved reference pixels.'} for p in config['references']]
        if config.get('references') and not config.get('character_consistency') else reference_plan(config))
    allowed={r['name'] for r in definitions}
    plan_file=folder/'planning.json'
    completed=json.loads(plan_file.read_text('utf-8')).get('clips',[]) if plan_file.exists() else []
    if len(completed)>len(rows):raise RuntimeError('Cinematic planning checkpoint is inconsistent; saved work retained.')
    video_rows=[row for row in rows if row['cinematic_kind']=='video']
    # Old partial checkpoints may contain image rows. Keep their validated work.
    completed=completed[:len(video_rows)]
    previous=completed[-1] if completed else None
    ready=config.get('cinematic_ready_prompts',False)
    if config.get('planning_source')=='chatgpt_ready' and not ready and len(completed)<len(video_rows):
        raise ValueError('Ready JSON needs cinematic shot and continuity directions. Import the complete Video + Image JSON; Gemini director is disabled for ready imports.')
    if ready and not completed:
        for row in video_rows:
            visuals=row['source_visuals']
            if not visuals or any(not v['visual_prompt'].strip() for v in visuals):raise ValueError('Ready cinematic video prompts are missing; import both complete JSON files.')
            directed=[v for v in visuals if v['continuity'] and v['shots']]
            if not directed:
                directed=[v for source_scene in source for v in [{'continuity':source_scene.get('cinematic_continuity',{}),'shots':source_scene.get('shots',[]),'visual_prompt':source_scene.get('visual_prompt','')}] if v['continuity'] and v['shots']][-1:]
            first=directed[0] if directed else visuals[0];last=directed[-1] if directed else visuals[-1];state=first['continuity']
            if not state:raise ValueError('Ready video JSON needs continuity states for each source clip.')
            count=min(4,max(2,sum(len(v['shots']) for v in visuals)))
            actions=[shot['visual_prompt'] for v in visuals for shot in v['shots']]
            if not actions:actions=[v['visual_prompt'] for v in visuals]
            if len(actions)==1:actions.append('Hold the established action and show its natural reaction; no new event.')
            if len(actions)<2:raise ValueError('Ready video clips require 2-4 shot directions.')
            shots=[{'start':round(i*8/count,6),'end':8 if i==count-1 else round((i+1)*8/count,6),
                    'visual_prompt':' '.join(actions[math.floor(i*len(actions)/count):math.floor((i+1)*len(actions)/count)]) or 'Hold the established composition and action.'} for i in range(count)]
            item={'clip':row['id'],'visual_prompt':'\n'.join(v['visual_prompt'] for v in visuals),
                  'location':state['location'],'start_state':state['start_state'],'end_state':last['continuity']['end_state'],
                  'continues_previous':bool(previous and state.get('continues_previous') and previous['location']==state['location']),
                  'references':sorted({r for v in visuals for r in v['references']}),'shots':shots}
            if item['continues_previous']:item['start_state']=previous['end_state']
            completed.extend(validate_plan(json.dumps([item]),[row],allowed,previous));previous=item
        atomic_json(plan_file,{'clips':completed,'ready_prompts':True})
        q.put(('log','info','Imported video directions mapped to measured audio windows locally; Gemini director skipped. Review timings before generation.'))
    for start in range(len(completed),len(video_rows),4):
        check_cancel(adapter._zb_cancel)
        group=video_rows[start:start+4]
        request={'title':config.get('title',''),'story_context':config.get('continuity','')[:3000],'style':config['style'],
            'continuity':config.get('continuity','')[:3000],'references':[{'name':r['name'],'kind':r['kind'],
                'design':config.get('reference_descriptions',{}).get(r['name'],config.get('reference_design',''))[:700]} for r in definitions],
            'previous_end_state':previous,'preceding_narration':rows[start-1]['narration'] if start else '',
            'following_narration':rows[start+len(group)]['narration'] if start+len(group)<len(rows) else '',
            'clips':[{'clip':s['id'],'start':s['cinematic_start'],'end':s['cinematic_end'],'used_duration':s['cinematic_end']-s['cinematic_start'],
                      'media_type':s['cinematic_kind'],'narration':s['narration'],'source_visuals':s['source_visuals'],'word_timings':s['word_timings']} for s in group]}
        q.put(('log','info',f'Cinematic director: VIDEO clips {start+1}-{start+len(group)}/{len(video_rows)} only; image prompts reused locally.'))
        error=None
        for attempt in range(2):
            raw,error=adapter._zb_llm(SYSTEM+('\nFix the previous validation issue: '+str(error) if attempt else ''),json.dumps(request,ensure_ascii=False),max_tokens=6500,provider='gemini')
            if error:break
            try:batch=validate_plan(raw,group,allowed,previous);break
            except RuntimeError as exc:error=str(exc)
        if error:raise RuntimeError('Cinematic storyboard paused: '+str(error)+'. Narration and completed planning batches retained.')
        completed.extend(batch);previous=completed[-1]
        atomic_json(plan_file,{'clips':completed})
    for row in rows:
        if row['cinematic_kind']=='video':plan=completed[row['id']-1]
        else:
            visuals=row['source_visuals']
            prompt='\n'.join(dict.fromkeys(v['visual_prompt'] for v in visuals if v['visual_prompt'].strip()))
            if not prompt:
                prompt=('Illustrate this exact narration in the full story context, using the selected visual preset and assigned references. '
                        'Show its concrete subjects and events; do not invent unrelated keyword metaphors, dialogue or embedded text. '
                        'Story title: '+config.get('title','')+'. Narration: '+row['narration'])
                if not ready:q.put(('log','info',f"Image {row['id']}: using local narration-based direction; no Gemini cinematic request."))
            plan={'visual_prompt':prompt,'shots':[],'references':sorted({r for v in visuals for r in v['references']}),
                  'location':visuals[0]['continuity'].get('location','Source narration setting'),
                  'start_state':'Illustrate the original image scene and its narration.','end_state':'Retain reference appearance.','continues_previous':False}
        row.update(visual_prompt=plan['visual_prompt'],shots=plan['shots'],reference_names=plan['references'],
                   cinematic_continuity={k:plan[k] for k in ('location','start_state','end_state','continues_previous')})
    if config.get('character_consistency'):
        reviewed(config,rows)
    atomic_json(cache_file,{'identity':identity,'scenes':rows})
    adapter.zb_scenes=rows;config['scene_reference_map']=[s['reference_names'] for s in rows]
    adapter.zb_last_video=None;adapter._cinematic_ready=True;adapter._zb_save_project(config)
    q.put(('refresh',));q.put(('log','success',f'Locked cinematic timeline: {len(rows)} outputs; continuous narration retained. Generate Agent Media or Build All to continue.'))


def handoff(scenes,records,record,config,cancel,log):
    """Attach the actual preceding clip's last frame only for connected scenes."""
    index=record['index'];row=scenes[index]
    if record['kind']!='video' or not row.get('cinematic_continuity',{}).get('continues_previous') or index==0:return config
    previous=records[index-1]
    if previous['kind']!='video':return config
    from ai_studio_animate_media import valid_video
    if previous['status']!='complete' or not valid_video(previous['output']):
        raise RuntimeError('Previous cinematic clip must be downloaded before its continuation can be submitted.')
    folder=Path(config['project'])/'cinematic_frames';folder.mkdir(parents=True,exist_ok=True)
    frame=folder/f'PreviousClip{index:04d}.png'
    run_ffmpeg(['-sseof','-0.5','-i',previous['output'],'-vf','reverse','-frames:v','1',str(frame)],cancel)
    if not valid_image(frame):raise RuntimeError('Previous clip end-frame could not be verified; no continuation submitted.')
    log(f'Clip {index+1}: attaching actual end-frame {frame.name}; continuing the previous visual state.')
    return {**config,'references':list(config.get('references',[]))+[str(frame)],'cinematic_previous_frame':frame.stem}
