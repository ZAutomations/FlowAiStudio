"""Additive clip continuity metadata. Never edits audio, scenes or media identities."""
import copy,json,re
from pathlib import Path
from ai_studio_pipeline import atomic_json,fingerprint,check_cancel

SECTIONS={'characters':{'location','wardrobe','props','injuries','emotion'},
          'props':{'description','holder','location','condition'},
          'clues':{'description','status','known_by'},'scene':{'location','time','lighting','planned_state'}}
SYSTEM='''Maintain a detailed film continuity ledger for the EXISTING supplied clip plan.
Return ONLY [{"clip":number,"updates":[{"section":"characters|props|clues|scene","id":"StableIdentifier",
"fields":{"field":"value"},"evidence":"exact quote from THIS clip or approved design"}]}].
For scene use id "scene". Characters fields: location, wardrobe, props, injuries, emotion (strings).
Props fields: description, holder, location, condition (strings). Clues: description,status (strings),known_by (array of character IDs).
Scene fields: location,time,lighting (strings). Use only supplied character IDs. Give objects/clues stable simple IDs.
Keep every unmodified fact from previous state, including people off-screen. Injuries do not heal, objects do not
change holder, clues do not become known, clothes and emotions do not reset merely because a new clip starts.
Emit only changes supported by this clip's narration, existing visual direction or approved character design.
Do not invent injuries, clues, evidence, props, plot events or future revelations. Leave unspecified details unknown.
Evidence must quote an exact supporting passage from this clip/design, not an explanation you invented.
When narration changes time/place, update the scene explicitly but carry other facts unless a change is supported.
At most 24 updates per clip. These are PLANNED facts, not a claim that existing generated footage was inspected.
Do not return/rewrite narration, visual prompts, shots or timing. Do not generate media.'''

def path(config):return Path(config['project'])/'continuity_ledger.json'
def scene_key(scene):return fingerprint('continuity-scene-v1',scene.get('id'),scene['narration'],scene.get('visual_prompt',''),scene.get('shots',[]),scene.get('cinematic_continuity',{}))
def video_rows(scenes,config):
    from ai_studio_animate_options import animation_count
    count=animation_count(config,len(scenes),scenes)
    return [s for i,s in enumerate(scenes) if s.get('cinematic_kind','video' if i<count else 'image')=='video']
def designs(config):
    file=Path(config['project'])/'cast_analysis.json'
    if file.exists():
        data=json.loads(file.read_text('utf-8'))
        if not data.get('approved'):raise ValueError('Review and Approve Cast before preparing the continuity ledger.')
        return {a['name']:a['description'] for a in data['assets'] if a['kind']=='character'}
    return {n.strip():config.get('reference_descriptions',{}).get(n.strip(),config.get('reference_design','')) for n in config.get('character_names','').split(',') if n.strip()}
def baseline(cast):
    return {'characters':{name:{'appearance':description} for name,description in cast.items()},'props':{},'clues':{},'scene':{}}
def support(scene,cast):return ' '.join((scene['narration'],scene.get('visual_prompt',''),json.dumps(scene.get('shots',[]),ensure_ascii=False),json.dumps(scene.get('cinematic_continuity',{}),ensure_ascii=False),*cast.values()))
def apply(state,updates,scene,cast):
    if not isinstance(updates,list) or len(updates)>24:raise ValueError('Ledger updates must be an array of at most 24 changes per clip.')
    result=copy.deepcopy(state);evidence_source=' '.join(support(scene,cast).split())
    for event in updates:
        if not isinstance(event,dict):raise ValueError('Each ledger change must be an object.')
        section=event.get('section');name=event.get('id');fields=event.get('fields');quote=event.get('evidence')
        if section not in SECTIONS or not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',name):raise ValueError('Invalid continuity section or identifier.')
        if section=='characters' and name not in cast:raise ValueError('Ledger character is not in the approved cast: '+name)
        if section=='scene' and name!='scene':raise ValueError('Scene changes must use id scene.')
        if not isinstance(fields,dict) or not fields or not set(fields)<=SECTIONS[section]:raise ValueError('Invalid ledger state fields.')
        if not isinstance(quote,str) or len(quote.strip())<4 or ' '.join(quote.split()) not in evidence_source:raise ValueError('Ledger change needs an exact supporting quote from this clip or approved design.')
        for key,value in fields.items():
            if key=='known_by':
                if not isinstance(value,list) or any(n not in cast for n in value):raise ValueError('Clue knowledge must name approved characters.')
            elif not isinstance(value,str) or not value.strip() or len(value)>1000:raise ValueError('Ledger state values must be short nonempty text.')
        target=result['scene'] if section=='scene' else result[section].setdefault(name,{})
        target.update(copy.deepcopy(fields))
        if len(result['props'])>160 or len(result['clues'])>160:raise ValueError('Continuity ledger contains too many distinct objects/clues.')
    return result
def make_entry(scene,updates,state,cast):
    after=apply(state,updates,scene,cast)
    return {'clip':scene['id'],'source_key':scene_key(scene),'updates':copy.deepcopy(updates),'before':copy.deepcopy(state),'after':after,
            'basis':'existing narration and planned visuals; generated footage not visually audited'}
def read(config,scenes):
    file=path(config)
    if not file.exists():return None
    data=json.loads(file.read_text('utf-8'));rows=video_rows(scenes,config)
    if data.get('story_key')!=fingerprint(config['script']):raise ValueError('Ledger belongs to another narration. Existing work retained.')
    entries=data.get('entries',[])
    if len(entries)>len(rows) or any(e.get('clip')!=s['id'] or e.get('source_key')!=scene_key(s) for e,s in zip(entries,rows)):
        raise ValueError('The saved clip plan differs from its continuity ledger. Restore the matching plan; no audio/media was changed.')
    return data
def build(adapter,q,config):
    rows=video_rows(adapter.zb_scenes,config)
    if not rows:raise ValueError('No video clips in this plan. Images continue through their existing workflow.')
    if config.get('animate_narration_mode')=='cinematic' and any('cinematic_start' not in s for s in rows):raise ValueError('Plan Cinematic Clips first; ledger preparation never generates narration or replaces a plan.')
    cast=designs(config);data=read(config,adapter.zb_scenes) or {'version':1,'story_key':fingerprint(config['script']),'initial':baseline(cast),'entries':[]}
    entries=data['entries'];state=entries[-1]['after'] if entries else data['initial']
    # Resume completed metadata, never rerun completed analysis batches.
    while len(entries)<len(rows):
        check_cancel(adapter._zb_cancel);group=rows[len(entries):len(entries)+4]
        if all('continuity_updates' in s for s in group):batch=[{'clip':s['id'],'updates':s['continuity_updates']} for s in group]
        elif config.get('planning_source')=='chatgpt_ready' or config.get('cinematic_ready_prompts') or config.get('ready_animation_script_key'):
            batch=[]
            for scene in group:
                c=scene.get('cinematic_continuity',{});updates=scene.get('continuity_updates',[])
                if not updates and c.get('end_state'):
                    updates=[{'section':'scene','id':'scene','fields':{'location':c['location'],'planned_state':c['end_state']},'evidence':c['end_state']}]
                batch.append({'clip':scene['id'],'updates':updates})
            q.put(('log','info','Using imported continuity locally; no Gemini planning. Unspecified injuries, props and clue knowledge remain unknown.'))
        else:
            request={'title':config.get('title',''),'characters':cast,'previous_state':state,
                     'clips':[{'clip':s['id'],'narration':s['narration'],'visual_prompt':s.get('visual_prompt',''),'shots':s.get('shots',[]),'continuity':s.get('cinematic_continuity',{})} for s in group]}
            q.put(('log','info',f'Continuity metadata only: clips {group[0]["id"]}–{group[-1]["id"]}. Saved narration, plan and media are unchanged.'))
            # This schema is a top-level array; the shared json_mode validator
            # accepts objects only. Parse and validate the array locally below.
            raw,error=adapter._zb_llm(SYSTEM,json.dumps(request,ensure_ascii=False),max_tokens=6500,provider='gemini',json_mode=False)
            if error:raise RuntimeError('Ledger analysis paused; completed entries retained: '+str(error))
            try:batch=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',str(raw).strip(),flags=re.I))
            except ValueError as exc:raise ValueError('Ledger returned incomplete JSON. Saved work retained; retry resumes metadata only.') from exc
        if not isinstance(batch,list) or len(batch)!=len(group) or any(not isinstance(e,dict) or e.get('clip')!=s['id'] for e,s in zip(batch,group)):raise ValueError('Ledger clip order/count changed. Saved work retained.')
        pending=[]
        for item,scene in zip(batch,group):
            entry=make_entry(scene,item.get('updates'),state,cast);pending.append(entry);state=entry['after']
        entries.extend(pending);atomic_json(path(config),data)
    q.put(('log','success',f'Continuity ledger ready for {len(entries)} video clips. Existing narration, plans and images retained. Review before submitting new clips.'))
    return data
def save_review(adapter,q,config,value):
    old=read(config,adapter.zb_scenes)
    if not old:raise ValueError('Prepare the continuity ledger first.')
    rows=video_rows(adapter.zb_scenes,config);edits=value.get('entries') if isinstance(value,dict) else None
    if not isinstance(edits,list) or len(edits)!=len(old['entries']):raise ValueError('Keep all ledger clip numbers and entries.')
    manifest=Path(config['project'])/'animate_media.json';issued=set()
    if manifest.exists():
        prepared='\n'.join(p.read_text('utf-8') for p in Path(config['project']).glob('agent_batch_*.txt'))
        issued={r['index']+1 for r in json.loads(manifest.read_text('utf-8')).get('records',[]) if r.get('status')!='pending' or r.get('preparation_started') or r.get('token','__missing_token__') in prepared}
    cast=designs(config);state=old['initial'];entries=[]
    for previous,edit,scene in zip(old['entries'],edits,rows):
        if not isinstance(edit,dict) or edit.get('clip')!=scene['id']:raise ValueError('Keep ledger clip numbers unchanged.')
        if (scene['id'] in issued or scene.get('video_path') or scene.get('image_path')) and edit.get('updates')!=previous['updates']:raise ValueError(f'Clip {scene["id"]} already has media or an issued request. Its ledger is locked; existing assets retained.')
        entry=make_entry(scene,edit.get('updates'),state,cast)
        if (scene['id'] in issued or scene.get('video_path') or scene.get('image_path')) and (entry['before']!=previous['before'] or entry['after']!=previous['after']):
            raise ValueError(f'Clip {scene["id"]} already has issued/generated media. Earlier edits would change its locked continuity state; existing assets retained.')
        entries.append(entry);state=entry['after']
    atomic_json(path(config),{**old,'entries':entries});q.put(('log','success','Upcoming continuity changes saved; existing media retained.'))
def prompt_context(records,config):
    if not config.get('continuity_ledger_enabled') or not any(r['kind']=='video' for r in records):return ''
    file=path(config)
    if not file.exists():raise ValueError('Prepare the continuity ledger before submitting new clips.')
    by_id={e['clip']:e for e in json.loads(file.read_text('utf-8'))['entries']};parts=[]
    for record in records:
        if record['kind']!='video':continue
        entry=by_id.get(record['index']+1)
        if not entry or entry['source_key']!=record.get('continuity_source_key'):raise ValueError('Ledger does not match this video clip. Prepare/review it before submission; saved work retained.')
        parts.append({'output':record['index']+1,'before':entry['before'],'after':entry['after'],'permitted_changes':entry['updates']})
    return ('\nDETAILED CONTINUITY LEDGER (planned state): retain props and their holders, injuries, clue knowledge, wardrobe and emotions. '
            'Apply only these supported changes; never reset hidden/off-screen characters. Show only this scene’s assigned visible subjects.\n'+json.dumps(parts,ensure_ascii=False)) if parts else ''
