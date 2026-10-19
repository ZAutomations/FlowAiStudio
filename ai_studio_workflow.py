from __future__ import annotations
import copy
import json
import queue
import shutil
import threading
from datetime import datetime
from pathlib import Path
from ai_studio_pipeline import STYLE_PRESETS, TRANSITIONS, Cancelled, atomic_json, check_cancel, fingerprint, image_prompt, probe, render_video, split_script, valid_audio, valid_image
from ai_studio_tab_render import captions_enabled, tab_settings_snapshot
VOICE_KEYS = { 'local': ('kokoro_voice', 'af_bella'), 'google_cloud': ('gemini_tts_voice', 'Zephyr'),   'piper': ('piper_voice', 'en_US-ryan-medium')}
VOICE_OPTIONS = {'tts_speed', 'tts_override_rate', 'kokoro_speed', 'piper_speed', 'gemini_tts_speed', 'gemini_tts_language', 'gemini_tts_prompt', 'gemini_tts_model', 'use_cloud_tts', 'cloud_tts_voice'} | {key for key, default in VOICE_KEYS.values()}
DRAFT_CONTROLS = {'title': 'zb_title_var', 'output_dir': 'zb_out_dir_var', 'provider': 'zb_provider_var', 'llm': 'zb_llm_var', 'resolution': 'zb_res_var', 'style': 'zb_style_var', 'custom_style': 'zb_custom_style_var', 'continuity': 'zb_continuity_var', 'shot_seconds': 'zb_shot_seconds_var', 'voice_engine': 'zb_voice_engine_var', 'voice': 'zb_voice_var', 'fallback': 'zb_fallback_var', 'motion': 'zb_motion_var', 'bgm': 'zb_bgm_var', 'captions': 'zb_captions_var', 'transitions_tab': 'zb_use_transitions_tab_var', 'effects_tab': 'zb_use_effects_tab_var', 'chrome_mode': 'zb_cdp_var', 'show_browser': 'zb_show_browser_var', 'flow_url': 'zb_flow_url_var', 'share_google_profile': 'zb_share_google_profile_var', 'image_batch_size': 'zb_image_batch_size_var', 'narration_style': 'zb_narration_style_var', 'narration_direction': 'zb_narration_direction_var'}

class AIStudioWorkflowMixin:

    def _zb_default_image_provider(self):
        return 'gemini'

    def _zb_merged_settings(self):
        if getattr(self, '_zb_job_config', None):
            return dict(self._zb_job_config['settings'])
        return super()._zb_merged_settings()

    def _zb_get_project_dir(self, create=False):
        origin = (self.zb_out_dir_var.get(), self.zb_title_var.get())
        if self.zb_project_dir is not None and self._zb_project_origin not in (None, origin):
            self.zb_project_dir = None
            self.zb_last_video = None
        if self.zb_project_dir is None:
            from zbot_ai_tab import _slug
            base = Path(origin[0] or 'FinalVideos').expanduser().resolve()
            self.zb_project_dir = base / f'zbot_{_slug(origin[1])}_{datetime.now():%Y%m%d_%H%M%S_%f}'
        self._zb_project_origin = origin
        if create:
            for sub in ('', 'images', 'voice', 'clips'):
                (Path(self.zb_project_dir) / sub).mkdir(parents=True, exist_ok=True)
        return Path(self.zb_project_dir)

    def _zb_save_project(self, config):
        project = Path(config['project'])
        scenes = copy.deepcopy(self.zb_scenes)
        for scene in scenes:
            for key in ('image_path', 'audio_path'):
                if scene.get(key):
                    try:
                        scene[key] = Path(scene[key]).resolve().relative_to(project.resolve()).as_posix()
                    except ValueError:
                        pass
        options = {key: value for key, value in config.items() if key not in ('settings', 'project', 'script', 'title', '_export_batches', '_local_references_only', '_exported_tokens', '_exported_groups', '_recover_only', '_generate_missing', '_manifest_name', '_download_one_batch', '_part_result', '_download_summary')}
        options['caption_settings'] = {key: value for key, value in config['settings'].items() if key.startswith('caption_')}
        options['render_tab_settings'] = tab_settings_snapshot(config['settings'])
        options['voice_settings'] = {key: value for key, value in config['settings'].items() if key in VOICE_OPTIONS}
        atomic_json(project / 'project.json', {'version': 3, 'title': config['title'], 'script': config['script'], 'package': self.zb_package, 'scenes': scenes, 'options': options, 'last_video': Path(self.zb_last_video).name if getattr(self, 'zb_last_video', None) else ''})

    def _zb_parse_script_text(self, text):
        try:
            seconds = float(self.zb_shot_seconds_var.get()) if hasattr(self, 'zb_shot_seconds_var') else 7
        except (ValueError, tk.TclError):
            seconds = 7
        wpm = float(self.settings.get('tts_speed', 150))
        return split_script(text, max_words=max(8, int(seconds * wpm / 60)))

    def _zb_generate_package(self):
        title = self.zb_title_var.get().strip()
        if not title:
            messagebox.showwarning('AI Studio', 'Enter a project title first.')
            return

        def work(q):
            from zbot_ai_tab import _LLM_SYSTEM
            from ai_studio_visual_context import TOPIC_DIRECTION
            config = self._zb_job_config
            raw, error = self._zb_llm(_LLM_SYSTEM + '\n' + TOPIC_DIRECTION, 'Topic: ' + title + '\nReturn the script package as JSON.', max_tokens=6000, provider=config['llm'])
            if error:
                raise RuntimeError('Script generation failed: ' + error)
            package, source_scenes, error = self._zb_parse_package_text(raw)
            if error or not source_scenes or (not all((s['narration'] for s in source_scenes))):
                raise RuntimeError('The model returned an invalid or empty script package; the existing script was preserved.')
            scenes = []
            for original in source_scenes:
                pieces = split_script(original['narration'], max_words=max(8, int(config['shot_seconds'] * float(config['settings'].get('tts_speed', 150)) / 60)))
                for piece in pieces:
                    if len(pieces) == 1:
                        piece['visual_prompt'] = original.get('visual_prompt', '')
                    piece['caption'] = original.get('caption', '')
                    scenes.append(piece)
            self.zb_scenes = scenes
            self.zb_package = package
            self.zb_last_video = None
            script = '\n\n'.join((s['narration'] for s in scenes))
            config['script'] = script
            q.put(('script', script))
            q.put(('refresh',))
            q.put(('log', 'success', f'Generated {len(scenes)} scenes. Edit them before Build All if needed.'))
        self._zb_start_worker(work)

    def _zb_fill_prompts(self, q, config):
        from ai_studio_visual_context import TOPIC_DIRECTION, MEANING_DIRECTION, planning_context, contextual_fallback
        missing = [i for i, scene in enumerate(self.zb_scenes) if not scene.get('visual_prompt')]
        for start in range(0, len(missing), 12):
            check_cancel(self._zb_cancel)
            indices = missing[start:start + 12]
            q.put(('log', 'info', f'Writing contextual image prompts: {start + 1}–{start + len(indices)} of {len(missing)} missing scenes.'))
            user = json.dumps(planning_context(config, self.zb_scenes, indices), ensure_ascii=False)
            system = 'Create one concrete image prompt per narration, in order. Return only a JSON array of strings. Never rewrite the narration. Each image must depict a single visual beat, not a collage. Describe subjects, their action and environment; avoid embedded text. Style: ' + config['style'] + '. Character/setting continuity: ' + config['continuity'] + '\n' + TOPIC_DIRECTION + '\n' + MEANING_DIRECTION + ' Return prompts only for the supplied scenes, in their supplied order; context is not an extra scene.'
            raw, error = self._zb_llm(system, user, max_tokens=5000, provider=config['llm'])
            prompts = None
            reason = error or 'Writer returned invalid JSON or an incomplete prompt array.'
            if not error:
                try:
                    import re
                    prompts = json.loads(re.search('\\[.*\\]', raw, re.S).group())
                    if not isinstance(prompts, list) or len(prompts) != len(indices) or (not all((isinstance(p, str) and p.strip() for p in prompts))):
                        prompts = None
                except (AttributeError, ValueError):
                    pass
            if prompts is None:
                from desktop.storage import redact
                q.put(('log', 'warn', 'Prompt writer: ' + redact(reason, self._zb_merged_settings())))
                q.put(('log', 'warn', 'AI prompts unavailable or invalid; using full-topic and neighboring-narration context for this batch.'))
            for j, i in enumerate(indices):
                self.zb_scenes[i]['visual_prompt'] = prompts[j].strip() if prompts else contextual_fallback(config, self.zb_scenes, i)
            self._zb_save_project(config)
            q.put(('refresh',))

    def _zb_clean_narration(self, text):
        import re
        text = re.sub('\\[(?:visual|caption|emotion):\\s*.*?\\]', '', text or '', flags=re.I)
        text = re.sub('^\\s*CTA\\s*[:\\-–—]\\s*', '', text, flags=re.I)
        text = re.sub('\\s*\\(\\s*\\d+\\s*(?:words?)?\\s*\\)\\s*$', '', text, flags=re.I)
        return text.strip()

    def _zb_images_pass(self, q, config, recover_only=False):
        if config.get('character_consistency'):
            from ai_studio_consistency import generate
            return generate(self, q, config, recover_only)
        from zbot_ai_tab import RES_ASPECT
        aspect = RES_ASPECT.get(config['resolution'], '16:9')
        pending = []
        from ai_studio_parts import scene_range
        first, last = scene_range(config, len(self.zb_scenes))
        for i, scene in enumerate(self.zb_scenes):
            if not first <= i < last:
                continue
            prompt = image_prompt(scene, config['style'], aspect, config['continuity'])
            key = fingerprint(config['provider'], prompt)
            if valid_image(scene.get('image_path', '')) and (scene.get('manual_image') or scene.get('image_key') == key):
                continue
            scene['image_path'] = ''
            pending.append((i, prompt, key))
        if not pending:
            q.put(('log', 'info', 'All scene images are valid and unchanged; reused.'))
            return
        if config['provider'] != 'gemini_api':
            from zbot_browser_images import ZBotImageGenerator
            from desktop.browser_accounts import browser_options
            generator = ZBotImageGenerator(config['provider'], mode=config['browser_mode'], log=lambda msg, level='info': q.put(('log', level, msg)), flow_project_url=config['flow_url'], cancel=self._zb_cancel, share_google_profile=config.get('share_google_profile', False), flow_aspect_ratio=aspect, **browser_options(config))
            completed_results = set()
            reported_failures = set()

            def result(index, ok, detail):
                i, prompt, key = pending[index]
                scene = self.zb_scenes[i]
                out = Path(config['project']) / 'images' / f'scene_{i + 1:04d}.png'
                if ok and valid_image(out):
                    scene.update(image_path=str(out), image_key=key, image_status='done')
                    q.put(('log', 'success', f'Scene {i + 1}: image saved.'))
                else:
                    scene['image_status'] = 'failed'
                    if str(detail) not in reported_failures:
                        reported_failures.add(str(detail))
                        q.put(('log', 'error', f'Scene {i + 1}: {detail}'))
                self._zb_save_project(config)
                q.put(('refresh',))
                completed_results.add(index)
                q.put(('progress', int(len(completed_results) / len(pending) * 100)))
            items = [(prompt, str(Path(config['project']) / 'images' / f'scene_{i + 1:04d}.png')) for i, prompt, key in pending]
            results = generator.generate_batch(items, on_result=result, headless=config['headless'], timeout=240, recover_only=recover_only, batch_size=config.get('image_batch_size', 6))
            check_cancel(self._zb_cancel)
            if recover_only:
                recovered = sum((bool(ok) for ok, detail in results))
                q.put(('log', 'info', f'Recovered {recovered}/{len(pending)} missing images without generating new ones. Generate Images continues any remaining scenes.'))
                return
            if len(results) != len(pending) or not all((ok for ok, detail in results)):
                limit = next((detail for ok, detail in results if not ok and 'Account limit reached:' in str(detail)), None)
                if limit:
                    raise RuntimeError(limit)
                detail = next((str(detail) for ok, detail in results if not ok), 'Image provider returned an incomplete result list.')
                raise RuntimeError('Image generation stopped: ' + detail + ' Completed images and pending requests are retained.')
        else:
            import thumbnail_designer as td
            settings = config['settings']
            if not (settings.get('gemini_service_account') or settings.get('service_account_path') or settings.get('gemini_api_key')):
                raise RuntimeError('Gemini API requires configured credentials. Select Gemini browser to use your browser account.')
            for n, (i, prompt, key) in enumerate(pending):
                check_cancel(self._zb_cancel)
                out = Path(config['project']) / 'images' / f'scene_{i + 1:04d}.png'
                ok = td.generate_thumbnail(prompt, out, frame_path=None, aspect=aspect, settings=settings, model=settings.get('zb_gemini_image_model', 'gemini-2.5-flash-image'), timeout=180, log=lambda level, text: q.put(('log', 'warn' if level == 'warn' else 'info', text)))
                if not ok or not valid_image(out):
                    self.zb_scenes[i]['image_status'] = 'failed'
                    raise RuntimeError(f'Gemini API failed for scene {i + 1}; check credentials/quota. Browser is a separate selectable route.')
                self.zb_scenes[i].update(image_path=str(out), image_key=key, image_status='done')
                self._zb_save_project(config)
                q.put(('refresh',))
                q.put(('progress', int((n + 1) / len(pending) * 100)))

    def _zb_voice_pass(self, q, config):
        from studio_voice import TTSGenerator
        from ai_studio_narration import settings_for, resolve, STYLES
        settings = config['settings']
        chosen = config['voice_engine']
        chain = [chosen] + ([e for e in VOICE_KEYS if e != chosen] if config['fallback'] else [])

        def signature(i):
            effective, _ = settings_for(config, i, len(self.zb_scenes))
            voice_settings = {key: value for key, value in effective.items() if key.startswith(('tts_', 'kokoro_', 'piper_', 'gemini_tts_', 'cloud_tts_'))}
            if chosen == 'google_cloud':
                voice_settings['use_cloud_tts'] = effective.get('use_cloud_tts', False)
                return fingerprint(self._zb_clean_narration(self.zb_scenes[i]['narration']), chosen, voice_settings, 'gemini-style-adapter-v2')
            return fingerprint(self._zb_clean_narration(self.zb_scenes[i]['narration']), chosen, voice_settings)
        if chosen == 'google_cloud':
            selected = resolve(config)
            q.put(('log', 'info', 'Gemini narration style: ' + STYLES[selected][0] + ('. Overrides Audio & Voice delivery prompt; selected voice retained.' if selected != 'original' else '. Using Audio & Voice delivery settings.')))
        locked_engine = next((scene.get('voice_engine', chosen) for i, scene in enumerate(self.zb_scenes) if scene.get('audio_key') == signature(i) and valid_audio(scene.get('audio_path', ''))), None)
        for i, scene in enumerate(self.zb_scenes):
            check_cancel(self._zb_cancel)
            text = self._zb_clean_narration(scene['narration'])
            key = signature(i)
            if valid_audio(scene.get('audio_path', '')) and scene.get('audio_key') == key and (scene.get('voice_engine', chosen) == locked_engine):
                continue
            scene['audio_path'] = ''
            out = Path(config['project']) / 'voice' / f'scene_{i + 1:04d}.mp3'
            success = False
            for engine in [locked_engine] if locked_engine else chain:
                check_cancel(self._zb_cancel)
                styled, resolved = settings_for({**config, 'voice_engine': engine}, i, len(self.zb_scenes))
                attempt_settings = dict(styled, tts_engine=engine, use_tts_voiceover=True)
                attempt = out.with_name(out.stem + '.generating' + out.suffix)
                ok, words = TTSGenerator.generate_voiceover(text, attempt, attempt_settings)
                effective_engine = attempt_settings.get('tts_engine', engine)
                if locked_engine and effective_engine != locked_engine:
                    raise RuntimeError(f'The saved {locked_engine} voice became unavailable. Fix that engine or choose a different engine and regenerate all voice files; narration will not switch voices halfway through.')
                if effective_engine != engine and (not config['fallback']):
                    raise RuntimeError(f'{engine} could not run and attempted to switch to {effective_engine}. Enable Fallback chain or fix the selected engine in Audio Settings.')
                if ok and valid_audio(attempt):
                    attempt.replace(out)
                    locked_engine = effective_engine
                    scene.update(audio_path=str(out), audio_key=key, audio_status='done', word_timings=words or [], voice_engine=effective_engine, timing_source='tts' if effective_engine == 'cloud' else 'estimated')
                    if effective_engine != chosen:
                        q.put(('log', 'warn', f'Using fallback {effective_engine} consistently for this project.'))
                    success = True
                    break
            if not success:
                scene['audio_status'] = 'failed'
                raise RuntimeError(f'Voice failed at scene {i + 1}. Check the selected voice in Audio Settings; completed audio is retained.')
            self._zb_save_project(config)
            q.put(('refresh',))
            q.put(('progress', int((i + 1) / len(self.zb_scenes) * 100)))
            q.put(('log', 'success', f'Scene {i + 1}: voice saved ({locked_engine}).'))

    def _zb_render_pass(self, q, config):
        self.zb_last_video = None
        self.zb_last_video = str(render_video(self.zb_scenes, config['project'], config, self._zb_cancel, progress=lambda n: q.put(('progress', n)), log=lambda msg: q.put(('log', 'info', msg))))
        self._zb_save_project(config)
        q.put(('log', 'success', 'Rendered: ' + self.zb_last_video))
