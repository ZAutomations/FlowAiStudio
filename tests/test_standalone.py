import ast,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from desktop.storage import ROOT,Store
from desktop.server import create_app
from fastapi.testclient import TestClient
from standalone_config import normalize
from ai_studio_workflow import VOICE_KEYS

class StandaloneTests(unittest.TestCase):
    def test_only_three_voice_engines_and_clean_render_boundary(self):
        self.assertEqual(set(VOICE_KEYS),{'google_cloud','local','piper'})
        c=normalize({'voice_engine':'google_cloud','settings':{},'use_effects_tab':True,'use_transitions_tab':True,'transition':'Dissolve'})
        self.assertFalse(c['use_effects_tab']);self.assertFalse(c['use_transitions_tab']);self.assertEqual(c['transition'],'Cut')
        self.assertFalse(c['settings']['use_cloud_tts'])
    def test_no_editor_imports_or_tk_widgets_in_extracted_modules(self):
        forbidden={'youtube_video_automation_enhanced','complete_automation_gui','dubbing_tab','dubbing_engine','neutts_helper','qwen3_tts_helper','tkinter'}
        files=list(ROOT.glob('*.py'))+list((ROOT/'desktop').glob('*.py'))
        for file in files:
            for n in ast.walk(ast.parse(file.read_text('utf-8-sig'))):
                names=[a.name.split('.')[0] for a in n.names] if isinstance(n,ast.Import) else [(n.module or '').split('.')[0]] if isinstance(n,ast.ImportFrom) else []
                self.assertFalse(forbidden.intersection(names),f'{file.name}: {names}')
    def test_only_two_navigation_tabs_and_pro_caption_controls(self):
        text=(ROOT/'desktop/ui/app.js').read_text('utf-8-sig')
        self.assertIn("['studio'",text);self.assertIn("['animate'",text)
        self.assertNotIn("['quick'",text)
        specs=json.loads((ROOT/'desktop/ui/configuration.json').read_text('utf-8'))
        self.assertTrue(all(s.get('group')=='Pro Captions (ASS)' or s['key'] in {'caption_position','caption_font_size','caption_y_offset','caption_words_per_line','caption_layout','caption_sync_offset'} for s in specs['captions']))
    def test_local_backend_security_and_removed_endpoints(self):
        jobs=Mock();jobs.list.return_value=[]
        app=create_app(jobs=jobs,token='offline-test-token')
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/state').status_code,401)
            headers={'x-desktop-token':'offline-test-token'}
            self.assertEqual(client.get('/api/studio/metadata',headers=headers).status_code,200)
            self.assertEqual(client.get('/api/animate/metadata',headers=headers).status_code,200)
            self.assertEqual(client.post('/api/jobs',headers=headers,json={'kind':'quick','payload':{}}).status_code,400)
            self.assertEqual(client.post('/api/legacy',headers=headers,json={}).status_code,404)
            self.assertEqual(client.get('/api/state',headers={**headers,'origin':'https://foreign.invalid'}).status_code,403)
