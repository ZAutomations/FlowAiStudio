import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_studio_manual_batches import run


class ManualBatchTests(unittest.TestCase):
    def test_download_status_reports_gaps_instead_of_all_scenes_complete(self):
        from desktop.jobs import download_scan_message
        message=download_scan_message({'saved':104,'downloaded':0,'highest_saved_scene':130,'gaps':list(range(26)),'unmatched':533})
        self.assertIn('104 scene images saved',message)
        self.assertIn('26 unmatched gaps through scene 130',message)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.scenes=[{'narration':f'Clue {i}.','visual_prompt':f'A clue {i}.'} for i in range(45)]
        self.config=dict(project=str(self.root),provider='flow',flow_url='https://flow.google.com/project/example',
            title='Investigation',script='A village investigation.',style='Handpainted',resolution='1280x720',references=[],settings={})
        class Adapter:
            _zb_cancel=threading.Event()
            def _zb_save_project(self,c):pass
        self.adapter=Adapter();self.adapter.zb_scenes=self.scenes
        import queue
        self.q=queue.Queue()

    def test_export_and_three_downloads_keep_ids_without_any_submission(self):
        with patch('ai_studio_animate_media.AgentMedia') as browser:
            run(self.adapter,self.q,self.config)
            browser.assert_not_called()
        export=json.loads((self.root/'manual_batch_export.json').read_text('utf-8'))
        self.assertEqual([len(b['tokens']) for b in export['batches']],[20,20,5])
        folder=Path(export['directory'])
        self.assertTrue((folder/'all_batches.txt').exists())
        before=json.loads((self.root/'studio_manual_images.json').read_text('utf-8'))
        self.assertTrue(all(r['status']=='pending' for r in before['records']))
        calls=[]
        def collect(records,save,callback):
            self.assertIs(browser.return_value.available_only,True)
            calls.append([r['index'] for r in records])
            for r in reversed(records):
                Path(r['output']).parent.mkdir(exist_ok=True)
                Image.new('RGB',(32,32),'red').save(r['output'])
                r['status']='complete';save();callback(r)
        with patch('ai_studio_animate_media.AgentMedia') as browser, patch('ai_studio_animate_media.prepare_agent_prompt') as submit:
            browser.return_value.collect.side_effect=collect
            for _ in range(3):run(self.adapter,self.q,self.config,download=True)
            run(self.adapter,self.q,self.config,download=True)
            submit.assert_not_called()
        self.assertEqual(calls,[list(range(20)),list(range(20,40)),list(range(40,45))])
        self.assertTrue(all(s['manual_image'] for s in self.scenes))
        after=json.loads((self.root/'studio_manual_images.json').read_text('utf-8'))
        self.assertEqual([r['token'] for r in before['records']],[r['token'] for r in after['records']])

    def test_custom_export_batch_sizes(self):
        for size,expected in [(40,[40,5]),(50,[45]),(1,[1]*45)]:
            with self.subTest(size=size):
                run(self.adapter,self.q,{**self.config,'prompt_batch_size':size})
                data=json.loads((self.root/'manual_batch_export.json').read_text('utf-8'))
                self.assertEqual(data['batch_size'],size)
                self.assertEqual([len(b['tokens']) for b in data['batches']],expected)

    def test_invalid_export_batch_sizes(self):
        from ai_studio_manual_batches import export_batch_size
        for value in [0,-1,1.5,True,'abc','']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                export_batch_size({'prompt_batch_size':value})

    def test_different_flow_project_does_not_download(self):
        run(self.adapter,self.q,self.config)
        with patch('ai_studio_animate_media.AgentMedia') as browser:
            with self.assertRaisesRegex(ValueError,'different scene plan or Flow project'):
                run(self.adapter,self.q,{**self.config,'flow_url':'other'},download=True)
            browser.assert_not_called()

    def test_export_groups_twenty_remaining_scenes_after_partial_completion(self):
        run(self.adapter,self.q,self.config)
        file=self.root/'studio_manual_images.json'
        state=json.loads(file.read_text('utf-8'))
        for i in [0,2,4,6,8,10,12]:
            output=Path(state['records'][i]['output']);output.parent.mkdir(exist_ok=True)
            Image.new('RGB',(32,32),'blue').save(output)
        run(self.adapter,self.q,self.config)
        export=json.loads((self.root/'manual_batch_export.json').read_text('utf-8'))
        self.assertEqual([len(b['tokens']) for b in export['batches']],[20,18])
        seen=[]
        def collect(records,save,callback):
            seen.extend(r['token'] for r in records)
            for r in records:
                Image.new('RGB',(32,32),'red').save(r['output'])
                r['status']='complete';save();callback(r)
        with patch('ai_studio_animate_media.AgentMedia') as browser:
            browser.return_value.collect.side_effect=collect
            run(self.adapter,self.q,self.config,download=True)
        self.assertEqual(seen,export['batches'][0]['tokens'])

    def test_unusual_activity_is_not_quota(self):
        from zbot_browser_images import ZBotImageGenerator
        from unittest.mock import Mock
        page=Mock();page.locator.return_value.inner_text.return_value='We noticed some unusual activity.'
        error=ZBotImageGenerator('flow')._queued_error(page)
        self.assertIn('unusual-activity',error)
        self.assertNotIn('Account limit reached:',error)

    def test_each_file_lists_only_its_required_attachments_and_scene_mapping(self):
        from ai_studio_manual_batches import export_files
        from ai_studio_animate_media import media_plan
        config={**self.config,'image_agent':True,'animate_model':'Veo 3.1 - Lite',
            'references':[str(self.root/name) for name in ['DSP.png','IdrisMochi.jpg','Unused.png']],
            'scene_reference_map':[['DSP'] if i<20 else ['IdrisMochi'] for i in range(45)]}
        records=media_plan(self.scenes,config)
        export_files({'identity':'test','records':records},config,lambda message:None)
        data=json.loads((self.root/'manual_batch_export.json').read_text('utf-8'))
        folder=Path(data['directory'])
        first=(folder/data['batches'][0]['file']).read_text('utf-8')
        second=(folder/data['batches'][1]['file']).read_text('utf-8')
        self.assertIn('REQUIRED REFERENCE ATTACHMENTS FOR THIS BATCH:\n@DSP.png',first)
        self.assertIn('References for THIS scene only: @DSP.png',first)
        self.assertNotIn('@IdrisMochi.jpg',first)
        self.assertIn('References for THIS scene only: @IdrisMochi.jpg',second)
        self.assertNotIn('@DSP.png',second)
        self.assertNotIn('@Unused.png',first+second)

    def test_reference_edit_keeps_completed_files_and_submitted_tokens_on_export(self):
        from ai_studio_animate_media import generate_agent_media
        ref=self.root/'DSP.png';Image.new('RGB',(32,32),'red').save(ref)
        config={**self.config,'references':[str(ref)],'image_agent':True,'animate_model':'Veo 3.1 - Lite',
            '_export_batches':True,'scene_reference_map':[['DSP'] for _ in self.scenes]}
        generate_agent_media(self.scenes,config,threading.Event(),lambda message:None,lambda record:None)
        file=self.root/'studio_agent_images.json';before=json.loads(file.read_text('utf-8'))
        output=Path(before['records'][0]['output']);output.parent.mkdir(exist_ok=True)
        Image.new('RGB',(32,32),'green').save(output);pixels=output.read_bytes()
        before['records'][0]['status']='complete'
        before['records'][1]['status']='submitted';before['records'][1]['asset_id']='existing-asset'
        before['account_binding']={'account':'retained','flow_url':config['flow_url']}
        from ai_studio_pipeline import atomic_json
        atomic_json(file,before)
        Image.new('RGB',(32,32),'blue').save(ref)
        with patch('ai_studio_animate_media.AgentMedia') as browser:
            generate_agent_media(self.scenes,config,threading.Event(),lambda message:None,lambda record:None)
            browser.assert_not_called()
        after=json.loads(file.read_text('utf-8'))
        self.assertEqual(output.read_bytes(),pixels)
        self.assertEqual([r['token'] for r in before['records']],[r['token'] for r in after['records']])
        self.assertEqual(after['records'][0]['status'],'complete')
        self.assertEqual(after['records'][1]['status'],'submitted')
        self.assertEqual(after['records'][1]['asset_id'],'existing-asset')
        self.assertEqual(after['account_binding'],before['account_binding'])
        self.assertNotEqual(after['identity'],before['identity'])
        self.assertTrue((self.root/'animate_plan_history'/f'{before["identity"]}.json').exists())

    def test_download_all_skips_existing_and_collects_across_batches(self):
        from ai_studio_manual_batches import download_all
        run(self.adapter,self.q,self.config)
        file=self.root/'studio_manual_images.json';before=json.loads(file.read_text('utf-8'))
        first=Path(before['records'][0]['output']);first.parent.mkdir(exist_ok=True)
        Image.new('RGB',(32,32),'blue').save(first);saved=first.read_bytes()
        seen=[]
        def collect(records,save,callback,timeout):
            seen.extend(r['index'] for r in records)
            for r in reversed(records):
                if r['index'] not in (2,23,44):continue
                Image.new('RGB',(32,32),'red').save(r['output'])
                r['status']='complete';save();callback(r)
        with patch('ai_studio_animate_media.AgentMedia') as browser,patch('ai_studio_animate_media.prepare_agent_prompt') as submit:
            browser.return_value.collect.side_effect=collect
            download_all(self.adapter,self.q,self.config)
            self.assertTrue(browser.return_value.available_only)
            submit.assert_not_called()
        self.assertEqual(seen,list(range(1,45)))
        self.assertEqual(first.read_bytes(),saved)
        after=json.loads(file.read_text('utf-8'))
        self.assertEqual([r['index'] for r in after['records'] if r['status']=='complete'],[0,2,23,44])
        self.assertTrue(self.scenes[44]['manual_image'])
        self.assertTrue(self.scenes[44]['image_path'].endswith('scene_0045.png'))

    def test_start_scene_export_preserves_global_scene_numbers(self):
        run(self.adapter,self.q,{**self.config,'scene_start':21,'scene_end':40})
        data=json.loads((self.root/'manual_batch_export.json').read_text('utf-8'))
        self.assertEqual(len(data['batches']),1)
        self.assertEqual(data['batches'][0]['scenes'],list(range(21,41)))
        text=(Path(data['directory'])/data['batches'][0]['file']).read_text('utf-8')
        self.assertIn('OUTPUT 0021',text);self.assertNotIn('OUTPUT 0001',text)

    def test_generation_start_does_not_regenerate_deleted_earlier_scenes(self):
        from ai_studio_animate_media import generate_agent_media
        from test_animate_full import FullAnimateTests
        prepared=[];submitted=[];delivered=[]
        config={**self.config,'scene_start':21,'scene_end':40,'image_agent':True,
            'animate_model':'Veo 3.1 - Lite','image_batch_size':20}
        with patch('ai_studio_animate_media.AgentMedia',FullAnimateTests().fake_agent(prepared,submitted)),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda config,path,*args:prepared.append(Path(path).read_text('utf-8'))):
            generate_agent_media(self.scenes,config,threading.Event(),lambda message:None,delivered.append)
        self.assertEqual([r['index'] for r in delivered],list(range(20,40)))
        self.assertFalse((self.root/'images/scene_0001.png').exists())
        state=json.loads((self.root/'studio_agent_images.json').read_text('utf-8'))
        self.assertTrue(all(r['status']=='pending' for r in state['records'][:20]))

    def test_exported_unsent_batch_verifies_download_only_before_automatic_submit(self):
        from ai_studio_animate_media import generate_agent_media
        from test_animate_full import FullAnimateTests
        config={**self.config,'image_agent':True,'animate_model':'Veo 3.1 - Lite',
            'image_batch_size':20,'scene_start':21,'scene_end':40}
        generate_agent_media(self.scenes,{**config,'_export_batches':True},threading.Event(),lambda m:None,lambda r:None)
        prepared=[];submitted=[];checks=[];delivered=[]
        base=FullAnimateTests().fake_agent(prepared,submitted)
        class Agent(base):
            def collect(self,records,save,on_media):
                checks.append(self.available_only)
                if self.available_only:return # completed scan found no matching existing outputs
                return super().collect(records,save,on_media)
        with patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda c,p,*args:prepared.append(Path(p).read_text('utf-8'))):
            generate_agent_media(self.scenes,config,threading.Event(),lambda m:None,delivered.append)
        self.assertEqual(checks,[True,False])
        self.assertEqual(len(submitted),1)
        self.assertEqual([r['index'] for r in delivered],list(range(20,40)))


if __name__=='__main__':unittest.main()
