import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_studio_manual_references import run

class ManualReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config={'project':str(self.root),'style_name':'Punjab DSP Handpantend ColorMix','style':'Hand-painted colorful historical Punjab.',
            'flow_url':'https://flow.google.com/project/example','cast_assets':[{'name':'DSPMalik','kind':'character','description':'Officer'},
            {'name':'Witness','kind':'character','description':'Farmer'},{'name':'PoliceStation','kind':'location','description':'Village station'}]}
        self.cancel=threading.Event()
    def test_export_is_offline_with_style_and_exact_reference_labels(self):
        with patch('ai_studio_animate_media.AgentMedia') as browser:
            run(self.config,self.cancel,lambda m:None)
            browser.assert_not_called()
        text=(self.root/'characters_and_locations_prompts.txt').read_text('utf-8')
        self.assertIn(self.config['style'],text);self.assertIn(self.config['style_name'],text)
        for name in ('DSPMalik','Witness','PoliceStation'):self.assertIn(name+'.png',text)
        state=json.loads((self.root/'manual_reference_images.json').read_text('utf-8'))
        self.assertEqual(len({r['token'] for r in state['records']}),3)
        self.assertTrue(all(r['token'] in text for r in state['records']))
    def test_fixed_dsp_is_not_in_generation_prompts(self):
        source=self.root/'master.png';Image.new('RGB',(512,512),'yellow').save(source)
        run({**self.config,'dsp_malik_reference_path':str(source)},self.cancel,lambda m:None)
        state=json.loads((self.root/'manual_reference_images.json').read_text('utf-8'))
        self.assertEqual(state['records'][0]['status'],'complete')
        text=(self.root/'characters_and_locations_prompts.txt').read_text('utf-8')
        self.assertNotIn(state['records'][0]['token'],text)
        self.assertTrue((self.root/'references/DSPMalik.png').exists())
    def test_download_renames_by_identity_skips_existing_and_never_submits(self):
        run(self.config,self.cancel,lambda m:None)
        def collect(records,save,callback,timeout):
            self.assertTrue(browser.return_value.available_only)
            self.assertTrue(browser.return_value.reference_collection)
            for r in reversed(records):
                Image.new('RGB',(512,512),'blue').save(r['output']);r['status']='complete';save();callback(r)
        with patch('ai_studio_animate_media.AgentMedia') as browser,patch('ai_studio_animate_media.prepare_agent_prompt') as submit:
            browser.return_value.collect.side_effect=collect
            files=run(self.config,self.cancel,lambda m:None,download=True)
            self.assertEqual([Path(p).name for p in files],['DSPMalik.png','Witness.png','PoliceStation.png'])
            run(self.config,self.cancel,lambda m:None,download=True)
            browser.return_value.collect.assert_called_once();submit.assert_not_called()
    def test_project_change_keeps_existing_export(self):
        run(self.config,self.cancel,lambda m:None)
        with self.assertRaises(ValueError):run({**self.config,'flow_url':'https://flow.google.com/project/other'},self.cancel,lambda m:None,download=True)
