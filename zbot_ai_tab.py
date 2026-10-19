from __future__ import annotations
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import traceback
from pathlib import Path
_LLM_SYSTEM = 'You are an expert short-form video scriptwriter (zBot style). You write punchy, scroll-stopping scripts with a strong hook. Always answer with ONLY a single JSON object, no markdown fences, no commentary. The JSON shape is:\n{\n  "title": "short catchy video title",\n  "hook": "one-line opening hook",\n  "hashtags": ["#tag1", "#tag2"],\n  "scenes": [\n    {"narration": "one spoken line (~10-20 words)",\n     "visual_prompt": "detailed image prompt for this scene",\n     "caption": "short on-screen text"}\n  ]\n}\nAim for 5-8 scenes. Each narration line must be spoken aloud, so no stage directions. Each visual_prompt must be a self-contained image prompt for the image generator (subject, style, lighting).'
_FALLBACK_STYLES = ['cinematic 4k, dramatic lighting, shallow depth of field', 'ultra-detailed, moody atmosphere, cinematic color grade', 'soft natural light, realistic textures, high detail', 'dramatic golden-hour light, epic composition, photorealistic', 'clean minimal composition, strong contrast, editorial photography']
_TTS_ENGINE_CHAIN = ['google_cloud', 'local', 'piper']
GEMINI_IMAGE_MODELS = ['gemini-2.5-flash-image', 'gemini-3.1-flash-image', 'gemini-3-pro-image-preview', 'gemini-3.1-flash-lite-image']
from gemini_text_fallback import TEXT_MODELS
GEMINI_LLM_MODELS = list(TEXT_MODELS)
GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta'
RES_ASPECT = {'1080x1920': '9:16', '720x1280': '9:16', '1920x1080': '16:9', '1080x1080': '1:1'}
_IMG_RETRY_WAITS = (5, 15, 30)
_TRANSIENT_429 = ('resource has been exhausted', 'resource_exhausted', 'rate limit', 'too many requests')
_MOTION_ZOOM = 0.14
_MOTION_FPS = 25

def _slug(text: str, fallback: str='untitled') -> str:
    """Filesystem-safe slug from arbitrary text."""
    s = re.sub('[^\\w\\s-]', '', text or '').strip().lower()
    s = re.sub('[\\s_-]+', '_', s)
    return s[:60] or fallback
from ai_studio_workflow import AIStudioWorkflowMixin

class ZBotBaseTabMixin:

    def _zb_merged_settings(self):
        """Host settings overlaid with the dashboard's saved automation keys."""
        merged = dict(self.settings or {})
        try:
            p = Path('automation_settings.json')
            if p.exists():
                merged.update(json.loads(p.read_text(encoding='utf-8')))
        except Exception:
            pass
        return merged

    def _zb_gemini_keys(self, merged=None):
        """Every configured Gemini API key, de-duplicated, primary first.

        Reads the ``gemini_api_keys`` pool (list, or a comma/newline separated
        string) plus the single ``gemini_api_key``.  The pool is what makes a
        configured key fallback available. Keys in one project share quotas.
        """
        m = self._zb_merged_settings() if merged is None else merged
        keys = []
        pool = m.get('gemini_api_keys')
        if isinstance(pool, str):
            pool = re.split('[,\\s]+', pool)
        for k in pool or []:
            k = str(k or '').strip()
            if k and k not in keys:
                keys.append(k)
        primary = str(m.get('gemini_api_key') or '').strip()
        if primary:
            if primary in keys:
                keys.remove(primary)
            keys.insert(0, primary)
        return keys

    def _zb_default_image_provider(self):
        """Pick the image route that can actually produce an image.

        The browser route was the original default, but the logged-in Gemini
        account is served a text-only model and answers image prompts with
        "I cannot generate or render visual image files directly" — verified
        2026-09-10.  So when a service account is configured (it renders via
        Vertex AI, ~$0.039/image on gemini-2.5-flash-image) prefer the API
        route; the free API keys still cannot make images at all.  The browser
        route stays the fallback — for Meta AI, or a different Google account.
        """
        return 'gemini_api' if self._zb_service_account() else 'gemini'

    def _zb_service_account(self):
        """Path to a configured service account, or ''."""
        for key in ('gemini_service_account', 'service_account_path'):
            val = str(self.settings.get(key) or '').strip()
            if val:
                return val
        return ''

    def _zb_default_provider(self):
        if os.environ.get('ANTHROPIC_BASE_URL') and os.environ.get('ANTHROPIC_AUTH_TOKEN'):
            return 'anthropic'
        try:
            if self._zb_gemini_keys():
                return 'gemini'
        except Exception:
            pass
        return 'openai'

    def _zb_llm(self, system, user, max_tokens=2000, provider=None, json_mode=False):
        """Route to the configured LLM (mirrors AutomationDashboard.call_llm_api
        but returns the raw text, and honors the .env Anthropic proxy)."""
        import requests
        merged = self._zb_merged_settings()
        if provider is None:
            provider = self.zb_llm_var.get() if hasattr(self, 'zb_llm_var') else merged.get('llm_provider', 'openai')
        try:
            if provider == 'gemini':
                keys = self._zb_gemini_keys(merged)
                if not keys:
                    return (None, 'Gemini API key not configured — paste one in AI Studio → 🍌 Gemini API → 🔑 Key')
                from gemini_text_fallback import generate
                return generate(self, merged, keys, system, user, max_tokens, GEMINI_API_BASE, json_mode=json_mode)
            if provider == 'openai':
                key = merged.get('openai_api_key', '')
                if not key:
                    return (None, 'OpenAI key not configured (set it in AI Automation → configure LLM)')
                r = requests.post('https://api.openai.com/v1/chat/completions', headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}, json={'model': merged.get('openai_model', 'gpt-4o-mini'), 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], 'max_tokens': max_tokens, 'temperature': 0.8}, timeout=120)
                if r.status_code == 200:
                    return (r.json()['choices'][0]['message']['content'], None)
                return (None, f'OpenAI {r.status_code}: {r.text[:200]}')
            if provider == 'openrouter':
                key = merged.get('openrouter_api_key', '')
                if not key:
                    return (None, 'OpenRouter key not configured')
                r = requests.post('https://openrouter.ai/api/v1/chat/completions', headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}, json={'model': merged.get('openrouter_model', 'anthropic/claude-3-haiku'), 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], 'max_tokens': max_tokens, 'temperature': 0.8}, timeout=120)
                if r.status_code == 200:
                    return (r.json()['choices'][0]['message']['content'], None)
                return (None, f'OpenRouter {r.status_code}: {r.text[:200]}')
            if provider == 'anthropic':
                base = os.environ.get('ANTHROPIC_BASE_URL', 'https://api.anthropic.com')
                token = os.environ.get('ANTHROPIC_AUTH_TOKEN', '')
                model = os.environ.get('ANTHROPIC_MODEL', merged.get('anthropic_model', 'claude-sonnet-4-5'))
                headers = {'Content-Type': 'application/json'}
                if token:
                    headers['Authorization'] = f'Bearer {token}'
                else:
                    key = merged.get('anthropic_api_key', '')
                    if not key:
                        return (None, 'Anthropic key not configured')
                    headers['x-api-key'] = key
                    headers['anthropic-version'] = '2023-06-01'
                r = requests.post(f'{base}/v1/messages', headers=headers, json={'model': model, 'max_tokens': max_tokens, 'system': system, 'messages': [{'role': 'user', 'content': user}]}, timeout=120)
                if r.status_code == 200:
                    return (r.json()['content'][0]['text'], None)
                return (None, f'Anthropic {r.status_code}: {r.text[:200]}')
            if provider == 'local':
                url = merged.get('local_llm_url', 'http://localhost:11434')
                r = requests.post(f'{url}/api/generate', json={'model': merged.get('local_llm_model', 'llama3.2'), 'prompt': f'{system}\n\n{user}', 'stream': False}, timeout=180)
                if r.status_code == 200:
                    return (r.json().get('response', ''), None)
                return (None, f'Local LLM {r.status_code}: {r.text[:200]}')
            return (None, f'Unknown provider {provider!r}')
        except Exception as e:
            return (None, f'{e}')

    @staticmethod
    def _zb_strip_tags(line):
        vis = re.search('\\[visual:\\s*(.*?)\\]', line, re.I)
        cap = re.search('\\[caption:\\s*(.*?)\\]', line, re.I)
        clean = re.sub('\\[(?:visual|caption):\\s*.*?\\]', '', line, flags=re.I).strip()
        if not clean:
            clean = re.sub('\\[.*?\\]', '', line).strip()
        return (vis.group(1).strip() if vis else '', cap.group(1).strip() if cap else '', clean)

    def _zb_parse_script_text(self, text):
        scenes = []
        for line in (text or '').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if re.fullmatch('[\\d\\s\\-.]+', line):
                continue
            if '-->' in line:
                continue
            if re.match('^title\\s*[:]', line, re.I):
                continue
            vis, cap, clean = self._zb_strip_tags(line)
            if not clean:
                continue
            scenes.append({'raw': line, 'narration': clean, 'visual_prompt': vis, 'caption': cap, 'image_path': '', 'audio_path': ''})
        return scenes

    @staticmethod
    def _zb_parse_package_text(raw):
        """Return (package dict, scenes list, error str)."""
        text = (raw or '').strip()
        m = re.search('\\{.*\\}', text, re.DOTALL)
        if not m:
            return ({}, [], 'no JSON object found')
        try:
            pkg = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return ({}, [], f'bad JSON: {e}')
        scenes = []
        for s in pkg.get('scenes', []):
            scenes.append({'raw': str(s.get('narration', '')).strip(), 'narration': str(s.get('narration', '')).strip(), 'visual_prompt': str(s.get('visual_prompt', '')).strip(), 'caption': str(s.get('caption', '')).strip(), 'image_path': '', 'audio_path': ''})
        pkg.setdefault('title', '')
        return (pkg, scenes, None)

    @staticmethod
    def _zb_offline_prompt(idx, narration):
        style = _FALLBACK_STYLES[idx % len(_FALLBACK_STYLES)]
        return f'{narration}, {style}'

    def _zb_clean_narration(self, text):
        t = re.sub('\\[(?:visual|caption|emotion):\\s*.*?\\]', '', text or '', flags=re.I)
        t = re.sub('\\[[\\w\\s-]+\\]', '', t)
        t = re.sub('^\\s*(?:CTA)\\s*[:\\-–—]\\s*', '', t, flags=re.I | re.MULTILINE)
        t = re.sub('\\s*\\(\\s*\\d+\\s*(?:words?)?\\s*\\)\\s*$', '', t, flags=re.I | re.MULTILINE)
        t = re.sub('\\s*\\|\\s*\\[.*?\\]\\s*', '', t)
        return t.strip()

class ZBotAITabMixin(AIStudioWorkflowMixin, ZBotBaseTabMixin):
    """AI Studio with durable planning, media generation and rendering."""
    pass
