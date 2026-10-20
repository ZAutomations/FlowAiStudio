"""Adopt copied image files without trusting another project's checkpoints."""
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_studio_animate_setup import ensure_references,reference_plan
from ai_studio_pipeline import atomic_json,fingerprint


class CopiedReferencePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'new';self.root.mkdir();(self.root/'images').mkdir()
        self.config=dict(project=str(self.root),image_agent=True,auto_reference=True,reference_mode='characters',
                         cast_assets=[dict(name='DSP',kind='character',description='Officer.')],style='Handpainted',continuity='',flow_url='new-project')
        self.refs=reference_plan(self.config);self.directory=self.root/'references';self.directory.mkdir()
        Image.new('RGB',(32,32),'red').save(self.directory/'DSP.png')
        self.foreign={'identity':'../../untrusted','references':[dict(name='OldDSP',kind='character',prompt='Old design',output=str(self.root.parent/'old/references/OldDSP.png'))]}
        atomic_json(self.directory/'reference_plan.json',self.foreign)
        atomic_json(self.directory/'image_batches.json',{'foreign_queue':True})

    def test_foreign_metadata_archived_and_exact_named_images_reused(self):
        before=(self.directory/'DSP.png').read_bytes();logs=[]
        with patch('ai_studio_animate_setup.ZBotImageGenerator') as browser:
            refs=ensure_references(self.config,threading.Event(),logs.append)
            browser.assert_not_called()
        self.assertEqual(refs,[str(self.directory/'DSP.png')])
        self.assertEqual((self.directory/'DSP.png').read_bytes(),before)
        state=json.loads((self.directory/'reference_plan.json').read_text('utf-8'))
        self.assertEqual(state['identity'],fingerprint([(r['name'],r['kind'],r['prompt']) for r in self.refs],'new-project'))
        self.assertFalse((self.directory/'image_batches.json').exists())
        backup=self.directory/'plan_history'/fingerprint(self.foreign)
        self.assertEqual(json.loads((backup/'reference_plan.json').read_text()),self.foreign)
        self.assertTrue((backup/'image_batches.json').exists())
        self.assertIn('copied from another project',logs[0])

    def test_foreign_plan_is_not_adopted_after_scene_requests_or_images_exist(self):
        for name in ('studio_agent_images.json','animate_media.json','images/image_batches.json','images/scene_0001.png'):
            with self.subTest(name=name):
                marker=self.root/name;marker.parent.mkdir(exist_ok=True)
                if marker.suffix=='.png':Image.new('RGB',(32,32)).save(marker)
                else:atomic_json(marker,{})
                original=(self.directory/'reference_plan.json').read_bytes()
                with self.assertRaisesRegex(RuntimeError,'scene generation already started'):ensure_references(self.config,threading.Event(),lambda m:None)
                self.assertEqual((self.directory/'reference_plan.json').read_bytes(),original)
                marker.unlink()

    def test_same_project_design_change_still_requires_review(self):
        original={**self.foreign,'references':[dict(self.refs[0],prompt='Different description')]}
        atomic_json(self.directory/'reference_plan.json',original)
        with self.assertRaisesRegex(RuntimeError,'different design'):ensure_references(self.config,threading.Event(),lambda m:None)
        self.assertEqual(json.loads((self.directory/'reference_plan.json').read_text()),original)

    def test_missing_reference_generation_does_not_resubmit_existing_files(self):
        config={**self.config,'agent_tool_dir':str(self.root),'cast_assets':self.config['cast_assets']+[dict(name='Station',kind='location',description='Brick station.')]}
        before=(self.directory/'DSP.png').read_bytes()
        def generate(config,items,cancel,log):
            pending=[r for r in items if not Path(r['output']).exists()]
            self.assertEqual(len(pending),1);self.assertEqual(Path(pending[0]['output']).name,'Station.png')
            Image.new('RGB',(512,288),'blue').save(pending[0]['output'])
        with patch('ai_studio_reference_agent.generate',side_effect=generate):
            refs=ensure_references(config,threading.Event(),lambda m:None)
        self.assertEqual(len(refs),2)
        self.assertEqual((self.directory/'DSP.png').read_bytes(),before)


if __name__=='__main__':unittest.main()
