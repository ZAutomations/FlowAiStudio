"""Offline model fallback and quota reconciliation; no browser submissions."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from ai_studio_image_models import IMAGE_MODELS, preferred, quota_model, ModelQuotaExhausted
from ai_studio_animate_media import generate_agent_media


class ImageModelTests(unittest.TestCase):
    def test_each_batch_has_order_and_only_missing_output_contract(self):
        from ai_studio_animate_media import batch_prompt
        record={'index':0,'kind':'image','token':'AS_SCENE_test','prompt':'A village.'}
        for model in IMAGE_MODELS:
            prompt=batch_prompt([record],{'image_agent':True,'agent_image_model':model,'animate_model':'Veo 3.1 - Lite'})
            self.assertIn('Nano Banana Pro → Nano Banana 2.1 → Nano Banana 2 Lite',prompt)
            self.assertIn('Start this batch with '+model,prompt)
            self.assertIn('outputs still missing from THIS batch',prompt)
            self.assertIn('Do not switch accounts.',prompt)
            self.assertIn('propose a materially safer, non-graphic visual',prompt)
            self.assertIn('keep the narration unchanged',prompt)
            self.assertIn('wait for user review',prompt)
            self.assertIn('Do not automatically submit the alternative',prompt)
        prompt=batch_prompt([record],{'image_agent':True,'agent_image_fallback':False,'animate_model':'Veo 3.1 - Lite'})
        self.assertIn('Do not switch models or accounts.',prompt)
        self.assertNotIn('automatically continue',prompt)
        self.assertIn('propose a materially safer, non-graphic visual',prompt)
    def test_explicit_model_quota_not_suggested_alternatives(self):
        text='The daily quota for 🍌 Nano Banana Pro has been reached. Try Nano Banana 2 Lite or Nano Banana 2.1?'
        self.assertEqual(quota_model(text),IMAGE_MODELS[0])
        self.assertEqual(quota_model('Nano Banana 2.1 daily quota has been exhausted.'),IMAGE_MODELS[1])
        self.assertIsNone(quota_model('Attachment failed. Try Nano Banana 2.1.'))
        self.assertIsNone(quota_model('Account usage limit reached.'))
        with self.assertRaises(ValueError):preferred({'agent_image_model':'Unknown'})

    def test_exhausted_models_and_landscape_are_in_next_batch_instructions(self):
        from ai_studio_animate_media import batch_prompt
        record={'index':0,'kind':'image','token':'AS_SCENE_test','prompt':'A modern room.'}
        c={'image_agent':True,'agent_image_model':IMAGE_MODELS[1],'exhausted_image_models':[IMAGE_MODELS[0]],'animate_model':'Veo 3.1 - Lite'}
        prompt=batch_prompt([record],c)
        self.assertIn('Skip these models in this and every later batch',prompt)
        self.assertIn('Start this batch with Nano Banana 2.1',prompt)
        self.assertIn('All images MUST be 16:9 landscape',prompt)
        portrait=batch_prompt([record],{**c,'aspect':'9:16'})
        self.assertNotIn('All images MUST be 16:9 landscape',portrait)
        self.assertIn('This aspect ratio was explicitly selected',portrait)

    def test_agent_internal_fallback_is_remembered_for_next_batch(self):
        from test_animate_full import FullAnimateTests
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root=Path(folder);scenes=[{'narration':f'Clue {i}'} for i in range(3)]
            c={'project':folder,'resolution':'320x180','aspect':'16:9','style':'Cartoon','references':[],
                'image_agent':True,'image_batch_size':2,'animate_model':'Veo 3.1 - Lite','flow_url':'https://flow.google.com/project/test'}
            prepared=[];submitted=[];models=[]
            fake=FullAnimateTests().fake_agent(prepared,submitted);original=fake.collect
            def collect(agent,records,save,media):
                models.append(agent.agent_image_model)
                original(agent,records,save,media)
                agent.completed_reported_quotas=(IMAGE_MODELS[0],)
            fake.collect=collect
            with patch('ai_studio_animate_media.AgentMedia',fake),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda c,p,*args:prepared.append(Path(p).read_text('utf-8'))):
                generate_agent_media(scenes,c,threading.Event(),lambda m:None,lambda r:None)
            self.assertEqual(models,[IMAGE_MODELS[0],IMAGE_MODELS[1]])
            state=json.loads((root/'studio_agent_images.json').read_text('utf-8'))
            self.assertEqual(state['exhausted_image_models'],[IMAGE_MODELS[0]])
            self.assertIn('Skip these models in this and every later batch',submitted[-1])

    def run_case(self,always_quota=False,fallback=True):
        tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);scenes=[{'narration':f'Clue {i}'} for i in range(3)]
        config={'project':str(root),'resolution':'320x180','aspect':'16:9','style':'Cartoon','references':[],
                'image_agent':True,'image_batch_size':3,'animate_model':'Veo 3.1 - Lite','flow_url':'https://flow.google.com/project/test',
                'agent_image_fallback':fallback}
        prepared=[];submitted=[];models=[];delivered=[]
        from test_animate_full import FullAnimateTests
        fake=FullAnimateTests().fake_agent(prepared,submitted);original=fake.collect
        def collect(agent,records,save,on_media):
            model=agent.agent_image_model;models.append(model)
            if always_quota or model==IMAGE_MODELS[0]:
                # First scene succeeded before quota. Never submit it again.
                if records[0]['index']==0:original(agent,records[:1],save,on_media)
                raise ModelQuotaExhausted(model)
            return original(agent,records,save,on_media)
        fake.collect=collect
        def prepare(cfg,file,*args):prepared.append(Path(file).read_text('utf-8'))
        with patch('ai_studio_animate_media.AgentMedia',fake),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=prepare):
            if always_quota or not fallback:
                with self.assertRaisesRegex(RuntimeError,'quota'):
                    generate_agent_media(scenes,config,threading.Event(),lambda m:None,delivered.append)
            else:
                generate_agent_media(scenes,config,threading.Event(),lambda m:None,delivered.append)
                # Simulate restart: one missing local output must use persisted 2.1.
                state=json.loads((root/'studio_agent_images.json').read_text('utf-8'))
                Path(state['records'][-1]['output']).unlink()
                generate_agent_media(scenes,config,threading.Event(),lambda m:None,delivered.append)
        return submitted,models,json.loads((root/'studio_agent_images.json').read_text('utf-8'))

    def test_fallback_preserves_outputs_and_remembers_model_on_restart(self):
        submitted,models,state=self.run_case()
        self.assertEqual(models,[IMAGE_MODELS[0],IMAGE_MODELS[1],IMAGE_MODELS[1]])
        self.assertEqual(len(submitted),2)
        self.assertIn('using Nano Banana 2.1.',submitted[1])
        self.assertNotIn('OUTPUT 0001',submitted[1])
        self.assertEqual(state['active_image_model'],IMAGE_MODELS[1])
        self.assertEqual(state['exhausted_image_models'],[IMAGE_MODELS[0]])
        self.assertTrue(all(r['status']=='complete' for r in state['records']))

    def test_all_models_exhausted_is_bounded_and_keeps_completed_image(self):
        submitted,models,state=self.run_case(always_quota=True)
        self.assertEqual(models,list(IMAGE_MODELS));self.assertEqual(len(submitted),3)
        self.assertEqual(state['records'][0]['status'],'complete')
        self.assertEqual(state['exhausted_image_models'],list(IMAGE_MODELS))

    def test_disabled_fallback_never_switches(self):
        submitted,models,state=self.run_case(fallback=False)
        self.assertEqual(models,[IMAGE_MODELS[0]]);self.assertEqual(len(submitted),1)

    def test_collector_scans_and_waits_for_idle_before_quota_handover(self):
        from test_agent_collection import AgentCollectionTests
        fixture=AgentCollectionTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        agent=fixture.agent;agent.agent_image_fallback=True;agent.agent_image_model=IMAGE_MODELS[0]
        agent._queued_error=Mock(return_value='Account limit reached: daily limit')
        agent._agent_batch_reply=Mock(return_value='Daily quota for Nano Banana Pro has been reached.')
        fixture.page.locator.return_value.inner_text.return_value='Daily quota for Nano Banana Pro has been reached.'
        fixture.page.locator.return_value.last.inner_text.return_value='Daily quota for Nano Banana Pro has been reached.'
        agent._agent_assets=Mock(return_value=[{**fixture.asset(0),'failed':True}])
        fixture.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'unidentified':False}
        clock=iter(range(0,5000,30))
        with patch('ai_studio_animate_media.time.monotonic',side_effect=lambda:next(clock)),patch('ai_studio_animate_media.time.sleep'):
            with self.assertRaises(ModelQuotaExhausted):agent.collect(fixture.records,lambda:None,lambda r:None)
        self.assertGreaterEqual(fixture.page.mouse.wheel.call_count,1)


if __name__=='__main__':unittest.main()
