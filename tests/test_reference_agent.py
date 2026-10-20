import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_studio_reference_agent import generate

class ReferenceAgentTests(unittest.TestCase):
    def test_one_agent_prompt_for_missing_identities_saved_files_skipped_and_retry_reused(self):
        from test_animate_full import FullAnimateTests
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);refs=[dict(name=n,kind='character',prompt='Fixed identity '+n,output=str(root/(n+'.png'))) for n in ['DSP','Ali','Mother']]
            Image.new('RGB',(512,512),'red').save(refs[0]['output']);original=Path(refs[0]['output']).read_bytes()
            config=dict(project=tmp,flow_url='https://flow.google.com/project/test',style='Handpainted',script='A long story.',agent_tool_dir='unused',scene_start=100,scene_end=150)
            prepared=[];submitted=[];base=FullAnimateTests().fake_agent(prepared,submitted)
            class Agent(base):
                def collect(agent,records,save,on_media):
                    self.assertTrue(agent.reference_collection)
                    for record in records:
                        Image.new('RGB',(512,288),'blue').save(record['output']);record['status']='complete';save();on_media(record)
            def prepare(cfg,path,refs,*args):
                self.assertEqual(cfg['aspect'],'16:9');self.assertTrue(cfg['image_agent']);self.assertEqual(refs,[])
                prepared.append(Path(path).read_text('utf-8'))
            with patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=prepare):
                generate(config,refs,threading.Event(),lambda m:None)
                self.assertEqual(len(submitted),1)
                self.assertNotIn('Fixed identity DSP',submitted[0]);self.assertIn('Fixed identity Ali',submitted[0]);self.assertIn('Fixed identity Mother',submitted[0])
                self.assertIn('Nano Banana Pro',submitted[0]);self.assertIn('Nano Banana 2.1',submitted[0]);self.assertIn('Nano Banana 2 Lite',submitted[0])
                self.assertIn('number_of_images=1',submitted[0]);self.assertIn('16:9',submitted[0])
                generate(config,refs,threading.Event(),lambda m:None)
                self.assertEqual(len(submitted),1)
            self.assertEqual(Path(refs[0]['output']).read_bytes(),original)
            self.assertTrue((root/'reference_agent_media.json').is_file());self.assertFalse((root/'animate_media.json').exists())

if __name__=='__main__':unittest.main()
