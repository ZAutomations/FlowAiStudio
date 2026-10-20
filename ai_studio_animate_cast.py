"""Shared Studio cast/references for Animate, including measured clip regrouping."""
import json
from pathlib import Path
from ai_studio_pipeline import atomic_json, valid_image
from ai_studio_cast import current, validate, source_key


def remember_existing(config,options):
    """Keep the old public generation context before adding cast metadata."""
    root=Path(config['project']);file=root/'animate_cast_migration.json'
    if config.get('character_consistency') and not options.get('character_consistency') and (root/'animate_media.json').exists() and not file.exists():
        from desktop.storage import public
        from ai_studio_pipeline import fingerprint
        atomic_json(file,{'story_key':fingerprint(config['script']),'options':public(options)})


def adopt_existing_media(plan,state,scenes,config):
    """Adopt casting only after proving the previous scene/model/Flow identity."""
    if not config.get('character_consistency'):return plan,state
    from ai_studio_pipeline import fingerprint
    from ai_studio_animate_media import media_plan,valid_video
    root=Path(config['project']);receipt=root/'animate_cast_migration.json';old=state.get('records',[])
    if len(old)!=len(plan):return plan,state
    effective=[]
    for previous,row in zip(old,plan):
        if (previous.get('reference_current_key')==row['key'] and previous.get('prompt')==row['prompt']
                and previous.get('kind')==row['kind'] and previous.get('index')==row['index']):
            row={**row,'key':previous['key'],'token':previous['token']}
        effective.append(row)
    if state.get('identity')==fingerprint([(r['key'],r['index']) for r in effective],config['flow_url']):return effective,state
    if not receipt.exists():return plan,state
    saved=json.loads(receipt.read_text('utf-8'))
    if saved.get('story_key')!=fingerprint(config['script']):return plan,state
    previous_config={**config,**saved['options'],'character_consistency':saved['options'].get('character_consistency',False),
                     'scene_reference_map':saved['options'].get('scene_reference_map'),'references':saved['options'].get('references',[])}
    if previous_config.get('animate_model')!=config.get('animate_model'):return plan,state
    original=media_plan(scenes,previous_config)
    if state.get('identity')!=fingerprint([(r['key'],r['index']) for r in old],config['flow_url']):return plan,state
    if any(a.get('key')!=b['key'] or a.get('prompt')!=c['prompt'] or a.get('kind')!=c['kind'] or a.get('index')!=c['index']
           for a,b,c in zip(old,original,plan)):return plan,state
    atomic_json(root/'animate_plan_history'/f'{state["identity"]}.json',state)
    prepared='\n'.join(p.read_text('utf-8') for p in root.glob('agent_batch_*.txt'))
    adopted=[];effective=[]
    for previous,row in zip(old,plan):
        issued=(previous.get('status')!='pending' or previous.get('preparation_started') or previous.get('token','__missing__') in prepared
                or (valid_video(previous.get('output','')) if row['kind']=='video' else valid_image(previous.get('output',''))))
        if issued:
            current={**previous,'output':row['output'],'reference_current_key':row['key']}
            effective.append({**row,'key':previous['key'],'token':previous['token']})
        else:current={**row,'status':'pending'};effective.append(row)
        adopted.append(current)
    identity=fingerprint([(r['key'],r['index']) for r in effective],config['flow_url'])
    return effective,{**state,'identity':identity,'records':adopted,'cast_added_preserving_issued_media':True}


def reviewed(config, scenes, approved=True):
    """Validate the original analysis, then map exact narration spans to clips."""
    path=Path(config['project'])/'cast_analysis.json'
    if not path.exists():raise ValueError('Analyze full script or import a ready cast, then review and Approve Cast first.')
    saved=json.loads(path.read_text('utf-8'))
    original=[{'narration':r['narration']} for r in saved.get('scenes',[])]
    data=current(config,original,approved=approved)
    if ' '.join(' '.join(s['narration'].split()) for s in scenes) != ' '.join(' '.join(s['narration'].split()) for s in original):
        raise ValueError('Cast narration differs from the current story. Saved references and media retained.')
    spans=[];position=0
    for row in data['scenes']:
        end=position+len(row['narration'].split());spans.append((position,end,row));position=end
    mapped=[];position=0
    for i,scene in enumerate(scenes):
        end=position+len(scene['narration'].split())
        matching=[row for left,right,row in spans if left<end and right>position]
        refs=list(dict.fromkeys(name for row in matching for name in row['references']))
        # Each approved source scene is already limited to six. A measured
        # multi-shot clip can overlap several scenes: preserve their full union.
        if len(refs)>40:raise ValueError(f'Clip/scene {i+1} exceeds the forty-identity story library.')
        if data.get('approved') and not scene.get('visual_prompt'):
            scene['visual_prompt']='\n'.join(dict.fromkeys(r['visual_prompt'] for r in matching if r['visual_prompt'].strip()))
        mapped.append(refs);position=end
    config.update(cast_assets=data['assets'],reference_descriptions={a['name']:a['description'] for a in data['assets']},
                  scene_reference_map=mapped)
    for scene,refs in zip(scenes,mapped):scene['reference_names']=refs
    return data


def references(adapter,q,config,manual=None):
    if not config.get('character_consistency'):raise ValueError('Enable Full story character/location consistency first.')
    reviewed(config,adapter.zb_scenes)
    from ai_studio_animate_setup import ensure_project,ensure_references
    from ai_studio_consistency import upload_reference_library
    log=lambda m:q.put(('log','info',m))
    config['reference_mode']='characters'
    config['flow_url']=ensure_project(config,adapter._zb_cancel,log)
    supplied=[p.strip() for p in str(config.get('reference_files','')).split('|') if p.strip()]
    expected={a['name'] for a in config['cast_assets']}
    if supplied:
        from desktop.animate import references as check_paths
        supplied=check_paths({**config,'references':supplied})
        if {Path(p).stem for p in supplied}!=expected:raise ValueError('Supplied reference filenames must match all approved characters and locations exactly.')
        config['references']=supplied
    else:config.pop('references',None)
    if manual:
        from ai_studio_manual_references import run
        files=run(config,adapter._zb_cancel,log,download=manual=='download')
        if files is None:return
    else:
        # Approved descriptions already form the design bible; no second LLM call.
        files=ensure_references(config,adapter._zb_cancel,log)
    if {Path(p).stem for p in files}!=expected or any(not valid_image(p) for p in files):
        raise ValueError('Some approved character/location images are missing. Complete references before scene generation.')
    config['references']=files
    adapter._zb_save_project(config)
    upload_reference_library(adapter,config,log)
    q.put(('log','success',f'All {len(files)} reference images ready in Flow. Each clip attaches only its assigned identities.'))


def import_cast(adapter,q,config,value):
    """Cast import also works with saved audio; existing narration never changes."""
    from ai_studio_cast import parse,locked,file
    if file(config).exists() and locked(config):raise ValueError('This project already has reference/media checkpoints. Use its existing approved cast or a new project; saved work retained.')
    data=validate(parse(value),adapter.zb_scenes,config['script'])
    data.update(source_key=source_key(config,adapter.zb_scenes),approved=False)
    atomic_json(file(config),data);config.update(character_consistency=True,reference_mode='characters')
    q.put(('log','success','Cast and location assignments imported. Review and approve before creating references. Existing narration retained.'))


def analyze(adapter,q,config):
    from ai_studio_cast import analyze as discover
    if (Path(config['project'])/'cast_analysis.json').exists():
        data=reviewed(config,adapter.zb_scenes,approved=False)
        q.put(('log','info','Reusing saved full-story cast and assignments. Review and approve to continue.'))
        return data
    if config.get('planning_source')=='chatgpt_ready' or config.get('cinematic_ready_prompts') or config.get('ready_animation_script_key'):
        raise ValueError('Ready JSON has no cast assets. Import the assets and per-scene references from ChatGPT; automatic Gemini discovery is disabled for ready JSON.')
    return discover(adapter,q,config,allow_existing=True)


def approve(adapter,q,config,value):
    from ai_studio_cast import approve as accept
    from types import SimpleNamespace
    data=reviewed(config,adapter.zb_scenes,approved=False)
    original=[{'narration':r['narration']} for r in data['scenes']]
    result=accept(SimpleNamespace(zb_scenes=original),q,config,value,allow_existing=not data.get("approved"))
    reviewed(config,adapter.zb_scenes)
    return result
