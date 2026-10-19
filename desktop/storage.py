from __future__ import annotations
import ast
import copy
import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r'api.?key|password|secret|token|credential|service.account|authorization', re.I)

def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)

def read(path, default=None):
    path = Path(path)
    return json.loads(path.read_text('utf-8')) if path.exists() else copy.deepcopy({} if default is None else default)

def public(value):
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if not SECRET.search(k) and not k.startswith('_')}
    if isinstance(value, list):
        return [public(v) for v in value]
    return value

def redact(text, settings):
    def secrets(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if SECRET.search(key):
                    if isinstance(item, str) and item:
                        yield item
                        if re.search(r'api.?keys$',key,re.I):
                            yield from (part for part in re.split(r'[,\s]+',item) if part)
                    elif isinstance(item, list):
                        yield from (str(x) for x in item if x)
                elif isinstance(item, (dict, list)):
                    yield from secrets(item)
        elif isinstance(value, list):
            for item in value:
                yield from secrets(item)
    text = str(text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    for secret in sorted(set(secrets(settings)), key=len, reverse=True):
        text = text.replace(secret, '[redacted]')
    return re.sub(r'(?i)(key|token|password|authorization)=([^\s&]+)', r'\1=[redacted]', text)

@lru_cache(maxsize=1)
def defaults():
    return read(ROOT/'defaults.json')

class Store:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.lock = threading.RLock()

    def settings(self):
        with self.lock:
            path = self.root / 'overlay_settings.json'
            from .vault import load
            return {**copy.deepcopy(defaults()), **read(path),
                    **load(self.root / '.desktop/credentials.bin')}

    def worker_settings(self):
        # Dashboard configuration is required by the existing writing providers.
        merged = read(self.root / 'automation_settings.json')
        merged.update(self.settings())
        private=self.root/'private/google_service_account.json'
        if private.is_file():merged.update(gemini_service_account=str(private),service_account_path=str(private))
        if merged.get('bgm_file'):
            local=self.root/'assets/audio'/Path(merged['bgm_file']).name
            if local.is_file():merged['bgm_file']=str(local)
        return merged

    def drafts(self):
        result = {}
        settings = self.settings()
        for kind, filename in (('studio', 'ai_studio_draft.json'), ('animate', 'ai_studio_animate_draft.json')):
            path = Path(settings.get('zb_draft_path') or self.root / 'zbot_profiles' / filename)
            if kind == 'animate':
                path = path.with_name(filename)
            saved = read(path)
            if saved.get('version') == 1:
                controls = saved.get('controls', {})
                result[kind] = {**controls, 'script': saved.get('script', ''), 'project': saved.get('project') or '',
                    'style_name': controls.get('style', 'Cinematic realistic'),
                    'use_transitions_tab': False,
                    'use_effects_tab': False}
        result.update(read(self.root / '.desktop/drafts.json'))
        return public(result)

    def snapshot(self):
        with self.lock:
            return {'settings': public(self.settings()), 'paths': public(read(self.root / 'processing_paths.json')),
                    'preferences': read(self.root / '.desktop/preferences.json', {'theme': 'crimson'}),
                    'credentials': self.credential_status()}

    def credential_status(self):
        return {k: bool(v) for k, v in self.worker_settings().items() if SECRET.search(k)}

    def update(self, section, patch):
        names = {'settings': 'overlay_settings.json', 'paths': 'processing_paths.json', 'preferences': '.desktop/preferences.json'}
        if section not in names or not isinstance(patch, dict):
            raise ValueError('Invalid settings section')
        if section == 'preferences':
            if set(patch) - {'theme', 'collapsed_cards'}:
                raise ValueError('Unknown interface preference')
            if 'theme' in patch and patch['theme'] not in ('crimson', 'ember', 'matte'):
                raise ValueError('Choose Crimson, Ember or Matte')
            if 'collapsed_cards' in patch:
                cards = patch['collapsed_cards']
                if not isinstance(cards, dict) or len(cards) > 1000 or any(not isinstance(k, str) or len(k) > 300 or type(v) is not bool for k, v in cards.items()):
                    raise ValueError('Invalid card visibility preferences')
        if section == 'paths' and set(patch) - {'video_folder', 'quotes_file', 'output_folder'}:
            raise ValueError('Unknown processing path')
        if section == 'settings' and public(patch) != patch:
            raise ValueError('Credentials must use the dedicated credential form')
        with self.lock:
            path = self.root / names[section]
            value = read(path)
            # Merge nested settings so omitted legacy fields survive.
            def merge(old, new):
                for key, item in new.items():
                    if isinstance(item, dict) and isinstance(old.get(key), dict):
                        merge(old[key], item)
                    else:
                        old[key] = item
            merge(value, patch)
            atomic(path, value)

    def credential(self, key, value):
        if not SECRET.search(key) or not isinstance(value, str):
            raise ValueError('Invalid credential')
        if key=='gemini_api_keys':
            pool=list(dict.fromkeys(part for part in re.split(r'[,\s]+',value.strip()) if part))
            if not pool:raise ValueError('Paste at least one Gemini API key, one per line.')
            if len(pool)>50 or any(len(part)>512 for part in pool):raise ValueError('Use at most 50 API keys, each at most 512 characters.')
            value='\n'.join(pool)
        with self.lock:
            from .vault import load, save
            path = self.root / '.desktop/credentials.bin'
            settings = load(path)
            settings[key] = value
            save(path, settings)
