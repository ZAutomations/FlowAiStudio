"""Offline collection fixtures: no browser or generation service."""
import json, tempfile, threading, unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from ai_studio_animate_media import AgentMedia, MissingAgentOutputs

class AgentCollectionTests(unittest.TestCase):
    def setUp(self):
        self.inventory_patch=patch('ai_studio_flow_inventory.read_project_images',return_value=[])
        self.inventory_mock=self.inventory_patch.start();self.addCleanup(self.inventory_patch.stop)
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.root=Path(self.temp.name)
        self.records=[{'index':i,'token':f'AS_SCENE_{i:020x}','kind':'video','status':'submitted',
                       'output':str(self.root/'videos'/f'scene_{i+1:04d}.mp4')} for i in range(2)]
        self.page=Mock();self.page.evaluate.return_value=None
        @contextmanager
        def session(**kwargs):yield None
        self.agent=AgentMedia('flow',cancel=threading.Event(),log=lambda *a:None)
        self.agent._session=session;self.agent._batch_page=Mock(return_value=self.page)
        self.agent._scene_grid_position=Mock(return_value=None)
        self.agent._queued_error=Mock(return_value='')
        self.agent._download_video=Mock();self.agent._load_video_source=Mock(return_value='https://example/video/ready')
        self.saved=[];self.delivered=[]
    def tearDown(self):self.temp.cleanup()
    def test_download_recovers_indexed_image_absent_from_virtual_grid(self):
        self.agent.available_only=True
        self.records=self.records[:1]
        self.records[0]['kind']='image'
        asset={**self.asset(0),'kind':'image','visible':False,'prompt':self.records[0]['token']}
        self.inventory_mock.return_value=[asset]
        self.agent._agent_assets=Mock(return_value=[])
        self.agent._download_image=Mock(return_value=True)
        self.agent._asset_prompt=AgentMedia._asset_prompt.__get__(self.agent)
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual(self.records[0]['status'],'complete')
        self.agent._download_image.assert_called_once()
        self.page.locator.assert_not_called()
        self.agent._agent_assets.assert_not_called()
    def test_fresh_submission_collects_without_reloading_index(self):
        self.agent.fresh_submission=True
        self.records=self.records[:1]
        self.records[0]['kind']='image'
        self.agent._agent_assets=Mock(return_value=[{**self.asset(0),'kind':'image'}])
        self.agent._asset_prompt=Mock(return_value=self.records[0]['token'])
        self.agent._download_image=Mock(return_value=True)
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.inventory_mock.assert_not_called()
        self.assertEqual(self.records[0]['status'],'complete')
        self.assertFalse(self.agent.fresh_submission)

    def test_normal_retry_downloads_indexed_image_before_old_quota_notice(self):
        self.records=self.records[:1]
        self.records[0]['kind']='image'
        self.agent._queued_error.return_value='Account limit reached: old notice'
        self.inventory_mock.return_value=[{**self.asset(0),'kind':'image','prompt':self.records[0]['token']}]
        self.agent._download_image=Mock(return_value=True)
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual(self.records[0]['status'],'complete')
        self.agent._queued_error.assert_not_called()
    def test_empty_prompt_is_not_cached_and_can_be_read_on_retry(self):
        asset=self.asset(0)
        self.page.locator.return_value.first.locator.return_value.inner_text.return_value='generated image'
        self.page.locator.return_value.last.inner_text.side_effect=['',self.records[0]['token']]
        self.assertEqual(self.agent._asset_prompt(self.page,asset),'')
        self.assertNotIn(asset['asset_id'],self.agent._flow_asset_prompts)
        self.assertEqual(self.agent._asset_prompt(self.page,asset),self.records[0]['token'])

    def test_uploaded_reference_uses_exact_filename_without_prompt_popup(self):
        self.agent._flow_reference_filenames={'dsp.png'}
        footer=self.page.locator.return_value.first.locator.return_value
        footer.inner_text.return_value='image\nDSP.png'
        self.assertEqual(self.agent._asset_prompt(self.page,self.asset(0)),'FLOW_REFERENCE:DSP.png')
        footer.click.assert_not_called()
        footer.inner_text.return_value='image\nDSPOffice.png'
        self.page.locator.return_value.last.inner_text.return_value='another location'
        self.assertEqual(self.agent._asset_prompt(self.page,self.asset(1)),'another location')

    def test_offscreen_unread_asset_does_not_open_its_popup(self):
        self.records=self.records[:1]
        offscreen={**self.asset(9),'visible':False}
        self.agent._agent_assets=Mock(return_value=[offscreen,self.asset(0)])
        self.agent._asset_prompt=Mock(side_effect=lambda page,a:self.records[0]['token'] if a['asset_id']=='asset0' else self.fail('Offscreen popup opened'))
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual(self.records[0]['status'],'complete')

    def test_uploaded_reference_does_not_block_confirmed_missing_scene(self):
        directory=self.root/'references';directory.mkdir()
        (directory/'reference_plan.json').write_text(json.dumps({'references':[{'name':'DSP'}]}))
        self.agent._agent_assets=Mock(return_value=[self.asset(0)])
        self.agent._asset_prompt=Mock(return_value='FLOW_REFERENCE:DSP.png')
        self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'failed':False}
        clock=iter(range(0,5000,30))
        with patch('ai_studio_animate_media.time.monotonic',side_effect=lambda:next(clock)),patch('ai_studio_animate_media.time.sleep'):
            with self.assertRaises(MissingAgentOutputs):self.agent.collect(self.records,lambda:None,self.delivered.append)

    def test_available_only_finishes_scan_ignoring_reference_and_missing_scenes(self):
        self.agent.available_only=True
        for r in self.records:r['kind']='image';r['output']=r['output'].replace('videos','images').replace('.mp4','.png')
        self.agent._download_image=Mock(return_value=True)
        assets=[{**self.asset(i),'kind':'image'} for i in (0,9)]
        self.agent._agent_assets=Mock(return_value=assets)
        self.agent._asset_prompt=Mock(side_effect=lambda page,a:self.records[0]['token'] if a['asset_id']=='asset0' else 'FLOW_REFERENCE:DSP.png')
        directory=self.root/'references';directory.mkdir()
        (directory/'reference_plan.json').write_text(json.dumps({'references':[{'name':'DSP'}]}))
        self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'failed':False}
        self.agent._queued_error.return_value='Account limit reached: old quota notice'
        with patch('ai_studio_animate_media.time.sleep'):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual([r['index'] for r in self.delivered],[0])
        self.assertEqual(self.records[1]['status'],'submitted')
        self.agent._download_image.assert_called_once()

    def test_download_only_continues_scan_with_generation_unusual_activity_notice(self):
        self.agent.available_only=True
        self.agent._agent_assets=Mock(return_value=[self.asset(0)])
        self.agent._asset_prompt=Mock(return_value=self.records[0]['token'])
        self.agent._queued_error.return_value='Flow unusual-activity check: generation paused.'
        self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'failed':False}
        with patch('ai_studio_animate_media.time.sleep'):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual([r['index'] for r in self.delivered],[0])
        self.assertEqual(self.records[1]['status'],'submitted')

    def test_normal_collection_still_stops_for_unusual_activity(self):
        self.agent._agent_assets=Mock(return_value=[])
        self.agent._queued_error.return_value='Flow unusual-activity check: generation paused.'
        with self.assertRaisesRegex(RuntimeError,'unusual-activity'):
            self.agent.collect(self.records,lambda:None,self.delivered.append)

    def test_download_only_still_stops_for_sign_in_failure(self):
        self.agent.available_only=True
        self.agent._agent_assets=Mock(return_value=[])
        self.agent._queued_error.return_value='Sign-in required. Completed images and pending identities are saved.'
        with self.assertRaisesRegex(RuntimeError,'Sign-in required'):
            self.agent.collect(self.records,lambda:None,self.delivered.append)

    def test_download_scan_restores_position_after_prompt_popup_scrolls_grid(self):
        self.agent.available_only=True;self.records=self.records[:1]
        self.agent._scene_grid_position=Mock(return_value={'top':0,'height':3000,'client':1000})
        self.agent._agent_assets=Mock(return_value=[self.asset(0)])
        self.agent._asset_prompt=Mock(return_value=self.records[0]['token'])
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        calls=self.agent._scene_grid_position.call_args_list
        self.assertEqual(calls[0].args,(self.page,0))
        self.assertEqual(calls[1].args,(self.page,))
        self.assertEqual(calls[2].args,(self.page,0))

    def test_normal_retry_restores_position_after_prompt_popup_scrolls_grid(self):
        self.agent.available_only=False;self.records=self.records[:1]
        self.agent._scene_grid_position=Mock(return_value={'top':0,'height':3000,'client':1000})
        self.agent._agent_assets=Mock(return_value=[self.asset(0)])
        self.agent._asset_prompt=Mock(return_value=self.records[0]['token'])
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        calls=self.agent._scene_grid_position.call_args_list
        self.assertEqual(calls[0].args,(self.page,0))
        self.assertEqual(calls[1].args,(self.page,))
        self.assertEqual(calls[2].args,(self.page,0))

    def test_download_pass_count_survives_new_virtual_grid_assets(self):
        self.agent.available_only=True
        position={'top':0};reads=[]
        def scroll(page,top=None):
            if top is not None:position['top']=max(0,min(100,top))
            return {'top':position['top'],'height':200,'client':100}
        self.agent._scene_grid_position=Mock(side_effect=scroll)
        def assets(page):
            reads.append(position['top'])
            if len(reads)>10:self.fail('Grid pass counter reset on virtual asset changes')
            return [self.asset(20+len(reads))]
        self.agent._agent_assets=Mock(side_effect=assets)
        self.agent._asset_prompt=Mock(return_value='Unrelated output')
        self.page.evaluate.side_effect=lambda *args:{'x':500,'y':500,'delta':50,
            'at_end':position['top']>=100,'agent_busy':False,'failed':False}
        with patch('ai_studio_animate_media.time.sleep'):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual(reads[:6],[0,50,100,0,50,100])
        self.assertFalse(self.delivered)
        report=json.loads((self.root/'scene_download_diagnostics.json').read_text())
        self.assertEqual(report['completed_passes'],2)

    def test_verified_reference_edit_ids_require_project_and_file_hash(self):
        import hashlib
        directory=self.root/'references';directory.mkdir()
        image=directory/'DSP.png';image.write_bytes(b'approved reference')
        (directory/'reference_plan.json').write_text(json.dumps({'references':[{'name':'DSP'}]}))
        (self.root/'project.json').write_text(json.dumps({'options':{'flow_url':'original-project'}}))
        mapping={'flow_url':'original-project','assets':[{'asset_id':'edited-dsp','filename':'DSP.png','sha256':hashlib.sha256(image.read_bytes()).hexdigest()}]}
        file=directory/'verified_flow_assets.json';file.write_text(json.dumps(mapping))
        self.assertIn('edited-dsp',self.agent._reference_asset_ids(self.records))
        image.write_bytes(b'different reference')
        self.assertNotIn('edited-dsp',self.agent._reference_asset_ids(self.records))
        image.write_bytes(b'approved reference');mapping['flow_url']='other-project';file.write_text(json.dumps(mapping))
        self.assertNotIn('edited-dsp',self.agent._reference_asset_ids(self.records))

    def test_provider_refusal_retains_partial_downloads_and_stops_immediately(self):
        self.agent._agent_assets=Mock(return_value=[self.asset(0)])
        self.agent._asset_prompt=Mock(return_value=self.records[0]['token'])
        self.agent._agent_refusal=Mock(return_value='This generation might violate our policies.')
        with self.assertRaisesRegex(RuntimeError,'Flow rejected scene.s. 2'):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual(self.records[0]['status'],'complete')
        self.assertEqual(self.records[1]['pause_reason'],'provider_refusal')
        self.assertEqual(len(self.delivered),1)
        self.agent._queued_error.assert_not_called()

    def asset(self,i,src='https://example/video/ready'):
        return {'asset_id':f'asset{i}','src':src,'kind':'video','busy':False,'failed':False}
    def test_lazy_video_source_and_exact_identity_saved(self):
        self.agent._agent_assets=Mock(return_value=[self.asset(0,''),self.asset(1)])
        self.agent._asset_prompt=Mock(side_effect=lambda page,a:self.records[int(a['asset_id'][-1])]['token'])
        self.agent.collect(self.records,lambda:self.saved.append(True),self.delivered.append)
        self.assertEqual(len(self.delivered),2);self.agent._load_video_source.assert_called_once()
        self.assertTrue(all(r['status']=='complete' for r in self.records))
    def test_unlabelled_media_not_guessed_diagnostics_persisted(self):
        self.agent._agent_assets=Mock(return_value=[self.asset(0)])
        self.agent._asset_prompt=Mock(return_value='Unrelated generated video without a tracking label')
        with self.assertRaisesRegex(RuntimeError,'Unresolved scenes: 1, 2'),patch('ai_studio_animate_media.time.monotonic',side_effect=[0,1,3601]):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        report=json.loads((self.root/'agent_collection_diagnostics.json').read_text())
        self.assertEqual(report['missing_scenes'],[1,2]);self.assertFalse(self.delivered)
        self.assertEqual([r['status'] for r in self.records],['submitted','submitted'])
        self.agent._download_video.assert_not_called()
    def test_duplicate_identity_stops_without_assigning_scene(self):
        self.agent._agent_assets=Mock(return_value=[self.asset(0),self.asset(1)])
        self.agent._asset_prompt=Mock(return_value=self.records[0]['token'])
        with self.assertRaisesRegex(RuntimeError,'More than one asset'):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.agent._download_video.assert_not_called()

    def test_download_all_keeps_stable_variant_and_continues_other_scenes(self):
        self.agent.available_only=True
        for r in self.records:
            r['kind']='image';r['output']=r['output'].replace('videos','images').replace('.mp4','.png')
        self.agent._download_image=Mock(return_value=True)
        self.agent._agent_assets=Mock(return_value=[{**self.asset(i),'kind':'image','src':f'https://example/{i}.png'} for i in (3,1,2)])
        self.agent._asset_prompt=Mock(side_effect=lambda page,a:self.records[0]['token'] if a['asset_id'] in ('asset3','asset1') else self.records[1]['token'])
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual(self.records[0]['asset_id'],'asset1')
        self.assertEqual(self.records[0]['alternate_asset_ids'],['asset3'])
        self.assertEqual([r['index'] for r in self.delivered],[0,1])
        self.assertEqual(self.agent._download_image.call_count,2)

    def test_normal_image_collection_keeps_one_exact_variant_per_scene(self):
        self.agent.available_only=False
        for r in self.records:
            r['kind']='image';r['output']=r['output'].replace('videos','images').replace('.mp4','.png')
        self.agent._download_image=Mock(return_value=True)
        self.agent._agent_assets=Mock(return_value=[{**self.asset(i),'kind':'image','src':f'https://example/{i}.png'} for i in (3,1,2)])
        self.agent._asset_prompt=Mock(side_effect=lambda page,a:self.records[0]['token'] if a['asset_id'] in ('asset3','asset1') else self.records[1]['token'])
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual(self.records[0]['asset_id'],'asset1')
        self.assertEqual(self.records[0]['alternate_asset_ids'],['asset3'])
        self.assertEqual([r['index'] for r in self.delivered],[0,1])
        self.assertEqual(self.agent._download_image.call_count,2)

    def test_whole_batch_prompt_cannot_match_single_remaining_scene(self):
        first,second=self.records
        self.records=[first]
        self.agent._agent_assets=Mock(return_value=[self.asset(0)])
        self.agent._asset_prompt=Mock(return_value=first['token']+' '+second['token'])
        with self.assertRaisesRegex(RuntimeError,'Unresolved scenes: 1'),patch('ai_studio_animate_media.time.monotonic',side_effect=[0,1,3601]):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertFalse(self.delivered)

    def test_resume_matched_asset_uses_saved_id_without_prompt_or_submission(self):
        self.records=self.records[:1];self.records[0].update(status='matched',asset_id='asset0')
        self.agent._agent_assets=Mock(return_value=[self.asset(0)])
        self.agent._asset_prompt=Mock(side_effect=AssertionError('Saved identity should be reused'))
        self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertEqual(self.records[0]['status'],'complete');self.assertEqual(len(self.delivered),1)

    def test_progress_is_retained_when_remaining_scene_has_no_label(self):
        self.agent._agent_assets=Mock(return_value=[self.asset(0),self.asset(1)])
        self.agent._asset_prompt=Mock(side_effect=lambda page,a:self.records[0]['token'] if a['asset_id']=='asset0' else '')
        with patch('ai_studio_animate_media.time.monotonic',side_effect=[0,1,2,3601]),self.assertRaisesRegex(RuntimeError,'Unresolved scenes: 2'):
            self.agent.collect(self.records,lambda:self.saved.append(True),self.delivered.append)
        self.assertEqual(self.records[0]['status'],'complete');self.assertEqual(self.records[1]['status'],'submitted')
        self.assertEqual(len(self.delivered),1);self.assertEqual(len(self.saved),2)

    def test_settled_grid_with_reference_images_detects_missing_videos_early(self):
        image={**self.asset(0),'asset_id':'reference','kind':'image'}
        self.agent._agent_assets=Mock(return_value=[image])
        self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'failed':False}
        clock=iter(range(0,2000,30))
        with patch('ai_studio_animate_media.time.monotonic',side_effect=lambda:next(clock)),patch('ai_studio_animate_media.time.sleep'),self.assertRaises(MissingAgentOutputs):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertFalse(self.delivered)

    def test_unlabelled_video_or_busy_agent_cannot_confirm_missing(self):
        for active in (False,True):
            self.agent._agent_assets=Mock(return_value=[self.asset(0)])
            self.agent._asset_prompt=Mock(return_value='')
            self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':active,'failed':False}
            clock=iter(range(0,5000,30))
            with patch('ai_studio_animate_media.time.monotonic',side_effect=lambda:next(clock)),patch('ai_studio_animate_media.time.sleep'),self.assertRaises(RuntimeError) as error:
                self.agent.collect(self.records,lambda:None,self.delivered.append,timeout=300)
            self.assertNotIsInstance(error.exception,MissingAgentOutputs)

    def test_image_request_recovers_after_idle_scan_of_verified_references(self):
        from ai_studio_pipeline import atomic_json
        self.records=[dict(self.records[0],kind='image',output=str(self.root/'images/scene_0001.png'))]
        atomic_json(self.root/'references/image_batches.json',{'requests':{'ref':{'asset_id':'reference','status':'complete'}}})
        self.agent._agent_assets=Mock(return_value=[dict(self.asset(0),asset_id='reference',kind='image')])
        self.agent._asset_prompt=Mock(side_effect=AssertionError('Verified reference prompts need not be reopened'))
        self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'failed':False,'unidentified':False}
        clock=iter(range(0,2000,30))
        with patch('ai_studio_animate_media.time.monotonic',side_effect=lambda:next(clock)),patch('ai_studio_animate_media.time.sleep'),self.assertRaises(MissingAgentOutputs):
            self.agent.collect(self.records,lambda:None,self.delivered.append)
        self.assertFalse(self.delivered)

    def test_unidentified_image_cannot_trigger_duplicate_generation(self):
        self.records=[dict(self.records[0],kind='image',output=str(self.root/'images/scene_0001.png'))]
        self.agent._agent_assets=Mock(return_value=[dict(self.asset(0),kind='image')]);self.agent._asset_prompt=Mock(return_value='')
        self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'failed':False,'unidentified':False}
        clock=iter(range(0,5000,30))
        with patch('ai_studio_animate_media.time.monotonic',side_effect=lambda:next(clock)),patch('ai_studio_animate_media.time.sleep'),self.assertRaises(RuntimeError) as error:
            self.agent.collect(self.records,lambda:None,self.delivered.append,timeout=300)
        self.assertNotIsInstance(error.exception,MissingAgentOutputs)

    def test_old_page_quota_does_not_bypass_current_batch_scan(self):
        self.agent.agent_image_fallback=True
        self.agent._queued_error.return_value='Account limit reached: old page notice'
        self.records=[dict(self.records[0],kind='image',output=str(self.root/'images/scene_0001.png'))]
        self.agent._agent_assets=Mock(return_value=[dict(self.asset(0),kind='image')]);self.agent._asset_prompt=Mock(return_value='')
        self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'failed':False,'unidentified':False}
        clock=iter(range(0,5000,30))
        with patch('ai_studio_animate_media.time.monotonic',side_effect=lambda:next(clock)),patch('ai_studio_animate_media.time.sleep'),self.assertRaises(RuntimeError) as error:
            self.agent.collect(self.records,lambda:None,self.delivered.append,timeout=300)
        self.assertNotIsInstance(error.exception,MissingAgentOutputs)
        self.assertNotIn('Account limit reached',str(error.exception))

    def test_explicit_generate_images_allows_bounded_unmatched_recovery(self):
        self.agent.retry_unmatched_images=True
        self.records=[dict(self.records[0],kind='image',output=str(self.root/'images/scene_0001.png'))]
        self.agent._agent_assets=Mock(return_value=[dict(self.asset(0),kind='image')]);self.agent._asset_prompt=Mock(return_value='')
        self.page.evaluate.return_value={'x':500,'y':500,'delta':-1000,'at_end':True,'agent_busy':False,'failed':False,'unidentified':False}
        clock=iter(range(0,5000,30))
        with patch('ai_studio_animate_media.time.monotonic',side_effect=lambda:next(clock)),patch('ai_studio_animate_media.time.sleep'),self.assertRaises(RuntimeError) as error:
            self.agent.collect(self.records,lambda:None,self.delivered.append,timeout=300)
        self.assertIsInstance(error.exception,MissingAgentOutputs)

if __name__=='__main__':unittest.main()
