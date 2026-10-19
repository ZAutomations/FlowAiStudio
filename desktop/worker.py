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

def studio(payload, settings, cancel, animated=False, emit=event):
    event = emit
    from ai_studio_pipeline import STYLE_PRESETS, check_cancel, split_script
    from ai_studio_workflow import VOICE_KEYS
    from zbot_ai_tab import ZBotAITabMixin
    from ai_studio_animate import AnimateStudio
    if animated and payload.get('action') in ('new', 'import'):
        from .animate import new_project
        return new_project(payload, settings, cancel, emit)
    if payload.get('action') == 'login':
        from zbot_browser_images import ZBotImageGenerator
        from .browser_accounts import browser_options
        generator = ZBotImageGenerator('flow' if animated else payload.get('provider', 'gemini'), mode=payload.get('browser_mode', 'cdp'), cancel=cancel, share_google_profile=True if animated else payload.get('share_google_profile', False), log=lambda message, level='info': print(f'[{level.upper()}] {message}', flush=True), **browser_options(payload))
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
        ready=parse_ready(payload.get('animation_ready',''),payload.get('ready_original_script',''))
        payload.update(ready['options'],title=ready['title'] or payload.get('title','Animate story'),script=ready['script'],scene_seed=ready['scenes'],ready_animation_script_key=fingerprint(ready['script']))
        saved={}
    options = saved.get('options', {})
    if (saved and not animated and payload.get('action') in ('references','images','build')
            and options.get('character_consistency')
            and payload.get('browser_account',options.get('browser_account','')) != options.get('browser_account','')):
        binding_state=read(project/'studio_agent_images.json')
        prior_accounts={row.get('account','') for row in binding_state.get('account_sessions',[])}
        selected_is_stale=(payload.get('browser_account','') in prior_accounts
                           and payload.get('_account_selection_from') != options.get('browser_account',''))
        from ai_studio_account_rotation import select_account
        selected={**options,**payload,'project':str(project)}
        if not selected_is_stale:
            select_account(selected,options,cancel,lambda message:print('[INFO] '+message,flush=True))
            binding={key:selected[key] for key in ('browser_account','flow_url','_rotation_scope','_rotation_restored','_reference_flow_url')}
            payload.update(binding);options={**options,**binding}
    if saved and payload.get('action') != 'login' and options.get('character_consistency'):
        from ai_studio_account_rotation import restore
        restored = {**options, **payload, 'project': str(project)}
        restore(restored)
        for key in ('browser_account', 'flow_url', '_rotation_scope', '_rotation_restored', '_reference_flow_url'):
            if key in restored:
                payload[key] = restored[key]
        if restored.get('_rotation_restored'):
            options = {**options, **{key: restored[key] for key in ('browser_account', 'flow_url', '_rotation_scope', '_rotation_restored', '_reference_flow_url')}}
    if saved and payload.get('action') != 'login' and (payload.get('browser_account', options.get('browser_account', '')) != options.get('browser_account', '')):
        raise ValueError('This project belongs to another browser account. Select its original account to resume; use a new project for a different account.')
    engine = payload.get('voice_engine', options.get('voice_engine', 'cloud'))
    if engine not in VOICE_KEYS:
        engine='google_cloud';payload['voice']='';options={**options,'voice':''}
    voice_key, default_voice = VOICE_KEYS[engine]
    settings[voice_key] = payload.get('voice') or options.get('voice') or settings.get(voice_key, default_voice)
    title = payload.get('title') or saved.get('title') or project.name
    script = payload.get('script') or saved.get('script', '')
    if not script.strip() and payload.get('action') not in ('package', 'save', 'login'):
        raise ValueError('Paste a script or open a saved project')
    style_name = payload.get('style_name', options.get('style_name', 'Cinematic realistic'))
    config = {'provider': 'gemini', 'llm': 'openai', 'style_name': style_name, 'style': STYLE_PRESETS.get(style_name, STYLE_PRESETS['Cinematic realistic']), 'continuity': '', 'resolution': '1920x1080', 'motion': True, 'captions': True, 'use_captions_tab': True, 'use_transitions_tab': False, 'use_effects_tab': False, 'transition': 'Cut', 'transition_seconds': 0.4, 'bgm_file': settings.get('bgm_file'), 'bgm_volume': settings.get('bgm_volume', 0.12), 'fallback': False, 'browser_mode': 'persistent', 'share_google_profile': False, 'headless': False, 'flow_url': '', 'auto_project': True, 'agent_tool_dir': str(ROOT / 'animate_flow_backend'), 'image_batch_size': 6, 'shot_seconds': 7, **options, **payload, 'project': str(project), 'settings': settings, 'title': title, 'script': script, 'voice_engine': engine, 'voice': settings[voice_key], 'style': STYLE_PRESETS.get(style_name, STYLE_PRESETS['Cinematic realistic']) + (', ' + str(payload.get('custom_style', options.get('custom_style', ''))) if payload.get('custom_style', options.get('custom_style')) else '')}
    from standalone_config import normalize
    config=normalize(config)
    if animated:
        from zbot_ai_tab import RES_ASPECT
        config = {'animation_mode': 'partial', 'animate_count': 3, 'animate_model': 'Omni 1.1 Flash', 'agent_tool_dir': str(ROOT / 'animate_flow_backend'), 'auto_project': True, 'auto_reference': True, 'character_names': 'CharacterA, CharacterB', 'place_name': 'StoryPlace', 'reference_design': '', 'references': [], **config, 'workflow': 'animate', 'provider': 'flow', 'browser_mode': 'cdp', 'share_google_profile': True, 'motion': False, 'aspect': RES_ASPECT.get(config['resolution'], '16:9')}
        from ai_studio_animate_options import animation_count
        animation_count(config, 0)
        if not config.get('agent_tool_dir'):
            config['agent_tool_dir'] = str(ROOT / 'animate_flow_backend')
    from ai_studio_narration import validate as validate_narration
    validate_narration(config)
    if not animated:
        from ai_studio_image_models import preferred
        preferred(config)
    if not animated and payload.get('action') == 'recover' and (config['provider'] not in ('gemini', 'flow')):
        raise ValueError('Recover Images supports Gemini and Flow browsers. Use Generate Images or attach an image for other providers.')
    if animated:
        from .animate import references
        config['references'] = references(config)
        from ai_studio_tab_render import captions_enabled
        config['captions'] = bool(config.get('use_captions_tab', True)) and captions_enabled(settings)
    if 'bgm' in config:
        config['bgm_file'] = settings.get('bgm_file') if config['bgm'] else None
    previous = saved.get('scenes', []) if saved else payload.get('scene_seed', [])
    for scene in previous:
        for key in ('image_path', 'audio_path', 'video_path'):
            if scene.get(key) and (not Path(scene[key]).is_absolute()):
                scene[key] = str(project / scene[key])
    if animated and payload.get('action')=='plan' and config.get('animate_multishot') and not any(s.get('image_path') or s.get('video_path') or s.get('audio_path') for s in previous):previous=[]
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
        if (script != saved.get('script') or animation_count(config, len(adapter.zb_scenes), adapter.zb_scenes) != animation_count(options, len(adapter.zb_scenes), adapter.zb_scenes) or
            any(config.get(k)!=options.get(k) for k in ('partial_animation_unit','animate_seconds')) or config['animate_model'] != options.get('animate_model', 'Omni 1.1 Flash')):
            adapter.zb_last_video = None
    if not animated and (script != saved.get('script') or payload.get('action') == 'plan'):
        adapter.zb_last_video = None
    if payload.get('action') == 'edit':
        edit = payload.get('scene_edit', {})
        index = edit.get('index')
        if not isinstance(index, int) or not 0 <= index < len(adapter.zb_scenes):
            raise ValueError('Choose an existing scene')
        scene = adapter.zb_scenes[index]
        for key in ('narration', 'visual_prompt', 'caption'):
            value = edit.get(key, scene.get(key, ''))
            if not isinstance(value, str) or (key == 'narration' and (not value.strip())):
                raise ValueError('Scene narration cannot be empty')
            if value != scene.get(key, ''):
                if key == 'narration':
                    scene.update(audio_path='', audio_key='', word_timings=[], audio_status='missing')
                if key in ('narration', 'visual_prompt'):
                    scene.update(image_path='', image_key='', manual_image=False, image_status='missing')
                    if animated:
                        scene.update(video_path='', video_key='', manual_video=False, video_status='missing')
            scene[key] = value.strip()
        if edit.get('image_path'):
            from ai_studio_pipeline import valid_image
            from PIL import Image
            if not valid_image(edit['image_path']):
                raise ValueError('Choose a valid scene image')
            destination = project / 'images' / f'scene_{index + 1:04d}.png'
            with Image.open(edit['image_path']) as image:
                image.convert('RGB').save(destination, 'PNG')
            scene.update(image_path=str(destination), manual_image=True, image_status='done')
        config['script'] = '\n\n'.join((s['narration'] for s in adapter.zb_scenes))
        adapter.zb_last_video = None
    config.pop('animation_ready', None)
    config.pop('ready_original_script', None)
    config.pop('_account_selection_from', None)
    config.pop('scene_seed', None)
    config.pop('package_seed', None)
    config.pop('scene_edit', None)
    config.pop('source_project', None)
    config.pop('cast_review', None)
    config.pop('ready_story', None)
    q = Events(emit)
    action = payload.get('action', 'build')
    if not animated and action == 'build':
        from ai_studio_parts import scene_range
        if scene_range(config, len(adapter.zb_scenes)) != (0, len(adapter.zb_scenes)):
            raise ValueError('A scene range is selected. Use Generate Images, then Compile Selected Part. Reset Start to 1 and clear End for Build All.')
    review_required = False
    if animated and action == 'attach':
        from .animate import attach_clip
        attach_clip(adapter, config, payload.get('scene_edit', {}), cancel)
        adapter._zb_save_project(config)
        result = {'project': str(project / 'project.json'), 'video': None, 'scenes': len(adapter.zb_scenes)}
        event(result=result)
        return result
    adapter._zb_save_project(config)
    phases = {'plan': [], 'prompts': [adapter._zb_fill_prompts], 'images': [adapter._zb_fill_prompts, adapter._zb_images_pass], 'voice': [adapter._zb_voice_pass], 'render': [adapter._zb_render_pass], 'build': [adapter._zb_fill_prompts, adapter._zb_images_pass, adapter._zb_voice_pass, adapter._zb_render_pass], 'recover': [lambda q, c: adapter._zb_images_pass(q, c, recover_only=True)], 'export': []}

    def package(q, c):

        class Value:

            def get(self):
                return c['title']
        adapter.zb_title_var = Value()
        adapter._zb_job_config = c
        adapter._zb_start_worker = lambda work: work(q)
        adapter._zb_generate_package()
    phases.update(package=[package], save=[], edit=[])
    if not animated and config.get('narration_mode') == 'continuous':
        phases['build']=[adapter._zb_fill_prompts,adapter._zb_voice_pass,adapter._zb_images_pass,adapter._zb_render_pass]
    if animated:
        phases['import-ready-animation'] = []
        phases['write-story'] = [adapter._zb_write_story]
        phases['build'] = [adapter._zb_fill_prompts, adapter._zb_voice_pass, adapter._zb_images_pass, adapter._zb_render_pass]

        def generate_missing(q, c):
            adapter._zb_images_pass(q, {**c, '_generate_missing': True})
        phases['generate-missing'] = [generate_missing]
    else:
        from ai_studio_thumbnails import generate as generate_thumbnails
        from ai_studio_cast import analyze as analyze_cast, approve as approve_cast, import_ready, current as current_cast
        config.setdefault('auto_cast', True)
        if 'auto_cast' not in options and (not (project / 'cast_analysis.json').exists()) and any(((project / p).exists() for p in ('studio_agent_images.json', 'references/reference_plan.json'))):
            config['auto_cast'] = False
        phases['analyze-cast'] = [lambda q, c: analyze_cast(adapter, q, c)]
        phases['approve-cast'] = [lambda q, c: approve_cast(adapter, q, c, payload.get('cast_review', {}))]
        phases['import-ready'] = [lambda q, c: import_ready(adapter, q, c, payload.get('ready_story', ''))]

        def references(q, c):
            if not c.get('character_consistency'):
                raise ValueError('Enable character consistency first.')
            from ai_studio_consistency import generate
            generate(adapter, q, c, references_only=True)
        phases['references'] = [references]
        phases['export-reference-prompts'] = [lambda q, c: references(q, {**c, '_manual_reference_action': 'export'})]
        phases['download-reference-images'] = [lambda q, c: references(q, {**c, '_manual_reference_action': 'download'})]
        from ai_studio_manual_batches import run as manual_batches, download_all
        phases['export-batches'] = [lambda q, c: manual_batches(adapter, q, c)]
        phases['download-batches'] = [lambda q, c: manual_batches(adapter, q, c, download=True)]

        def download_scenes(q, c):
            c['_download_summary'] = download_all(adapter, q, c)
        phases['download-all-images'] = [download_scenes]
        from ai_studio_parts import compile_part
        phases['compile-part'] = [lambda q, c: compile_part(adapter, q, c)]

        def thumbnails(q, c):
            from ai_studio_parts import scene_range
            if scene_range(c, len(adapter.zb_scenes)) != (0, len(adapter.zb_scenes)):
                q.put(('log', 'info', 'Scene range selected. End thumbnails are deferred until the full video is ready.'))
                return
            generate_thumbnails(adapter, q, c)
        phases['images'].append(thumbnails)
        phases['build'].insert(2, thumbnails)
        phases['thumbnails'] = [thumbnails]

        def retry_thumbnails(q, c):
            generate_thumbnails(adapter, q, {**c, '_retry_missing_thumbnails': True})
        phases['retry-thumbnails'] = [retry_thumbnails]
        if action in ('images', 'build', 'references') and config.get('character_consistency') and config.get('auto_cast', True):
            review = current_cast(config, adapter.zb_scenes)
            if not review or not review.get('approved'):
                phases[action] = phases['analyze-cast']
                review_required = True
    if action not in phases:
        raise ValueError('Unknown Studio stage')
    try:

        def prepare_flow():
            from ai_studio_animate_setup import ensure_project
            from .studio import adopt_existing_flow
            adopt_existing_flow(config, recover_only=action == 'recover')
            if not config.get('agent_tool_dir'):
                config['agent_tool_dir'] = str(ROOT / 'animate_flow_backend')
            if config.get('auto_project'):
                config['browser_mode'] = 'cdp'
            event(message='Opening saved Flow project or creating this video’s Flow project')
            config['flow_url'] = ensure_project(config, cancel, lambda message: print(message, flush=True))
            adapter._zb_save_project(config)
        flow_ready = False
        for phase in phases[action]:
            check_cancel(cancel)
            if animated and phase == adapter._zb_images_pass:
                print('[INFO] Veo generates visual clips. Local voice-over is mixed into final.mp4; raw downloaded clip audio is discarded.', flush=True)
            if not flow_ready and (not animated) and (config['provider'] == 'flow') and (action in ('images', 'build', 'recover', 'thumbnails', 'retry-thumbnails', 'references')) and (phase != adapter._zb_fill_prompts) and (phase not in phases.get('analyze-cast', [])):
                prepare_flow()
                flow_ready = True
            event(message=phase.__name__.replace('_zb_', '').replace('_', ' '))
            started = time.monotonic()
            phase(q, config)
            if animated and phase == adapter._zb_voice_pass:adapter._opening_voice_ready=True
            print(f"[INFO] {phase.__name__.replace('_zb_', '').replace('_', ' ')} finished in {time.monotonic() - started:.1f}s.", flush=True)
        if action == 'export':
            if not adapter.zb_last_video or not Path(adapter.zb_last_video).is_file():
                raise ValueError('Render this project before exporting')
            destination = Path(payload['output']).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination != Path(adapter.zb_last_video).resolve():
                shutil.copy2(adapter.zb_last_video, destination)
            if (project / 'captions.srt').is_file():
                if (project / 'captions.srt').resolve() != destination.with_suffix('.srt'):
                    shutil.copy2(project / 'captions.srt', destination.with_suffix('.srt'))
        check_cancel(cancel)
        if action == 'plan':
            print(f'[SUCCESS] Parsed {len(adapter.zb_scenes)} scenes. Parsing is complete. Next: Generate Images / Generate Voice, or Build All.', flush=True)
        result = {'project': str(project / 'project.json'), 'video': adapter.zb_last_video, 'scenes': len(adapter.zb_scenes)}
        if config.get('_part_result'):
            result['part'] = config['_part_result']
            result['video'] = result['part']['video']
        if config.get('_download_summary') is not None:
            result['download'] = config['_download_summary']
        if review_required:
            result['review_required'] = True
        event(result=result)
        return result
    finally:
        adapter._zb_save_project(config)
def main():
    from runtime_paths import configure
    configure()
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    request=json.loads(sys.stdin.readline());cancel=threading.Event()
    def watch():
        while not cancel.is_set():
            if Path(request['cancel']).exists():cancel.set()
            time.sleep(.1)
    threading.Thread(target=watch,daemon=True).start()
    kind=request['kind'];payload=request['payload'];settings=request['settings']
    os.chdir(ROOT)
    if kind in ('studio-batch','animate-batch'):
        from .studio_batch import run
        run(payload,settings,cancel,event,lambda p,s,c,e:studio(p,s,c,animated=kind=='animate-batch',emit=e))
    elif kind in ('studio','animate'):studio(payload,settings,cancel,kind=='animate')
    else:raise ValueError('Only AI Studio and Animate jobs are supported')
if __name__=='__main__':
    try:main()
    except Exception as error:
        print(f'[ERROR] {type(error).__name__}: {error}',flush=True);sys.exit(1)

