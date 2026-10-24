"""Desktop adapters for the original Animate controls; no Tk window needed."""
import copy
from pathlib import Path
from .storage import ROOT, read, atomic, public

PRESET_KEYS = ('audio_source','existing_audio_path','continuity_ledger_enabled','animate_narration_mode','narration_alignment_model','animation_mode','animate_count','partial_animation_unit','animate_seconds','animate_clip_seconds','animate_multishot','animate_model','animate_video_resolution','animate_video_aspect','animate_video_batch_size','auto_project','auto_reference','reference_mode',
               'character_consistency','auto_cast','main_character_references','dsp_malik_reference_path','character_names','place_name','reference_design','reference_files',
               'style_name','custom_style','continuity','resolution','narration_style','narration_direction')

def metadata(settings, root=ROOT):
    from .studio import metadata as studio_metadata
    inherited = studio_metadata(settings, root)
    folder = Path(settings.get('zb_draft_path') or root/'zbot_profiles/ai_studio_draft.json').parent
    draft = public(read(folder/'ai_studio_animate_draft.json'))
    defaults = dict(inherited['defaults'])
    defaults.update(title='Animate project', script='', project='', provider='flow', motion=False,
                    resolution='1920x1080', animation_mode='partial', animate_count=3,
                    animate_model='Omni 1.1 Flash', auto_project=True, auto_reference=True,reference_mode='auto',
                    character_names='CharacterA, CharacterB', place_name='StoryPlace',
                    reference_design='Colorful cartoon characters, simple grey backgrounds; consistent clothing and colors.',
                    reference_files='', agent_tool_dir=str(root/'animate_flow_backend'), browser_account='')
    mapping={'style':'style_name','captions':'use_captions_tab','transitions_tab':'use_transitions_tab','effects_tab':'use_effects_tab'}
    defaults.update({mapping.get(k,k):v for k,v in draft.get('controls',{}).items()})
    defaults.update(draft.get('animate',{}))
    private=settings.get('ai_studio_animate',{})
    for key in ('animate_count','animate_model','agent_tool_dir','auto_project','auto_reference','character_consistency','auto_cast','main_character_references','dsp_malik_reference_path','character_names','place_name','reference_design','reference_files','reference_mode'):
        if key not in draft.get('animate',{}) and key in private:defaults[key]=private[key]
    defaults.update(script=draft.get('script',''), project=draft.get('project') or '')
    presets = read(folder/'ai_studio_animate_presets.json')
    converted={}
    oldmap={'zb_style_var':'style_name','zb_custom_style_var':'custom_style','zb_continuity_var':'continuity','zb_res_var':'resolution'}
    for name, value in presets.items():
        converted[name]={**value.get('animate',{}), **{oldmap[k]:v for k,v in value.get('studio',{}).items() if k in oldmap}}
    converted.update(read(root/'.desktop/animate_presets.json'))
    from ai_studio_animate_prompts import master_prompt,split_master_prompt
    return {**inherited,'master_prompts':{**{mode:master_prompt(mode) for mode in ('partial','full')},'split':split_master_prompt()},'defaults':defaults,'presets':converted,'scenes':draft.get('scenes',[])}

def save_preset(name, options, root=ROOT):
    name=str(name).strip()
    if not name or len(name)>80:raise ValueError('Enter a preset name of 1–80 characters')
    from ai_studio_animate_options import animation_count
    animation_count(options,0)
    selected={k:options[k] for k in PRESET_KEYS if k in options}
    rows=read(root/'.desktop/animate_presets.json');rows[name]=selected
    atomic(root/'.desktop/animate_presets.json',rows)
    return selected

def references(config):
    from ai_studio_animate_options import reference_mode
    if reference_mode(config)=='none':return []
    from ai_studio_pipeline import valid_image
    paths=[p.strip() for p in str(config.get('reference_files','')).split('|') if p.strip()]
    if not paths:paths=config.get('references',[])
    if not isinstance(paths,list) or len(paths)>40 or any(not isinstance(p,str) or ',' in p or not valid_image(p) for p in paths):
        raise ValueError('Choose up to forty valid reference images with no commas in their paths')
    names=[Path(p).stem for p in paths]
    import re
    if len({n.casefold() for n in names})!=len(names) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',n) for n in names):
        raise ValueError('Reference filenames must have unique simple identifiers such as DSPMalik.png.')
    return paths

def new_project(payload, settings, cancel, emit):
    from .worker import studio
    from ai_studio_pipeline import check_cancel
    source=Path(payload['animate_source']).resolve() if payload.get('action')=='import' and payload.get('animate_source') else None
    saved=public(read(source/'project.json')) if source else {}
    if payload['action']=='import' and (not saved or saved.get('workflow')=='animate'):
        raise ValueError('Choose a saved AI Studio project to import')
    scenes=copy.deepcopy(saved.get('scenes',[]))
    target=Path(payload['project']);target.mkdir(parents=True,exist_ok=True)
    import shutil
    for i, scene in enumerate(scenes):
        check_cancel(cancel)
        for key in list(scene):
            if key.startswith('video_') or key=='manual_video':scene.pop(key,None)
        for key,folder in [('image_path','images'),('audio_path','voice')]:
            path=Path(scene.get(key) or '')
            if source and scene.get(key) and not path.is_absolute():path=source/path
            keep=folder=='voice' or payload['action']=='import'
            if keep and scene.get(key) and path.is_file():
                out=target/folder/f'scene_{i+1:04d}{path.suffix}';out.parent.mkdir(exist_ok=True)
                shutil.copy2(path,out);scene[key]=str(out)
            else:
                scene[key]=''
                if folder=='images':
                    scene.update(image_key='',image_status='missing',manual_image=False)
    config={**payload,'action':'save','scene_seed':scenes,'flow_url':'','auto_project':True,
            'package_seed':saved.get('package',{}),
            'script':payload.get('script') or saved.get('script','')}
    if payload['action']=='import':
        options=saved.get('options',{})
        config.update({k:options[k] for k in ('style_name','custom_style','continuity','resolution') if k in options})
        config['custom_style']=config.get('custom_style','')
    if payload['action']=='new':
        config.update(audio_source='tts',existing_audio_path='',scene_start=1,scene_end='',script='',scene_seed=[],package_seed={},references=[],reference_files='',scene_reference_map=None)
        for key in ('planning_source','cinematic_ready_prompts','ready_animation_script_key','cast_assets','reference_descriptions','thumbnail_paths','last_video','animation_ready','animation_video_ready','animation_image_ready'):
            config.pop(key,None)
    config.pop('animate_source',None)
    return studio(config,settings,cancel,animated=True,emit=emit)

def attach_clip(adapter, config, edit, cancel):
    from ai_studio_animate_options import animation_count
    from ai_studio_animate_media import valid_video
    from ai_studio_pipeline import run_ffmpeg
    index=edit.get('index');source=edit.get('video_path','')
    if type(index) is not int or not 0<=index<animation_count(config,len(adapter.zb_scenes),adapter.zb_scenes):
        raise ValueError('Select a scene animated by the current mode')
    if not valid_video(source):raise ValueError('Choose a playable video clip')
    target=Path(config['project'])/'videos'/f'scene_{index+1:04d}.mp4';target.parent.mkdir(exist_ok=True)
    temp=target.with_name(target.stem+'.attaching.mp4')
    image=Path(config['project'])/'images'/f'scene_{index+1:04d}.png';image.parent.mkdir(exist_ok=True)
    run_ffmpeg(['-i',source,'-an','-c:v','libx264','-preset','veryfast',temp],cancel)
    temp.replace(target)
    run_ffmpeg(['-i',target,'-frames:v','1',image],cancel)
    adapter.zb_scenes[index].update(video_path=str(target),manual_video=True,video_status='done',image_path=str(image))
    adapter.zb_last_video=None
