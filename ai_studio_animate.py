from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
from ai_studio_workflow import AIStudioWorkflowMixin, DRAFT_CONTROLS
from zbot_ai_tab import ZBotBaseTabMixin
from ai_studio_pipeline import atomic_json, fingerprint, valid_image, run_ffmpeg, check_cancel
from ai_studio_animate_media import generate_agent_media, valid_video
from ai_studio_animate_render import render_animated_video
DEFAULT_AGENT_TOOL = str(Path(__file__).parent / 'animate_flow_backend')

class AnimateStudio(AIStudioWorkflowMixin, ZBotBaseTabMixin):
    _is_animate = True

    def _zb_save_project(self, config):
        super()._zb_save_project(config)
        p = Path(config['project'])
        data = json.loads((p / 'project.json').read_text(encoding='utf-8'))
        data['workflow'] = 'animate'
        for scene in data['scenes']:
            if scene.get('video_path'):
                try:
                    scene['video_path'] = Path(scene['video_path']).resolve().relative_to(p.resolve()).as_posix()
                except ValueError:
                    pass
        atomic_json(p / 'project.json', data)

    def _zb_write_story(self, q, config):
        from ai_studio_story import write_story
        write_story(self, q, config)

    def _zb_fill_prompts(self, q, config):
        from ai_studio_pipeline import fingerprint
        if config.get('ready_animation_script_key') == fingerprint(config['script']) and all(s.get('visual_prompt') for s in self.zb_scenes):
            q.put(('log', 'info', 'Reusing imported Animate visual prompts; narration is unchanged.'))
            return
        from ai_studio_story import is_narration_story
        if is_narration_story(config):
            return self._zb_write_story(q, config)
        return super()._zb_fill_prompts(q, config)

    def _zb_images_pass(self, q, config, recover_only=False):
        from ai_studio_animate_options import partial_options
        if config.get('animation_mode','partial') == 'partial' and partial_options(config)[0] == 'seconds':
            q.put(('log','info','Measuring opening animation against actual narration. Generating/reusing voice first.'))
            if not getattr(self,'_opening_voice_ready',False):self._zb_voice_pass(q, config)
            self._opening_voice_ready=True
            from ai_studio_animate_options import scene_duration, animation_count
            elapsed=0
            for scene in self.zb_scenes:
                if elapsed>=float(config.get('animate_seconds',80)):break
                scene['animation_duration']=scene_duration(scene);elapsed+=scene['animation_duration']
            q.put(('log','info',f'Opening {config.get("animate_seconds",80)} seconds: {animation_count(config,len(self.zb_scenes),self.zb_scenes)} scenes need video clips; remaining scenes use images.'))
        if recover_only:
            raise RuntimeError('Animate resumes matched images and clips through Generate Agent Media.')
        from ai_studio_animate_setup import ensure_project, ensure_references
        log = lambda m: q.put(('log', 'info', m))
        config['flow_url'] = ensure_project(config, self._zb_cancel, log)
        q.put(('callback', lambda url=config['flow_url']: self.zb_flow_url_var.set(url)))

        def plan_designs(refs):
            import re
            system = 'Plan distinct recurring character designs and a recurring location for this script. Return ONLY a JSON object mapping each supplied permanent asset name to a detailed design string. Keep supplied names exactly. Character designs must specify role, age, face, hair, fixed clothing and colors. Location must specify layout and grey scenery. Do not invent additional named assets. Honor the provided preset design and visual style.'
            user = json.dumps({'assets': [{'name': r['name'], 'kind': r['kind']} for r in refs], 'script': config['script'], 'style': config['style'], 'design': config.get('reference_design', ''), 'continuity': config.get('continuity', '')})
            from ai_studio_story import is_narration_story
            raw, error = self._zb_llm(system, user, max_tokens=2200, provider='gemini' if is_narration_story(config) else config['llm'])
            if error:
                raise RuntimeError('Character/location planning failed: ' + str(error))
            try:
                return json.loads(re.search('\\{.*\\}', raw, re.S).group())
            except (AttributeError, ValueError):
                raise RuntimeError('Character/location planner returned invalid JSON. Retry with the selected writing provider.')
        config['references'] = ensure_references(config, self._zb_cancel, log, plan_designs)
        self._zb_save_project(config)

        def media(record):
            scene = self.zb_scenes[record['index']]
            if record['kind'] == 'video':
                scene.update(video_path=record['output'], video_key=record['key'], video_status='done')
                thumbnail = Path(config['project']) / 'images' / f"scene_{record['index'] + 1:04d}.png"
                thumbnail.parent.mkdir(exist_ok=True)
                if not valid_image(thumbnail):
                    run_ffmpeg(['-i', record['output'], '-frames:v', '1', thumbnail], self._zb_cancel)
                scene['image_path'] = str(thumbnail)
            else:
                scene.update(image_path=record['output'], image_key=record['key'], image_status='done')
            self._zb_save_project(config)
            q.put(('refresh',))
            q.put(('log', 'success', f"Scene {record['index'] + 1}: {record['kind']} saved."))
        generate_agent_media(self.zb_scenes, config, self._zb_cancel, lambda m: q.put(('log', 'info', m)), media)

    def _zb_render_pass(self, q, config):
        self.zb_last_video = str(render_animated_video(self.zb_scenes, config['project'], config, self._zb_cancel, progress=lambda n: q.put(('progress', n)), log=lambda m: q.put(('log', 'info', m))))
        self._zb_save_project(config)
        q.put(('log', 'success', 'Animate rendered: ' + self.zb_last_video))
