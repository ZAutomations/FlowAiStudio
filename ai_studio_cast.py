"""Reviewed cast/location bible and deterministic ready-story import."""
import json
import re
from pathlib import Path
from ai_studio_pipeline import atomic_json, fingerprint, check_cancel

MASTER_PROMPT = '''Read the ENTIRE supplied script and return ONLY JSON in the schema below.
Preserve every narration word in its original language and order. Do not translate, rewrite or add dialogue.
Discover recurring or visually important characters AND recurring places. Merge aliases (DSP, officer, I)
only when the script establishes the same person; an off-screen narrator is not automatically on screen.
Do not invent a cast for explanatory/documentary scenes or turn background extras into recurring heroes.
Use stable unique ASCII identifiers, e.g. DSP, ConstableAli, PoliceStation. Label uncertain visual details
as proposed design choices, not story facts. Keep period, region, ages, clothes and architecture appropriate
to the selected style and full context. Different life stages may need distinct identifiers.
For each scene list ONLY the references visibly needed in that scene. Use [] for diagrams, objects or
scenes without a recurring subject. Do not add a person simply because they narrate or are mentioned.
Each scene may use at most six references. Up to forty reference assets are supported in one story.
If supplied with existing numbered scenes, keep their numbers, count and narration exactly unchanged.
Otherwise split the full script into useful short visual scenes without omitting any words.
Descriptions must define immutable appearance/role or architecture/layout; visual_prompt describes the
actual scene action with those identities. No combined storyboards, embedded text or character speech.
JSON schema:
{"version":1,"title":"Story title","script":"full original narration",
 "assets":[{"name":"DSP","kind":"character","aliases":["officer"],"description":"role, age, face, hair, clothes"},
           {"name":"PoliceStation","kind":"location","aliases":["station"],"description":"architecture and layout"}],
 "scenes":[{"scene":1,"narration":"exact scene narration","references":["DSP","PoliceStation"],"visual_prompt":"scene action"}]}
'''


def parse(value):
    if isinstance(value,dict):return value
    text=str(value or '').strip()
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text,flags=re.I)
    try:result=json.loads(text)
    except ValueError:raise ValueError('Paste the complete ready-story JSON. No files were imported.')
    if not isinstance(result,dict):raise ValueError('The story must be a JSON object.')
    return result


def validate(value,scenes=None,script=None):
    data=parse(value)
    assets=data.get('assets');rows=data.get('scenes')
    if not isinstance(assets,list) or len(assets)>40:raise ValueError('Provide an assets list with at most 40 characters/locations.')
    if not isinstance(rows,list) or not 1<=len(rows)<=3000:raise ValueError('Provide the complete numbered scenes list.')
    names=set();clean=[]
    for a in assets:
        if not isinstance(a,dict):raise ValueError('Each reference asset must be an object.')
        name=a.get('name','');description=a.get('description','');aliases=a.get('aliases',[])
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',name) or name.casefold() in names or re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]',name,re.I):
            raise ValueError('Asset identifiers must be unique simple names such as DSP or PoliceStation.')
        if a.get('kind') not in ('character','location','prop'):raise ValueError('Asset kind must be character, location or prop.')
        if not isinstance(description,str) or not description.strip() or len(description)>8000:raise ValueError('Every asset needs a design description (at most 8000 characters).')
        if not isinstance(aliases,list) or len(aliases)>40 or any(not isinstance(s,str) or len(s)>200 for s in aliases):raise ValueError('Aliases must be a list of short names.')
        names.add(name.casefold());clean.append(dict(name=name,kind=a['kind'],aliases=aliases,description=description.strip()))
    exact={a['name'] for a in clean};mapped=[]
    if scenes is not None and len(rows)!=len(scenes):raise ValueError('Scene count changed. Analyze again using the current parsed scenes.')
    for i,row in enumerate(rows):
        if not isinstance(row,dict) or type(row.get('scene')) is not int or row['scene']!=i+1:raise ValueError('Scene numbers must start at 1 and be consecutive.')
        text=row.get('narration');refs=row.get('references');visual=row.get('visual_prompt','')
        if not isinstance(text,str) or not text.strip():raise ValueError('Every scene needs its unchanged narration.')
        if scenes is not None and text!=scenes[i]['narration']:raise ValueError(f'Scene {i+1}: narration changed. Keep it verbatim.')
        if not isinstance(refs,list) or len(refs)>6 or any(not isinstance(n,str) or n not in exact for n in refs) or len(set(refs))!=len(refs):
            raise ValueError(f'Scene {i+1}: use at most six distinct declared reference identifiers.')
        if not isinstance(visual,str) or len(visual)>20000:raise ValueError('Visual prompts must be text, at most 20000 characters.')
        mapped.append(dict(scene=i+1,narration=text,references=refs,visual_prompt=visual))
    narration=' '.join(r['narration'] for r in mapped)
    if scenes is None and script is not None and ' '.join(narration.split())!=' '.join(script.split()):
        raise ValueError('Scene narration must preserve the full original script, without missing, added or reordered words.')
    return dict(version=1,title=str(data.get('title',''))[:300],script=script if script is not None else narration,assets=clean,scenes=mapped)


def source_key(config,scenes):
    return fingerprint(config['script'],config['style'],config.get('reference_design',''),config.get('continuity',''),[s['narration'] for s in scenes])


def file(config):return Path(config['project'])/'cast_analysis.json'


def locked(config):
    root=Path(config['project'])
    return any((root/p).exists() for p in ('references/reference_plan.json','studio_agent_images.json','animate_media.json','images/image_batches.json'))


def current(config,scenes,approved=False):
    path=file(config)
    if not path.is_file():return None
    data=json.loads(path.read_text('utf-8'))
    if data.get('source_key')!=source_key(config,scenes):
        from ai_studio_story import PUNJAB_DSP_STYLE,PUNJAB_DSP_COLORMIX_STYLE
        from ai_studio_pipeline import STYLE_PRESETS
        previous={**config,'style':STYLE_PRESETS[PUNJAB_DSP_STYLE]}
        if (config.get('style_name')==PUNJAB_DSP_COLORMIX_STYLE
                and data.get('source_key')==source_key(previous,scenes)):
            # Only the known DSP visual variant is compatible. Script, scene
            # narration, continuity and reference design remain hash-checked.
            config['_dsp_previous_style']=STYLE_PRESETS[PUNJAB_DSP_STYLE]
        else:
            raise ValueError('Script, scenes or design settings changed after cast analysis. Analyze again before generating.')
    validate(data,scenes,config['script'])
    if approved and not data.get('approved'):raise ValueError('Review and approve the cast and scene references before generating.')
    return data


def bind_mapping_narration(rows,scenes,start=0):
    """AI maps visuals by immutable scene ID; source narration stays local.

    This is only for generated analysis. Ready-story imports and user review
    continue through strict validation, including verbatim narration checks.
    """
    if (not isinstance(rows,list) or len(rows)!=len(scenes)
        or any(not isinstance(row,dict) or type(row.get('scene')) is not int
               or row['scene']!=start+i+1 for i,row in enumerate(rows))):
        raise ValueError(f'Scene mapping {start+1}–{start+len(scenes)} returned incomplete or reordered scene IDs; completed analysis batches retained.')
    return [{**row,'narration':scene['narration']} for row,scene in zip(rows,scenes)]


MAPPING_ONLY = ('The supplied scene numbers and narration are immutable source data. '
                'For each scene return only scene, references and visual_prompt. '
                'OMIT narration in your response: the application copies it verbatim locally by scene number. '
                'Do not merge, split, omit, duplicate or reorder scene numbers. '
                'Interpret each visual using its original supplied narration and the full script.')


def analyze_long(adapter,q,config,context):
    """Keep full-story identity context while bounding scene-mapping replies."""
    path=Path(config['project'])/'cast_analysis_progress.json';key=source_key(config,adapter.zb_scenes)
    progress=json.loads(path.read_text('utf-8')) if path.is_file() else {}
    if progress.get('source_key')!=key:
        raw,error=adapter._zb_llm(MASTER_PROMPT+'\nTHIS CALL: return ONLY {"assets":[...]}. Discover the complete cast/places from the full script. Do not return scene mappings yet.',
            json.dumps({k:v for k,v in context.items() if k!='scenes'},ensure_ascii=False),max_tokens=12000,provider=config.get('llm','gemini'),json_mode=True)
        if error:raise RuntimeError('Full-story cast discovery failed: '+str(error))
        assets=parse(raw).get('assets')
        assets=validate({'assets':assets,'scenes':[dict(scene=1,narration='Validation only.',references=[])]})['assets']
        progress=dict(source_key=key,assets=assets,scenes=[])
        atomic_json(path,progress)
    done=progress.get('scenes',[])
    if done:
        validate({'assets':progress['assets'],'scenes':done},adapter.zb_scenes[:len(done)],config['script'])
    if len(done)>len(adapter.zb_scenes):raise ValueError('Saved cast analysis progress exceeds the current scene count.')
    size=max(1,min(30,int(progress.get('mapping_batch_size',30))))
    single_retries=0
    while len(done)<len(adapter.zb_scenes):
        check_cancel(adapter._zb_cancel)
        start=len(done);batch=context['scenes'][start:start+size]
        q.put(('log','info',f'Cast mapping scenes {start+1}–{start+len(batch)} / {len(adapter.zb_scenes)}; full-story identities retained.'))
        raw,error=adapter._zb_llm(MASTER_PROMPT+'\nTHIS CALL: return ONLY {"scenes":[...]}, for exactly the supplied scene numbers. Assets are fixed; use only their identifiers. Do not return or redesign assets. '+MAPPING_ONLY,
            json.dumps({**context,'assets':progress['assets'],'scenes':batch},ensure_ascii=False),max_tokens=16000,provider=config.get('llm','gemini'),json_mode=True)
        if error and not str(error).startswith('[INVALID_JSON]'):
            raise RuntimeError('Scene reference mapping failed; completed analysis batches retained: '+str(error))
        try:
            if error:raise ValueError(str(error))
            try:generated=parse(raw)
            except ValueError:raise ValueError('Model returned malformed or incomplete JSON for scene mapping.')
            rows=bind_mapping_narration(generated.get('scenes'),adapter.zb_scenes[start:start+len(batch)],start)
            local=[{**r,'scene':i+1} for i,r in enumerate(rows)]
            checked=validate({'assets':progress['assets'],'scenes':local},adapter.zb_scenes[start:start+len(batch)],config['script'])['scenes']
        except ValueError as failure:
            if size==1 and single_retries>=1:
                raise ValueError(f'Cast mapping scene {start+1} repeatedly returned invalid structured output. Completed analysis batches retained. {failure}') from failure
            if size>1:size=max(1,size//2)
            else:single_retries+=1
            progress['mapping_batch_size']=size
            check_cancel(adapter._zb_cancel);atomic_json(path,progress)
            q.put(('log','warn',f'Invalid model mapping for scenes {start+1}–{start+len(batch)}. Retrying from scene {start+1} with {size} scene(s) per call; fixed cast and saved narration retained.'))
            continue
        single_retries=0
        done.extend({**r,'scene':start+i+1} for i,r in enumerate(checked))
        progress['scenes']=done;check_cancel(adapter._zb_cancel);atomic_json(path,progress)
    return validate({**context,'assets':progress['assets'],'scenes':done},adapter.zb_scenes,config['script'])


def analyze(adapter,q,config,allow_existing=False):
    check_cancel(adapter._zb_cancel)
    try:saved=current(config,adapter.zb_scenes)
    except ValueError:
        if locked(config):raise ValueError('This project already has submitted references/media. Use a new video for a changed script or cast.')
        saved=None
    if saved:
        q.put(('log','info','Saved cast analysis ready. Review characters, locations and scene references, then Approve Cast.'))
        return saved
    if locked(config) and not allow_existing:raise ValueError('Use a new video to analyze automatic casting; existing reference/media checkpoints are retained.')
    context=dict(title=config['title'],script=config['script'],style=config['style'],design=config.get('reference_design',''),
                 continuity=config.get('continuity',''),scenes=[dict(scene=i+1,narration=s['narration']) for i,s in enumerate(adapter.zb_scenes)])
    q.put(('log','info','Analyzing the full script: recurring identities, aliases, locations and visible subjects per scene…'))
    if len(adapter.zb_scenes)>30:
        data=analyze_long(adapter,q,config,context)
    else:
        raw,error=adapter._zb_llm(MASTER_PROMPT+'\nTHIS CALL: '+MAPPING_ONLY,json.dumps(context,ensure_ascii=False),max_tokens=16000,provider=config.get('llm','gemini'),json_mode=True)
        if error:raise RuntimeError('Cast analysis failed: '+str(error))
        generated=parse(raw)
        generated={**generated,'scenes':bind_mapping_narration(generated.get('scenes'),adapter.zb_scenes)}
        data=validate(generated,adapter.zb_scenes,config['script'])
    data.update(source_key=source_key(config,adapter.zb_scenes),approved=False)
    check_cancel(adapter._zb_cancel);atomic_json(file(config),data)
    q.put(('log','success',f"Analysis ready: {len(data['assets'])} reference assets, {len(data['scenes'])} scenes. Review and Approve Cast before references are created. No images submitted."))
    return data


def approve(adapter,q,config,value,allow_existing=False):
    data=validate(value,adapter.zb_scenes,config['script'])
    saved=current(config,adapter.zb_scenes)
    if not allow_existing and locked(config) and (not saved or validate(saved,adapter.zb_scenes,config['script'])!=data):
        raise ValueError('References/media already use this cast. Use a new video to change it; saved work is retained.')
    data.update(source_key=source_key(config,adapter.zb_scenes),approved=True)
    atomic_json(file(config),data)
    for scene,row in zip(adapter.zb_scenes,data['scenes']):
        if not scene.get('visual_prompt') and row.get('visual_prompt'):scene['visual_prompt']=row['visual_prompt']
    q.put(('log','success','Cast and per-scene reference assignments approved. Next: Create / reuse reference images.'))
    return data


def import_ready(adapter,q,config,value):
    if locked(config) or any(s.get('audio_path') or s.get('image_path') for s in adapter.zb_scenes):
        raise ValueError('Import into a new video project; existing media and audio are retained.')
    raw=parse(value);script=raw.get('script')
    if not isinstance(script,str) or not script.strip():raise ValueError('Ready story needs the complete original script field.')
    data=validate(raw,script=script)
    if ' '.join(script.split())!=' '.join(config['script'].split()):raise ValueError('Ready-story script differs from the Script field.')
    adapter.zb_scenes=[dict(id=i+1,raw=r['narration'],source_line=i+1,narration=r['narration'],visual_prompt=r['visual_prompt'],caption='') for i,r in enumerate(data['scenes'])]
    config['character_consistency']=True
    data.update(source_key=source_key(config,adapter.zb_scenes),approved=False)
    atomic_json(file(config),data)
    atomic_json(Path(config['project'])/'ready_story_source.json',raw)
    adapter._zb_save_project(config)
    q.put(('log','success','Ready story imported to project files without AI rewriting. Review cast and scene assignments, then Approve Cast.'))
