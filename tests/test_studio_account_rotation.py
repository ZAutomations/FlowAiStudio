"""Offline account handover fixtures; never signs in or submits generation."""
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image
from ai_studio_pipeline import atomic_json,fingerprint
from ai_studio_account_rotation import account_order,handover,restore,select_account


class AccountRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.account='a'*32;self.other='b'*32
        self.profiles=[{'id':self.account,'label':'Second','port':9300},{'id':self.other,'label':'Third','port':9303}]
        self.config={'project':str(self.root),'provider':'flow','image_agent':True,'account_fallback':True,
                     'account_fallback_order':'Second, Third','flow_url':'https://flow.google.com/project/original','browser_account':''}
        self.file=self.root/'studio_agent_images.json'
        output=self.root/'images/scene_0001.png';output.parent.mkdir();Image.new('RGB',(32,32),'red').save(output)
        self.original=output.read_bytes()
        self.records=[{'index':0,'key':'one','token':'AS_SCENE_one','status':'complete','asset_id':'original-asset','output':str(output)},
                      {'index':1,'key':'two','token':'AS_SCENE_two','status':'submitted','preparation_started':True,'output':str(output.with_name('scene_0002.png'))},
                      {'index':2,'key':'three','token':'AS_SCENE_three','status':'pending','output':str(output.with_name('scene_0003.png'))}]
        self.state={'identity':fingerprint([(r['key'],r['index']) for r in self.records],self.config['flow_url']),
                    'records':self.records,'preferred_image_model':'Nano Banana Pro','active_image_model':'Nano Banana 2 Lite',
                    'exhausted_image_models':['Nano Banana Pro','Nano Banana 2.1','Nano Banana 2 Lite'],'quota_verified_missing':[1]}
        atomic_json(self.file,self.state)
        self.patch=patch('ai_studio_account_rotation.profiles',return_value=self.profiles);self.patch.start();self.addCleanup(self.patch.stop)
        self.options=patch('ai_studio_account_rotation.browser_options',return_value={'profile_dir':self.root,'cdp_port':9300});self.options.start();self.addCleanup(self.options.stop)
    def read(self):return json.loads(self.file.read_text('utf-8'))
    def switch(self):
        with patch('ai_studio_animate_setup.ensure_project',return_value='https://flow.google.com/project/second') as project:
            handover(self.config,threading.Event(),lambda m:None)
            return project
    def test_order_validation_and_deduplication(self):
        self.assertEqual(account_order(self.config),[self.account,self.other])
        self.assertEqual(account_order({**self.config,'account_fallback_order':'second, '+self.account}),[self.account])
        with self.assertRaisesRegex(ValueError,'Unknown fallback'):account_order({**self.config,'account_fallback_order':'unknown'})
    def test_explicit_account_selection_preserves_local_images_and_archives_pending_ids(self):
        (self.root/'profile_gemini').mkdir()
        queue=self.root/'references/image_batches.json'
        atomic_json(queue,{'browser_account':'','requests':[{'token':'old-reference-id'}]})
        selected={**self.config,'browser_account':self.account,'character_consistency':True,'share_google_profile':True}
        with patch('ai_studio_animate_setup.ensure_project',return_value='https://flow.google.com/project/second') as project:
            select_account(selected,self.config,threading.Event(),lambda m:None)
        self.assertTrue(project.call_args.args[0]['_rotation_scope'])
        self.assertEqual(project.call_args.args[0]['flow_url'],'')
        self.assertEqual(Path(self.records[0]['output']).read_bytes(),self.original)
        state=self.read()
        self.assertEqual(state['account_binding']['account'],self.account)
        self.assertEqual(state['records'][1]['status'],'pending')
        self.assertEqual(state['reference_flow_url'],self.config['flow_url'])
        archive=next((self.root/'account_history').glob('*/studio_agent_images.json'))
        self.assertEqual(json.loads(archive.read_text())['records'][1]['status'],'submitted')
        self.assertFalse(queue.exists())
        self.assertTrue((archive.parent/'references/image_batches.json').exists())
        # Crash after binding commit but before project options save is recoverable.
        with patch('ai_studio_animate_setup.ensure_project') as project:
            select_account(selected,self.config,threading.Event(),lambda m:None)
            project.assert_not_called()
    def test_manual_selection_works_before_any_scene_batch_exists(self):
        self.file.unlink();(self.root/'profile_gemini').mkdir()
        selected={**self.config,'browser_account':self.account,'character_consistency':True}
        with patch('ai_studio_animate_setup.ensure_project',return_value='https://flow.google.com/project/second'):
            select_account(selected,self.config,threading.Event(),lambda m:None)
        self.assertEqual(selected['_reference_flow_url'],self.config['flow_url'])
        self.assertTrue(selected['_rotation_scope'])
        self.assertFalse(self.file.exists())
    def test_manual_account_without_saved_login_does_not_change_checkpoints(self):
        before=self.file.read_bytes()
        with patch('ai_studio_animate_setup.ensure_project') as project:
            with self.assertRaisesRegex(ValueError,'Login first'):
                select_account({**self.config,'browser_account':self.account,'character_consistency':True},self.config,threading.Event(),lambda m:None)
            project.assert_not_called()
        self.assertEqual(self.file.read_bytes(),before)
    def test_quota_handover_preserves_images_and_tracking_and_restores_stale_job(self):
        self.switch();state=self.read()
        self.assertEqual(Path(self.records[0]['output']).read_bytes(),self.original)
        self.assertEqual([r['token'] for r in state['records']],[r['token'] for r in self.records])
        self.assertEqual(state['records'][0]['status'],'complete')
        self.assertEqual(state['records'][1]['status'],'pending')
        self.assertTrue(state['records'][1]['handover_unsubmitted'])
        self.assertNotIn('preparation_started',state['records'][1])
        self.assertEqual(state['active_image_model'],'Nano Banana Pro')
        self.assertTrue(list((self.root/'account_history').glob('*.json')))
        stale={**self.config,'browser_account':'','flow_url':'old'};restore(stale)
        self.assertEqual(stale['browser_account'],self.account)
        self.assertEqual(stale['flow_url'],'https://flow.google.com/project/second')
        self.assertEqual(stale['_reference_flow_url'],'https://flow.google.com/project/original')
    def test_unknown_account_cannot_adopt_existing_checkpoint(self):
        self.switch()
        with self.assertRaisesRegex(ValueError,'original or active'):restore({**self.config,'browser_account':'c'*32})
    def test_other_uncertain_requests_block_handover(self):
        self.state['records'][2].update(status='pending',preparation_started=True);atomic_json(self.file,self.state)
        before=self.file.read_bytes()
        with patch('ai_studio_animate_setup.ensure_project') as project:
            with self.assertRaisesRegex(RuntimeError,'uncertain'):handover(self.config,threading.Event(),lambda m:None)
            project.assert_not_called()
        self.assertEqual(self.file.read_bytes(),before)
    def test_creation_failure_preserves_original_binding_and_progress(self):
        before=self.file.read_bytes()
        with patch('ai_studio_animate_setup.ensure_project',side_effect=RuntimeError('Sign in required')):
            with self.assertRaisesRegex(RuntimeError,'Sign in'):handover(self.config,threading.Event(),lambda m:None)
        self.assertEqual(self.file.read_bytes(),before)
        self.assertEqual(self.config['browser_account'],'')
    def test_exhausted_accounts_do_not_cycle(self):
        self.state['account_sessions']=[{'account':self.account,'status':'quota_exhausted'},{'account':self.other,'status':'quota_exhausted'}]
        atomic_json(self.file,self.state)
        with patch('ai_studio_animate_setup.ensure_project') as project:
            with self.assertRaisesRegex(RuntimeError,'All selected fallback'):handover(self.config,threading.Event(),lambda m:None)
            project.assert_not_called()
    def test_no_handover_without_verified_quota_or_opt_in(self):
        for enabled,verified in [(False,[1]),(True,[])]:
            self.state['quota_verified_missing']=verified;atomic_json(self.file,self.state)
            with patch('ai_studio_animate_setup.ensure_project') as project:
                with self.assertRaises(RuntimeError):handover({**self.config,'account_fallback':enabled},threading.Event(),lambda m:None)
                project.assert_not_called()

    def test_reference_checkpoint_remains_bound_to_original_project(self):
        from ai_studio_animate_setup import ensure_references,reference_plan
        config={**self.config,'auto_reference':True,'reference_mode':'characters','style':'Cartoon',
                'continuity':'','cast_assets':[{'name':'DSP','kind':'character','description':'Officer in khaki.'}],
                'reference_descriptions':{'DSP':'Officer in khaki.'}}
        refs=reference_plan(config)
        file=self.root/'references/reference_plan.json'
        atomic_json(file,{'identity':fingerprint([(r['name'],r['kind'],r['prompt']) for r in refs],config['flow_url']),'references':refs})
        for ref in refs:
            Path(ref['output']).parent.mkdir(exist_ok=True);Image.new('RGB',(32,32)).save(ref['output'])
        with patch('ai_studio_animate_setup.ZBotImageGenerator') as generator:
            result=ensure_references({**config,'flow_url':'next-account-project','_reference_flow_url':config['flow_url']},threading.Event(),lambda m:None)
            generator.assert_not_called();self.assertEqual(result,[r['output'] for r in refs])

    def test_adapter_switches_only_on_typed_all_model_quota_failure(self):
        from ai_studio_consistency import generate
        from ai_studio_image_models import ImageModelsExhausted
        adapter=Mock();adapter.zb_scenes=[{'narration':'A village.'}];adapter._zb_cancel=threading.Event()
        config={**self.config,'auto_cast':False,'resolution':'1280x720','title':'Story','script':'A village.'}
        with patch('ai_studio_animate_setup.ensure_references',return_value=['DSP.png']),patch('ai_studio_animate_media.generate_agent_media',side_effect=[ImageModelsExhausted('quota'),None]) as media,patch('ai_studio_account_rotation.handover') as change:
            change.side_effect=lambda cfg,*args:cfg.update(browser_account=self.account,flow_url='new-project')
            generate(adapter,Mock(),config)
            change.assert_called_once();self.assertEqual(media.call_count,2)
            self.assertEqual(media.call_args.args[1]['browser_account'],self.account)
        for error in (RuntimeError('Flow rejected scene'),RuntimeError('Download failed')):
            with patch('ai_studio_animate_setup.ensure_references',return_value=['DSP.png']),patch('ai_studio_animate_media.generate_agent_media',side_effect=error),patch('ai_studio_account_rotation.handover') as change:
                with self.assertRaises(RuntimeError):generate(adapter,Mock(),config)
                change.assert_not_called()

    def test_scoped_project_checkpoint_reused_without_creating_another(self):
        from ai_studio_animate_setup import ensure_project
        config={**self.config,'browser_account':self.account,'_rotation_scope':True}
        atomic_json(self.root/'flow_accounts'/self.account/'flow_project.json',{'url':'saved-account-project','status':'ready'})
        with patch('ai_studio_animate_setup.ZBotImageGenerator') as browser:
            self.assertEqual(ensure_project(config,threading.Event(),lambda m:None),'saved-account-project')
            browser.assert_not_called()

    def test_full_model_chain_then_next_account_generates_only_unfinished_scenes(self):
        from ai_studio_consistency import generate
        from ai_studio_image_models import ModelQuotaExhausted,IMAGE_MODELS
        from test_animate_full import FullAnimateTests
        self.file.unlink()
        adapter=Mock();adapter.zb_scenes=[{'narration':f'Clue {i}'} for i in range(3)];adapter._zb_cancel=threading.Event()
        config={**self.config,'auto_cast':False,'character_consistency':True,'resolution':'1280x720','style':'Cartoon',
                'title':'Story','script':'A village.','image_batch_size':3,'continuity':''}
        prepared=[];submitted=[];seen=[]
        base=FullAnimateTests().fake_agent(prepared,submitted);original=base.collect
        class Agent(base):
            def __init__(agent,*args,**kwargs):
                super().__init__(*args,**kwargs)
                agent.url=kwargs['flow_project_url']
            def collect(agent,records,save,on_media):
                seen.append((agent.url,agent.agent_image_model))
                if agent.url.endswith('/original'):
                    if records[0]['index']==0:original(agent,records[:1],save,on_media)
                    raise ModelQuotaExhausted(agent.agent_image_model)
                return original(agent,records,save,on_media)
        with patch('desktop.browser_accounts.browser_options',return_value={}),patch('ai_studio_animate_setup.ensure_references',return_value=[]),patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda c,p,*args:prepared.append(Path(p).read_text('utf-8'))),patch('ai_studio_animate_setup.ensure_project',return_value='https://flow.google.com/project/second'):
            generate(adapter,Mock(),config)
        self.assertEqual([model for url,model in seen[:3]],list(IMAGE_MODELS))
        self.assertEqual(seen[-1],('https://flow.google.com/project/second','Nano Banana Pro'))
        self.assertEqual(len(submitted),4)
        for prompt in submitted[1:]:self.assertNotIn('OUTPUT 0001',prompt)
        self.assertTrue(all(r['status']=='complete' for r in self.read()['records']))
        self.assertEqual(config['browser_account'],self.account)


if __name__=='__main__':unittest.main()
