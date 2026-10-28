"""Process-isolated adapters to the existing engines. No Tk window is created."""
from __future__ import annotations
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from .storage import ROOT, read

def event(**values):
    print('@desktop:' + json.dumps(values, default=str), flush=True)

class Events:
    def __init__(self, emit=event):
        self.emit = emit
    def put(self, item):
        if item[0] == 'progress':
            self.emit(progress=item[1])
        elif item[0] == 'status':
            self.emit(message=item[1])
        elif item[0] == 'log':
            print(f'[{item[1].upper()}] {item[2]}', flush=True)
        # Tk callbacks and refresh events are unnecessary in the web adapter.

def studio(payload, settings, cancel, animated=False, emit=event):
    event = emit
    task_names={'approve-cast':'Review cast & locations','import-ready-animation':'Import ready animation story','cinematic-images':'Generate Remaining Images','cinematic-videos':'Generate Video Clips Only','references':'Create / reuse reference images','compile-part':'Compile Selected Part','render':'Render Video','build':'Build All'}
    print('Task: '+task_names.get(payload.get('action'),str(payload.get('action','build')).replace('-', ' ').replace('_',' ').title()),flush=True)
    from ai_studio_pipeline import STYLE_PRESETS, check_cancel, split_script
    from ai_studio_workflow import VOICE_KEYS
    from zbot_ai_tab import ZBotAITabMixin
    from ai_studio_animate import AnimateStudio

    if animated and payload.get('action') in ('new','import'):
        from .animate import new_project
        return new_project(payload,settings,cancel,emit)
    if payload.get('action') == 'login':
        from zbot_browser_images import ZBotImageGenerator
        from .browser_accounts import browser_options
        generator = ZBotImageGenerator('flow' if animated else payload.get('provider', 'gemini'),
            mode=payload.get('browser_mode', 'cdp'), cancel=cancel,
            share_google_profile=True if animated else payload.get('share_google_profile', False),
            log=lambda message, level='info': print(f'[{level.upper()}] {message}', flush=True),
            **browser_options(payload))
        try:
            if not generator.login():
                raise RuntimeError('Complete sign-in in the selected browser profile yourself, then retry.')
            result = {'browser_account': payload.get('browser_account', ''), 'login': True}
            event(result=result)
            return result
        finally:
            generator.close()
    base = AnimateStudio if animated else ZBotAITabMixin
    class Adapter(base):
        def __init__(self):
            self.settings = settings
            self._zb_cancel = cancel
            self.zb_last_video = None
            self.zb_package = {}
            self.zb_scenes = []
        def _zb_merged_settings(self):
            return dict(self.settings)
    adapter = Adapter()
    project = Path(payload['project']).expanduser().resolve()
    if payload.get('source_project'):
        from .studio import copy_project
        event(message='Saving project under its title; preserving existing assets')
        copy_project(payload['source_project'], project, cancel)
    for sub in ('', 'images', 'voice', 'clips'):
        (project / sub).mkdir(parents=True, exist_ok=True)
    saved = read(project / 'project.json')
    if animated and payload.get('action') == 'import-ready-animation':
        from ai_studio_animate_prompts import parse_ready
        from ai_studio_pipeline import fingerprint
        if any(s.get('image_path') or s.get('video_path') or s.get('audio_path') for s in saved.get('scenes',[])) or (project/'animate_media.json').exists():
            raise ValueError('Import a ready story into a new empty Animate project; existing generated assets are preserved.')
        if payload.get('animation_video_ready'):
            from ai_studio_animate_prompts import parse_split
            ready=parse_split(payload['animation_video_ready'],payload.get('animation_image_ready',''),payload.get('ready_original_script',''))
        else:
            ready=parse_ready(payload.get('animation_ready',''),payload.get('ready_original_script',''))
        payload.update(ready['options'],title=ready['title'] or payload.get('title','Animate story'),script=ready['script'],scene_seed=ready['scenes'],ready_animation_script_key=fingerprint(ready['script']))
        saved={}
    options = saved.get('options', {})
    if (saved and payload.get('action') in ('references','download-reference-images','images','build','cinematic-images','cinematic-videos','generate-missing','package','save','export-batches','download-batches','download-all-images')
            and options.get('character_consistency')
            and (payload.get('browser_account',options.get('browser_account','')) != options.get('browser_account','') or payload.get('flow_url_override') is True)):
        binding_state=read(project/('animate_media.json' if animated else 'studio_agent_images.json'))
        prior_accounts={row.get('account','') for row in binding_state.get('account_sessions',[])}
        selected_is_stale=(payload.get('browser_account','') in prior_accounts
                           and payload.get('account_selection_from') != options.get('browser_account',''))
        from ai_studio_account_rotation import select_account
        selected={**options,**payload,'project':str(project),**({'workflow':'animate','provider':'flow'} if animated else {})}
        if not selected_is_stale or payload.get('flow_url_override') is True:
            select_account(selected,options,cancel,lambda message:print('[INFO] '+message,flush=True))
            binding={key:selected[key] for key in ('browser_account','flow_url','_rotation_scope','_rotation_restored','_reference_flow_url')}
            payload.update(binding);options={**options,**binding}
    if saved and payload.get('action')!='login' and options.get('character_consistency'):
        from ai_studio_account_rotation import restore
        restored={**options,**payload,'project':str(project),**({'workflow':'animate'} if animated else {})}
        restore(restored)
        for key in ('browser_account','flow_url','_rotation_scope','_rotation_restored','_reference_flow_url'):
            if key in restored:payload[key]=restored[key]
        # The manifest is authoritative if the app closed during handover.
        if restored.get('_rotation_restored'):options={**options,**{key:restored[key] for key in ('browser_account','flow_url','_rotation_scope','_rotation_restored','_reference_flow_url')}}
    if saved and payload.get('action') != 'login' and payload.get('browser_account', options.get('browser_account', '')) != options.get('browser_account', ''):
        raise ValueError('This project belongs to another browser account. Select its original account to resume; use a new project for a different account.')
    engine = payload.get('voice_engine', options.get('voice_engine', 'cloud'))
    voice_key, default_voice = VOICE_KEYS[engine]
    settings[voice_key] = payload.get('voice') or options.get('voice') or settings.get(voice_key, default_voice)
    title = payload.get('title') or saved.get('title') or project.name
    script = payload.get('script') or saved.get('script', '')
    if not script.strip() and payload.get('action') not in ('package','save','login'):
        raise ValueError('Paste a script or open a saved project')
    style_name = payload.get('style_name', options.get('style_name', 'Cinematic realistic'))
    config = {'provider': 'gemini', 'llm': 'openai', 'style_name': style_name,
        'style': STYLE_PRESETS.get(style_name, STYLE_PRESETS['Cinematic realistic']),
        'continuity': '', 'resolution': '1920x1080', 'motion': True, 'captions': True,
        'use_captions_tab': True, 'use_transitions_tab': True, 'use_effects_tab': True,
        'transition': 'Cut', 'transition_seconds': .4, 'bgm_file': settings.get('bgm_file'),
        'bgm_volume': settings.get('bgm_volume', .12), 'fallback': False,
        'browser_mode': 'persistent', 'share_google_profile': False, 'headless': False,
        'flow_url': '', 'auto_project':True,'agent_tool_dir':str(ROOT/'animate_flow_backend'), 'image_batch_size': 6, 'shot_seconds': 7,
        **options, **payload, 'project': str(project), 'settings': settings,
        'title': title, 'script': script, 'voice_engine': engine, 'voice': settings[voice_key],
        'style': STYLE_PRESETS.get(style_name, STYLE_PRESETS['Cinematic realistic']) +
                 (', ' + str(payload.get('custom_style', options.get('custom_style', ''))) if payload.get('custom_style', options.get('custom_style')) else '')}
    if animated:
        from zbot_ai_tab import RES_ASPECT
        config = { 'animation_mode': 'partial', 'animate_count': 3, 'animate_model': 'Omni 1.1 Flash',
            'agent_tool_dir': str(ROOT / 'animate_flow_backend'), 'auto_project': True,
            'auto_reference': True, 'character_names': 'CharacterA, CharacterB',
            'place_name': 'StoryPlace', 'reference_design': '', 'references': [],
            **config, 'workflow': 'animate', 'provider': 'flow', 'browser_mode': 'cdp',
            'share_google_profile': True, 'motion': False,
            'aspect': RES_ASPECT.get(config['resolution'], '16:9')}
        from ai_studio_animate_options import animation_count
        animation_count(config, 0)
        if not config.get('agent_tool_dir'):config['agent_tool_dir']=str(ROOT/'animate_flow_backend')
    if animated and saved:
        from ai_studio_animate_cast import remember_existing
        remember_existing(config,options)
    from ai_studio_narration import validate as validate_narration
    validate_narration(config)
    if config.get("audio_source","tts") not in ("tts","existing"):raise ValueError("Choose existing TTS or imported audio workflow")
    if animated and config.get("audio_source")=="existing" and config.get("animate_narration_mode")!="cinematic":raise ValueError("Imported audio in Animate requires Narration-first cinematic mode")
    if not animated:
        from ai_studio_image_models import preferred
        preferred(config)
    if not animated and payload.get('action') == 'recover' and config['provider'] not in ('gemini', 'flow'):
        raise ValueError('Recover Images supports Gemini and Flow browsers. Use Generate Images or attach an image for other providers.')
    if animated:
        from .animate import references
        config['references']=references(config)
        from ai_studio_tab_render import captions_enabled
        config['captions']=bool(config.get('use_captions_tab',True)) and captions_enabled(settings)
    if 'bgm' in config:config['bgm_file']=settings.get('bgm_file') if config['bgm'] else None
    previous = saved.get('scenes', []) if saved else payload.get('scene_seed', [])
    for scene in previous:
        for key in ('image_path', 'audio_path', 'video_path'):
            if scene.get(key) and not Path(scene[key]).is_absolute():
                scene[key] = str(project / scene[key])
    if animated and payload.get('action')=='plan' and config.get('animate_multishot') and config.get('planning_source')!='chatgpt_ready' and not any(s.get('image_path') or s.get('video_path') or s.get('audio_path') for s in previous):previous=[]
    if script == (saved.get('script') if saved else script) and previous and (animated or payload.get('action') != 'plan'):
        adapter.zb_scenes = previous
    else:
        remaining = list(previous)
        for scene in split_script(script, max_words=max(8, int(float(config['shot_seconds']) * float(settings.get('tts_speed', 150)) / 60))):
            match = next((old for old in remaining if old['narration'] == scene['narration']), None)
            if match:
                remaining.remove(match)
                if not scene['visual_prompt']:
                    scene['visual_prompt'] = match.get('visual_prompt', '')
                for key, value in match.items():
                    if key not in ('id', 'raw', 'source_line', 'narration', 'visual_prompt', 'caption'):
                        if not key.startswith(('image_', 'video_')) or scene['visual_prompt'] == match.get('visual_prompt', ''):
                            scene[key] = value
            adapter.zb_scenes.append(scene)
    adapter.zb_package = saved.get('package', payload.get('package_seed', {}))
    adapter.zb_last_video = str(project / saved['last_video']) if saved.get('last_video') else None
    if animated and saved:
        from ai_studio_animate_options import animation_count
        if (script != saved.get('script') or
            animation_count(config, len(adapter.zb_scenes), adapter.zb_scenes) != animation_count(options, len(adapter.zb_scenes), adapter.zb_scenes) or
            any(config.get(k)!=options.get(k) for k in ('partial_animation_unit','animate_seconds')) or
            config['animate_model'] != options.get('animate_model', 'Omni 1.1 Flash')):
            adapter.zb_last_video = None
    if not animated and (script != saved.get('script') or payload.get('action') == 'plan'):
        adapter.zb_last_video = None
    if payload.get('action') == 'edit':
        edit = payload.get('scene_edit', {})
        index = edit.get('index')
        if not isinstance(index,int) or not 0 <= index < len(adapter.zb_scenes):
            raise ValueError('Choose an existing scene')
        scene=adapter.zb_scenes[index]
        for key in ('narration','visual_prompt','caption'):
            value=edit.get(key,scene.get(key,''))
            if not isinstance(value,str) or (key=='narration' and not value.strip()):
                raise ValueError('Scene narration cannot be empty')
            if value != scene.get(key,''):
                if key=='narration':scene.update(audio_path='',audio_key='',word_timings=[],audio_status='missing')
                if key in ('narration','visual_prompt'):
                    scene.update(image_path='',image_key='',manual_image=False,image_status='missing')
                    if animated:scene.update(video_path='',video_key='',manual_video=False,video_status='missing')
            scene[key]=value.strip()
        if edit.get('image_path'):
            from ai_studio_pipeline import valid_image
            from PIL import Image
            if not valid_image(edit['image_path']):raise ValueError('Choose a valid scene image')
            destination=project/'images'/f'scene_{index+1:04d}.png'
            with Image.open(edit['image_path']) as image:image.convert('RGB').save(destination,'PNG')
            scene.update(image_path=str(destination),manual_image=True,image_status='done')
        config['script']='\n\n'.join(s['narration'] for s in adapter.zb_scenes)
        adapter.zb_last_video=None
    config.pop('animation_video_ready', None)
    config.pop('animation_image_ready', None)
    config.pop('animation_ready', None)
    config.pop('ready_original_script', None)
    config.pop('account_selection_from', None)
    config.pop('flow_url_override', None)
    config.pop('scene_seed', None)
    config.pop('package_seed', None)
    config.pop('scene_edit', None)
    config.pop('source_project', None)
    config.pop('ledger_review',None)
    config.pop('cast_review',None)
    config.pop('ready_story',None)
    q = Events(emit)
    if animated and payload.get('action')=='import-ready-animation' and ready.get('assets') is not None:
        from ai_studio_animate_cast import import_cast
        import_cast(adapter,q,config,{'assets':ready['assets'],'scenes':[{'scene':i+1,'narration':s['narration'],'references':s.get('reference_names',[]),'visual_prompt':s['visual_prompt']} for i,s in enumerate(adapter.zb_scenes)]})
    action = payload.get('action', 'build')
    if not animated and action=='build':
        from ai_studio_parts import scene_range
        if scene_range(config,len(adapter.zb_scenes))!=(0,len(adapter.zb_scenes)):
            raise ValueError('A scene range is selected. Use Generate Images, then Compile Selected Part. Reset Start to 1 and clear End for Build All.')
    review_required=False
    if animated and action=='attach':
        from .animate import attach_clip
        attach_clip(adapter,config,payload.get('scene_edit',{}),cancel)
        adapter._zb_save_project(config)
        result={'project':str(project/'project.json'),'video':None,'scenes':len(adapter.zb_scenes)}
        event(result=result)
        return result
    adapter._zb_save_project(config)
    phases = {'plan': [], 'prompts': [adapter._zb_fill_prompts],
        'images': [adapter._zb_fill_prompts, adapter._zb_images_pass],
        'voice': [adapter._zb_voice_pass], 'render': [adapter._zb_render_pass],
        'build': [adapter._zb_fill_prompts, adapter._zb_images_pass, adapter._zb_voice_pass, adapter._zb_render_pass],
        'recover': [lambda q, c: adapter._zb_images_pass(q, c, recover_only=True)], 'export': []}
    def package(q,c):
        class Value:
            def get(self):return c['title']
        adapter.zb_title_var=Value()
        adapter._zb_job_config=c
        adapter._zb_start_worker=lambda work:work(q)
        adapter._zb_generate_package()
    phases.update(package=[package],save=[],edit=[])
    if not animated:
        def studio_generate_missing(q,c):
            if c.get('provider')!='flow' or not c.get('character_consistency'):
                raise ValueError('Generate Missing recovery requires Flow with reviewed character/location consistency.')
            adapter._zb_fill_prompts(q,c)
            if c.get('audio_source')=='existing':adapter._zb_voice_pass(q,c)
            adapter._zb_images_pass(q,{**c,'_generate_missing':True})
        phases['generate-missing']=[studio_generate_missing]

    if not animated and (config.get('narration_mode') == 'continuous' or config.get('audio_source')=='existing'):
        phases['build']=[adapter._zb_fill_prompts,adapter._zb_voice_pass,adapter._zb_images_pass,adapter._zb_render_pass]
    if not animated and config.get('audio_source')=='existing':
        phases['images']=[adapter._zb_fill_prompts,adapter._zb_voice_pass,adapter._zb_images_pass]
    if animated:
        phases['import-ready-animation'] = []
        from ai_studio_continuity_ledger import build as build_ledger,save_review as save_ledger
        phases['continuity-ledger']=[lambda q,c:build_ledger(adapter,q,c)]
        phases['save-continuity-ledger']=[lambda q,c:save_ledger(adapter,q,c,payload.get('ledger_review',{}))]
        from ai_studio_cast import analyze as analyze_cast,approve as approve_cast,current as current_cast
        from ai_studio_animate_cast import references as full_references,import_cast,analyze as animate_analyze,approve as animate_approve
        phases['analyze-cast']=[lambda q,c:animate_analyze(adapter,q,c)]
        phases['approve-cast']=[lambda q,c:animate_approve(adapter,q,c,payload.get('cast_review',{}))]
        phases['import-ready']=[lambda q,c:import_cast(adapter,q,c,payload.get('ready_story',''))]
        phases['references']=[lambda q,c:full_references(adapter,q,c)]
        phases['export-reference-prompts']=[lambda q,c:full_references(adapter,q,c,'export')]
        phases['download-reference-images']=[lambda q,c:full_references(adapter,q,c,'download')]
        phases['write-story']=[adapter._zb_write_story]
        def cinematic_media(q,c):
            if c.get('animate_narration_mode')!='cinematic':raise ValueError('Choose Narration-first cinematic mode for separate video/image generation.')
            adapter._zb_images_pass(q,{**c,'cinematic_media_kind':'video' if action=='cinematic-videos' else 'image'})
        from ai_studio_parts import compile_part
        phases['compile-part']=[lambda q,c:compile_part(adapter,q,c,animated=True)]
        phases['cinematic-videos']=[cinematic_media]
        phases['cinematic-images']=[cinematic_media]
        phases['build']=[adapter._zb_fill_prompts,adapter._zb_voice_pass,adapter._zb_images_pass,adapter._zb_render_pass]
        def generate_missing(q,c):
            adapter._zb_images_pass(q,{**c,'_generate_missing':True})
        phases['generate-missing']=[generate_missing]
        if config.get('character_consistency') and action in ('write-story','images','build','references','cinematic-videos','cinematic-images','generate-missing'):
            from ai_studio_animate_cast import reviewed
            try:review=reviewed(config,adapter.zb_scenes,approved=False)
            except ValueError:
                if (project/'cast_analysis.json').exists():raise
                review=None
            if not review or not review.get('approved'):
                phases[action]=phases['analyze-cast'] if not review else []
                review_required=True
    else:
        from ai_studio_thumbnails import generate as generate_thumbnails
        from ai_studio_cast import analyze as analyze_cast, approve as approve_cast, import_ready, current as current_cast
        config.setdefault('auto_cast',True)
        if ('auto_cast' not in options and not (project/'cast_analysis.json').exists()
            and any((project/p).exists() for p in ('studio_agent_images.json','references/reference_plan.json'))):
            # Older reference jobs already have immutable identities. Preserve
            # their original resume path; automatic discovery starts in new videos.
            config['auto_cast']=False
        phases['analyze-cast']=[lambda q,c:analyze_cast(adapter,q,c)]
        phases['approve-cast']=[lambda q,c:approve_cast(adapter,q,c,payload.get('cast_review',{}))]
        phases['import-ready']=[lambda q,c:import_ready(adapter,q,c,payload.get('ready_story',''))]
        def references(q,c):
            if not c.get('character_consistency'):raise ValueError('Enable character consistency first.')
            from ai_studio_consistency import generate
            generate(adapter,q,c,references_only=True)
        phases['references']=[references]
        phases['export-reference-prompts']=[lambda q,c:references(q,{**c,'_manual_reference_action':'export'})]
        phases['download-reference-images']=[lambda q,c:references(q,{**c,'_manual_reference_action':'download'})]
        from ai_studio_manual_batches import run as manual_batches, download_all
        phases['export-batches']=[lambda q,c:manual_batches(adapter,q,c)]
        phases['download-batches']=[lambda q,c:manual_batches(adapter,q,c,download=True)]
        def download_scenes(q,c):c['_download_summary']=download_all(adapter,q,c)
        phases['download-all-images']=[download_scenes]
        from ai_studio_parts import compile_part
        phases['compile-part']=[lambda q,c:compile_part(adapter,q,c)]
        def thumbnails(q,c):
            from ai_studio_parts import scene_range
            if scene_range(c,len(adapter.zb_scenes))!=(0,len(adapter.zb_scenes)):
                q.put(('log','info','Scene range selected. End thumbnails are deferred until the full video is ready.'))
                return
            generate_thumbnails(adapter,q,c)
        phases['images'].append(thumbnails)
        phases['build'].insert(phases['build'].index(adapter._zb_images_pass)+1,thumbnails)
        phases['thumbnails']=[thumbnails]
        def retry_thumbnails(q,c):generate_thumbnails(adapter,q,{**c,'_retry_missing_thumbnails':True})
        phases['retry-thumbnails']=[retry_thumbnails]
        if action in ('images','build','references') and config.get('character_consistency') and config.get('auto_cast',True):
            review=current_cast(config,adapter.zb_scenes)
            if not review or not review.get('approved'):
                phases[action]=phases['analyze-cast']
                review_required=True
    if action not in phases:
        raise ValueError('Unknown Studio stage')
    try:
        def prepare_flow():
            from ai_studio_animate_setup import ensure_project
            from .studio import adopt_existing_flow
            adopt_existing_flow(config,recover_only=action=='recover')
            if not config.get('agent_tool_dir'):config['agent_tool_dir']=str(ROOT/'animate_flow_backend')
            if config.get('auto_project'):config['browser_mode']='cdp'
            event(message='Opening saved Flow project or creating this video’s Flow project')
            config['flow_url'] = ensure_project(config, cancel, lambda message: print(message, flush=True))
            adapter._zb_save_project(config)
        flow_ready=False
        for phase in phases[action]:
            check_cancel(cancel)
            if animated and phase==adapter._zb_images_pass:
                print('[INFO] Veo generates visual clips. Local voice-over is mixed into final.mp4; raw downloaded clip audio is discarded.',flush=True)
            # Open Flow only when the first image requests are ready.
            if (not flow_ready and not animated and config['provider']=='flow'
                and action in ('images','build','recover','thumbnails','retry-thumbnails','references') and phase!=adapter._zb_fill_prompts
                and phase not in phases.get('analyze-cast',[])):
                prepare_flow();flow_ready=True
            event(message=phase.__name__.replace('_zb_', '').replace('_', ' '))
            started=time.monotonic()
            while True:
                try:
                    phase(q, config)
                    break
                except RuntimeError as error:
                    from ai_studio_stall_recovery import recover
                    if not recover(adapter,q,config,error,animated=animated):raise
                    event(message='Account switched; references ready. Resuming missing scenes')
            if animated and phase == adapter._zb_voice_pass:adapter._opening_voice_ready=True
            print(f'[INFO] {phase.__name__.replace("_zb_", "").replace("_", " ")} finished in {time.monotonic()-started:.1f}s.',flush=True)
        from .job_automation import should_compile,verify_part_media
        if should_compile(config,review_required):
            first,last=verify_part_media(adapter.zb_scenes,config,animated)
            check_cancel(cancel)
            print(f'[INFO] Auto compile: all selected media files {first}–{last} verified. Starting Compile Selected Part.',flush=True)
            event(message='Auto compile selected part')
            from ai_studio_parts import compile_part
            compile_part(adapter,q,config,animated=animated)
        if action == 'export':
            if not adapter.zb_last_video or not Path(adapter.zb_last_video).is_file():
                raise ValueError('Render this project before exporting')
            destination = Path(payload['output']).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination != Path(adapter.zb_last_video).resolve():
                shutil.copy2(adapter.zb_last_video, destination)
            if (project / 'captions.srt').is_file():
                if (project/'captions.srt').resolve() != destination.with_suffix('.srt'):
                    shutil.copy2(project / 'captions.srt', destination.with_suffix('.srt'))
        check_cancel(cancel)
        if action == 'plan':
            print(f'[SUCCESS] Parsed {len(adapter.zb_scenes)} scenes. Parsing is complete. Next: Generate Images / Generate Voice, or Build All.', flush=True)
        result = {'project': str(project / 'project.json'), 'video': adapter.zb_last_video, 'scenes': len(adapter.zb_scenes)}
        if config.get('_part_result'):
            result['part']=config['_part_result'];result['video']=result['part']['video']
        if config.get('_download_summary') is not None:result['download']=config['_download_summary']
        if review_required:result['review_required']=True
        event(result=result)
        return result
    finally:
        adapter._zb_save_project(config)

def quick(payload, settings, cancel):
    from youtube_video_automation_enhanced import VideoQuoteAutomation, remove_silence_from_video
    from ai_studio_pipeline import check_cancel
    # Override load_settings before construction so all engine initialization uses the frozen snapshot.
    class Processor(VideoQuoteAutomation):
        def load_settings(self):
            return dict(settings)
    processor = Processor(payload['video_folder'], payload.get('quotes_file', ''), payload['output_folder'])
    videos = processor.get_video_files()
    if not videos:
        raise ValueError('No supported videos in the source folder')
    checkpoint = Path(payload['output_folder']) / 'desktop_quick_checkpoint.json'
    from .storage import atomic
    from ai_studio_pipeline import fingerprint
    signature = fingerprint(settings, str(processor.video_folder), payload.get('quotes_file', ''))
    saved = read(checkpoint)
    done = saved.get('done', {}) if saved.get('signature') == signature else {}
    failures = []
    for index, video in enumerate(videos):
        check_cancel(cancel)
        key = fingerprint(str(video), video.stat().st_size, video.stat().st_mtime_ns)
        if key in done and Path(done[key]).is_file():
            print(f'[REUSED] {video.name}', flush=True)
            event(progress=(index + 1) / len(videos) * 100)
            continue
        event(progress=index / len(videos) * 100, range_start=index / len(videos) * 100,
              range_size=100 / len(videos), message=f'Video {index + 1}/{len(videos)} · {video.name}')
        source = video
        if settings.get('silence_removal_enabled'):
            cleaned = Path(payload['output_folder']) / (video.stem + '_nosilence.mp4')
            ok = remove_silence_from_video(video, cleaned, settings, ffmpeg_path='ffmpeg',
                transition_duration=settings.get('silence_transition_duration', .3) if settings.get('silence_transition_enabled') else 0,
                use_tab_transitions=bool(settings.get('silence_transition_enabled')))
            if ok and cleaned.is_file():
                source = cleaned
        try:
            result = processor.process_single_video(source, video_index=index)
        except Exception as error:
            result = {'status': 'failed', 'error': str(error)}
        if result.get('status') != 'success':
            failures.append(video.name)
            print(f'[ERROR] {video.name}: {result.get("error", "processing failed")}', flush=True)
        else:
            output = Path(result.get('output_file', result.get('output_path', '')))
            done[key] = str(output if output.is_absolute() else processor.output_folder / output)
            atomic(checkpoint, {'signature': signature, 'done': done})
        event(progress=(index + 1) / len(videos) * 100)
    if failures:
        raise RuntimeError(f'{len(failures)} videos failed: ' + ', '.join(failures))
    event(result={'output': payload['output_folder'], 'count': len(done)})

def main():
    # The parent sends UTF-8 and expects UTF-8 logs. Windows pipe defaults can
    # otherwise drop browser messages containing emoji or non-English text.
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    request = json.loads(sys.stdin.readline())
    cancel = threading.Event()
    def watch():
        while not cancel.is_set():
            if Path(request['cancel']).exists():
                cancel.set()
            time.sleep(.1)
    threading.Thread(target=watch, daemon=True).start()
    kind, p, settings = request['kind'], request['payload'], request['settings']
    os.chdir(ROOT)
    if kind == 'ourscript':
        from .ourscript import run
        run(p, settings, cancel)
    elif kind == 'quick':
        quick(p, settings, cancel)
    elif kind in ('studio-batch','animate-batch'):
        from .studio_batch import run
        run(p, settings, cancel, event, lambda p,s,c,e: studio(p,s,c,animated=kind=='animate-batch',emit=e))
    elif kind in ('studio', 'animate'):
        studio(p, settings, cancel, kind == 'animate')
    elif kind == 'dub-tools':
        from .dubbing_actions import run
        run(p, settings, event)
    elif kind == 'dubbing':
        if p.get('items'):
            from .dubbing import run
            run(p, settings, cancel, event)
            return
        from dubbing_engine import dub_video
        out = dub_video(Path(p['input']), Path(p['output']), p['language'], settings,
            log=lambda level, text: print(f'[{level.upper()}] {text}', flush=True),
            progress=lambda done,total,note: event(progress=100*done/max(1,total),message=str(note)), source_language=p.get('source_language') or None,
            keep_audio_file=bool(settings.get('dub_keep_audio_file')))
        if not out:
            raise RuntimeError('Dubbing failed; see the engine log')
        event(result={'output': str(out)})
    elif kind == 'thumbnail':
        from thumbnail_designer import generate_thumbnail
        out = generate_thumbnail(p['prompt'], p['output'], frame_path=p.get('reference') or None,
            aspect=p.get('aspect', '16:9'), settings=settings,
            log=lambda level, text: print(f'[{level.upper()}] {text}', flush=True))
        if not out:
            raise RuntimeError('Thumbnail generation failed; check credentials and quota')
        event(result={'output': str(out)})
    elif kind == 'voice':
        from youtube_video_automation_enhanced import TTSGenerator
        settings.update(tts_engine=p['engine'], use_tts_voiceover=True)
        from ai_studio_workflow import VOICE_KEYS
        if p.get('voice'):
            settings[VOICE_KEYS[p['engine']][0]] = p['voice']
        Path(p['output']).parent.mkdir(parents=True, exist_ok=True)
        ok, words = TTSGenerator.generate_voiceover(p['text'], Path(p['output']), settings)
        if not ok:
            raise RuntimeError('Voice generation failed')
        event(result={'output': p['output']})
    elif kind == 'cleanup':
        from youtube_video_automation_enhanced import remove_silence_from_video
        Path(p['output']).parent.mkdir(parents=True, exist_ok=True)
        if not remove_silence_from_video(Path(p['input']), Path(p['output']), settings, ffmpeg_path='ffmpeg'):
            raise RuntimeError('Silence cleanup failed')
        event(result={'output': p['output']})

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'[ERROR] {type(error).__name__}: {error}', flush=True)
        sys.exit(1)
