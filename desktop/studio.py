"""Read-only Tk Studio defaults and desktop workflow normalization."""
from pathlib import Path
import importlib.util
import os
import re
import shutil
from .storage import ROOT, public, read, atomic

def metadata(settings, root=ROOT):
    from .browser_accounts import profiles
    from ai_studio_motion import STYLES
    from ai_studio_pipeline import STYLE_PRESETS
    try:
        draft = public(read(Path(settings.get('zb_draft_path') or ROOT/'zbot_profiles/ai_studio_draft.json')))
    except (OSError, ValueError):
        draft = {}
    controls = draft.get('controls', {})
    mapping = {'style':'style_name','captions':'use_captions_tab','transitions_tab':'use_transitions_tab','effects_tab':'use_effects_tab'}
    defaults = {'title':settings.get('zb_title',''), 'provider':settings.get('zb_image_provider','gemini'),
        'llm':settings.get('llm_provider','gemini' if settings.get('gemini_api_key') else 'openai'),
        'resolution':settings.get('zb_resolution','1920x1080'), 'voice_engine':settings.get('tts_engine','google_cloud'),
        'style_name':settings.get('zb_style','Cinematic realistic'), 'custom_style':settings.get('zb_custom_style',''),
        'continuity':settings.get('zb_continuity',''), 'shot_seconds':settings.get('zb_shot_seconds',7),
        'image_batch_size':settings.get('zb_image_batch_size',6), 'chrome_mode':settings.get('zb_chrome_mode',True),
        'share_google_profile':settings.get('zb_flow_share_google_profile',True), 'show_browser':settings.get('zb_show_browser',True),
        'output_dir':settings.get('output_dir',settings.get('output_folder','FinalVideos')),
        'flow_url':settings.get('zb_flow_project_url',''), 'auto_project':True,'agent_tool_dir':str(root/'animate_flow_backend'),
        'narration_style':'auto','narration_direction':'',
        'character_consistency':False,'auto_cast':True,'character_names':'DSP, HelpingPoliceman','place_name':'PoliceStation','reference_design':'','reference_files':'',
        'bgm':bool(settings.get('bgm_file')), 'fallback':True, 'motion':True,'thumbnail_enabled':True,'thumbnail_count':1,
        'use_captions_tab':settings.get('zb_captions',True),'use_transitions_tab':False,'use_effects_tab':False}
    defaults.update({mapping.get(k,k):v for k,v in controls.items()})
    defaults.update(script=draft.get('script',''),project=draft.get('project') or '')
    from ai_studio_narration import STYLES as NARRATION_STYLES
    pool=settings.get('gemini_api_keys',[])
    if isinstance(pool,str):pool=re.split(r'[,\s]+',pool)
    count=len({str(key).strip() for key in [settings.get('gemini_api_key',''),*(pool or [])] if str(key).strip()})
    return {'gemini_key_count':count,'narration_styles':[[key,value[0]] for key,value in NARRATION_STYLES.items()],'defaults':defaults,'scenes':draft.get('scenes',[]),'package':draft.get('package',{}),
        'accounts':profiles(root), 'styles':list(STYLE_PRESETS),'motion_styles':list(STYLES.items()),'playwright':importlib.util.find_spec('playwright') is not None}

def project_name(title):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f_]+', ' ', str(title or ''))
    name = re.sub(r'\s+', ' ', name).strip(' .')[:120].rstrip(' .') or 'Untitled project'
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I):
        name = 'Project ' + name
    return name


def reference_inventory(project,data=None):
    """Discover completed references even when generation paused mid-plan."""
    project=Path(project)
    data=data if data is not None else read(project/'project.json')
    declared={}
    for file in data.get('options',{}).get('references',[]):
        path=Path(file);path=path if path.is_absolute() else project/path
        declared[path.stem]=path
    for ref in read(project/'references/reference_plan.json').get('references',[]):
        name=ref.get('name','')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',name):continue
        path=Path(ref.get('output') or project/'references'/(name+'.png'))
        if not path.is_absolute():path=project/path
        declared.setdefault(name,path)
    from ai_studio_pipeline import valid_image
    saved=[];missing=[]
    for name,path in list(declared.items())[:40]:
        candidates=[path]+[project/'references'/(name+ext) for ext in ('.png','.jpg','.jpeg','.webp')]
        found=next((p for p in candidates if valid_image(p)),None)
        if found:saved.append({'name':name,'path':str(found)})
        else:missing.append(name)
    return {'references':saved,'missing':missing,'expected':len(declared)}

def adopt_existing_flow(config,recover_only=False):
    """Migrate existing image queues without giving them a different Flow URL."""
    file=Path(config['project'])/'flow_project.json'
    if file.exists():return
    queue=read(Path(config['project'])/'images/image_batches.json')
    existing=queue.get('provider')=='flow' and bool(queue.get('requests'))
    if existing or recover_only:
        saved_url=read(Path(config['project'])/'project.json').get('options',{}).get('flow_url','')
        url=saved_url or config.get('flow_url','')
        if not re.fullmatch(r'https://(?:flow\.google\.com|labs\.google)/(?:fx/tools/flow/)?project/[A-Za-z0-9-]+(?:[/?].*)?',url):
            raise ValueError('This image queue needs its original Flow project URL to resume. Enter that URL; no new Flow project was created.')
        atomic(file,{'url':url,'status':'ready','adopted_existing':True})

def copy_project(source, destination, cancel):
    """Save as a new title without moving or overwriting the original project."""
    from ai_studio_pipeline import check_cancel
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not (source/'project.json').is_file():
        raise ValueError('The source project is missing')
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('The new project must be outside the source project')
    for folder, _, files in os.walk(source):
        check_cancel(cancel)
        target = destination/Path(folder).relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for filename in files:
            check_cancel(cancel)
            original = Path(folder)/filename
            if original == source/'project.json':
                continue
            output = target/filename
            if not output.exists():
                temporary = output.with_name(output.name+'.copying')
                shutil.copy2(original, temporary)
                temporary.replace(output)
    if not (destination/'project.json').exists():
        def rebase(value):
            if isinstance(value, dict):return {key:rebase(item) for key,item in value.items()}
            if isinstance(value, list):return [rebase(item) for item in value]
            if isinstance(value, str):
                try:
                    path = Path(value)
                    if path.is_absolute():return str(destination/path.relative_to(source))
                except (ValueError, OSError):pass
            return value
        atomic(destination/'project.json', rebase(read(source/'project.json')))

def prepare(payload, settings, occupied=()):
    p=dict(payload)
    from .browser_accounts import browser_options
    browser_options(p)
    if p.get('account_fallback'):
        from ai_studio_account_rotation import account_order
        if not account_order(p):raise ValueError('Choose at least one saved fallback account in the account order.')
        if p.get('provider')!='flow' or not p.get('character_consistency'):
            raise ValueError('Account fallback supports Google Flow with Character & location consistency enabled.')
    current = Path(p['project']).expanduser().resolve() if p.get('project') else None
    saved = read(current/'project.json') if current else {}
    title = p.get('title') or saved.get('title') or 'Untitled project'
    name = project_name(title)
    migrate = bool(current and saved and (
        (p.get('title') and p['title'] != saved.get('title')) or
        (p.get('action') == 'save' and current.name != name and not re.fullmatch(re.escape(name)+r' \(\d+\)', current.name)) or
        current.name.startswith('zbot_')))
    if current is None or migrate:
        base = Path(p.get('output_dir') or (current.parent if current else None) or settings.get('output_dir') or settings.get('output_folder') or 'FinalVideos').expanduser().resolve()
        reserved = {Path(path).resolve() for path in occupied if path}
        destination = base/name
        suffix = 2
        while destination.exists() or destination in reserved:
            destination = base/f'{name} ({suffix})'
            suffix += 1
        if migrate:
            if current == destination or current in destination.parents or destination in current.parents:
                raise ValueError('Choose an output folder outside the existing project')
            p['source_project'] = str(current)
        p['project'] = str(destination)
    if 'show_browser' in p:p['headless']=not bool(p['show_browser'])
    if 'chrome_mode' in p:p['browser_mode']='cdp' if p['chrome_mode'] or (p.get('provider')=='flow' and p.get('share_google_profile')) else 'persistent'
    if 'bgm' in p:p['bgm_file']=settings.get('bgm_file') if p['bgm'] else None
    if p.get('action')=='export' and not p.get('output'):
        p['output']=str(Path(p.get('output_dir') or settings.get('output_dir') or 'FinalVideos').expanduser().resolve()/(name+'.mp4'))
    return p
