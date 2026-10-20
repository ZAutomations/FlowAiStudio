import copy,json,queue,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
from ai_studio_pipeline import atomic_json
from ai_studio_cast import source_key
from ai_studio_animate_cast import reviewed,references,approve
from ai_studio_animate_media import media_plan


class AnimateCastTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.root=Path(self.temp.name)
        self.scenes=[{'id':i+1,'narration':t,'visual_prompt':'Illustrate this exact action.'} for i,t in enumerate(['DSP walks.','Ali listens.','Mother waits.','Child arrives.'])]
        from ai_studio_pipeline import STYLE_PRESETS
        self.config=dict(project=str(self.root),title='Cast test',script=' '.join(s['narration'] for s in self.scenes),style=STYLE_PRESETS['Cinematic realistic'],
                         character_consistency=True,reference_mode='characters',auto_reference=True,flow_url='https://flow.google.com/project/test',
                         animate_model='Veo 3.1 - Lite',animation_mode='full',resolution='1920x1080',continuity='',reference_design='')
        self.assets=[{'name':n,'kind':'location' if n=='Station' else 'character','description':'Fixed design for '+n,'aliases':[]} for n in ['DSP','Ali','Mother','Child','Station']]
        self.data=dict(assets=self.assets,scenes=[dict(scene=i+1,narration=s['narration'],references=[self.assets[i]['name'],'Station'],visual_prompt=s['visual_prompt']) for i,s in enumerate(self.scenes)],
                       source_key=source_key(self.config,self.scenes),approved=True)
        atomic_json(self.root/'cast_analysis.json',self.data)
        self.adapter=SimpleNamespace(zb_scenes=copy.deepcopy(self.scenes),_zb_cancel=threading.Event(),_zb_save_project=Mock(),_zb_llm=Mock())
    def tearDown(self):self.temp.cleanup()
    def test_all_five_paths_and_exact_per_clip_identity(self):
        paths=[]
        for a in self.assets:
            path=self.root/(a['name']+'.png');Image.new('RGB',(24,24),'red').save(path);paths.append(str(path))
        from desktop.animate import references as validate_paths
        self.assertEqual(validate_paths({**self.config,'reference_files':'|'.join(paths)}),paths)
        reviewed(self.config,self.scenes);self.config['references']=paths
        plan=media_plan(self.scenes,self.config)
        self.assertEqual(plan[0]['reference_names'],['DSP','Station'])
        self.assertEqual(plan[2]['reference_names'],['Mother','Station'])
        before=plan[0]['key'];Image.new('RGB',(24,24),'blue').save(paths[2])
        self.assertEqual(media_plan(self.scenes,self.config)[0]['key'],before)
        self.assertNotEqual(media_plan(self.scenes,self.config)[2]['key'],plan[2]['key'])
    def test_measured_clip_regrouping_carries_only_overlapping_cast(self):
        grouped=[{'narration':'DSP walks. Ali listens.'},{'narration':'Mother waits. Child arrives.'}]
        reviewed(self.config,grouped)
        self.assertEqual(grouped[0]['reference_names'],['DSP','Station','Ali'])
        self.assertEqual(grouped[1]['reference_names'],['Mother','Station','Child'])
        self.assertTrue(grouped[0]['visual_prompt'])
        approve(SimpleNamespace(zb_scenes=grouped),queue.Queue(),self.config,self.data)
        self.assertTrue(json.loads((self.root/'cast_analysis.json').read_text('utf-8'))['approved'])
    def test_review_gate_and_narration_changes_do_not_touch_media(self):
        atomic_json(self.root/'cast_analysis.json',{**self.data,'approved':False})
        with self.assertRaisesRegex(ValueError,'approve'):reviewed(self.config,self.scenes)
        atomic_json(self.root/'cast_analysis.json',self.data)
        with self.assertRaisesRegex(ValueError,'differs'):reviewed(self.config,[{'narration':'A different story.'}])
    def test_uploads_complete_library_once_without_changing_animation_options(self):
        paths=[]
        for a in self.assets:
            path=self.root/(a['name']+'.png');Image.new('RGB',(24,24),'red').save(path);paths.append(str(path))
        with patch('ai_studio_animate_setup.ensure_project',return_value=self.config['flow_url']),patch('ai_studio_animate_setup.ensure_references',return_value=paths) as ensure,patch('ai_studio_consistency.upload_reference_library') as upload:
            references(self.adapter,queue.Queue(),self.config)
            self.assertEqual(len(ensure.call_args.args[0]['cast_assets']),5)
            self.assertEqual(upload.call_args.args[1]['references'],paths)
            self.assertEqual(self.config['animation_mode'],'full')
            self.assertNotIn('image_agent',self.config)
            self.adapter._zb_llm.assert_not_called()
    def test_more_than_six_references_per_measured_clip_reports_instead_of_dropping(self):
        extra=[dict(name=n,kind='character',description='Fixed face',aliases=[]) for n in ['ExtraA','ExtraB']]
        self.data['assets']+=extra;self.data['scenes'][3]['references']+=['ExtraA','ExtraB']
        atomic_json(self.root/'cast_analysis.json',self.data)
        with self.assertRaisesRegex(ValueError,'at most six'):reviewed(self.config,[{'narration':self.config['script']}])
    def test_worker_build_pauses_for_cast_review_before_voice_or_browser(self):
        from desktop.worker import studio
        atomic_json(self.root/'cast_analysis.json',{**self.data,'approved':False})
        atomic_json(self.root/'project.json',dict(script=self.config['script'],title='Cast test',scenes=self.scenes,options={**self.config,'voice_engine':'google_cloud'}))
        with patch('ai_studio_animate.AnimateStudio._zb_voice_pass') as voice,patch('ai_studio_animate_setup.ensure_project') as browser:
            result=studio({'project':str(self.root),'action':'build','character_consistency':True},{},threading.Event(),animated=True,emit=lambda **e:None)
            self.assertTrue(result['review_required']);voice.assert_not_called();browser.assert_not_called()
    def test_video_batches_attach_one_clip_and_image_unions_stay_bounded(self):
        from ai_studio_animate_media import cast_groups
        rows=[dict(index=i,kind='video' if i<2 else 'image',reference_names=[f'Person{i}','Station']) for i in range(10)]
        groups=cast_groups(rows)
        self.assertEqual([len(g) for _,g in groups[:2]],[1,1])
        for _,group in groups:self.assertLessEqual(len({n for r in group for n in r['reference_names']}),6)
        self.assertEqual([r['index'] for _,g in groups for r in g],list(range(10)))
    def test_new_project_never_copies_old_story_even_with_stale_source(self):
        from desktop.animate import new_project
        source=self.root/'old';source.mkdir();image=source/'old.png';Image.new('RGB',(512,512),'red').save(image)
        atomic_json(source/'project.json',dict(title='Old story',script='Old narration.',scenes=[dict(id=1,narration='Old narration.',image_path=str(image),audio_path='old.wav')],options={}))
        original=(source/'project.json').read_bytes();target=self.root/'fresh'
        result=new_project(dict(action='new',project=str(target),animate_source=str(source),title='New story',script='Old narration.',voice_engine='google_cloud',flow_url='https://flow.google.com/project/old',references=[str(image)],reference_files=str(image),planning_source='chatgpt_ready',cinematic_ready_prompts=True),{},threading.Event(),lambda **e:None)
        saved=json.loads((target/'project.json').read_text('utf-8'))
        self.assertEqual(saved['script'],'');self.assertEqual(saved['scenes'],[])
        self.assertEqual(saved['options']['flow_url'],'');self.assertEqual(saved['options']['references'],[])
        self.assertNotIn('planning_source',saved['options']);self.assertEqual(result['scenes'],0)
        self.assertEqual((source/'project.json').read_bytes(),original);self.assertTrue(image.exists())

    def test_split_json_cast_import_creates_review_without_ai_or_browser(self):
        from desktop.worker import studio
        clips=[dict(narration=self.scenes[0]['narration'],visual_prompt='Walk into the station.',references=['DSP','Station'],
                    continuity=dict(location='Station',start_state='Door',end_state='Desk',continues_previous=False),
                    shots=[dict(start=0,end=4,visual_prompt='Walk'),dict(start=4,end=8,visual_prompt='Sit')])]
        video=dict(version=1,title='Cast test',script=self.config['script'],assets=self.assets,video_clips=clips)
        image=dict(version=1,image_scenes=[dict(narration=s['narration'],visual_prompt=s['visual_prompt'],references=self.data['scenes'][i+1]['references']) for i,s in enumerate(self.scenes[1:])])
        payload=dict(project=str(self.root),action='import-ready-animation',animation_video_ready=json.dumps(video),animation_image_ready=json.dumps(image),voice_engine='google_cloud')
        result=studio(payload,{},threading.Event(),animated=True,emit=lambda **e:None)
        saved=json.loads((self.root/'project.json').read_text('utf-8'))
        cast=json.loads((self.root/'cast_analysis.json').read_text('utf-8'))
        self.assertEqual(result['scenes'],4);self.assertTrue(saved['options']['character_consistency'])
        self.assertFalse(cast['approved']);self.assertEqual(len(cast['assets']),5)
        self.assertEqual(cast['scenes'][0]['references'],['DSP','Station'])
    def test_cast_upgrade_preserves_completed_and_manually_submitted_tracking_ids(self):
        from ai_studio_animate_cast import remember_existing,adopt_existing_media
        from ai_studio_pipeline import fingerprint
        previous={**self.config,'character_consistency':False,'references':[]}
        old_plan=media_plan(self.scenes,previous)
        state={'identity':fingerprint([(r['key'],r['index']) for r in old_plan],previous['flow_url']),
               'records':[{**r,'status':'complete' if i==0 else 'submitted' if i==1 else 'pending'} for i,r in enumerate(old_plan)]}
        atomic_json(self.root/'animate_media.json',state);remember_existing(self.config,previous)
        reviewed(self.config,self.scenes);new_plan=media_plan(self.scenes,self.config)
        plan,adopted=adopt_existing_media(new_plan,state,self.scenes,self.config)
        self.assertEqual([r['token'] for r in plan[:2]],[r['token'] for r in old_plan[:2]])
        self.assertEqual([r['status'] for r in adopted['records'][:2]],['complete','submitted'])
        self.assertEqual(plan[2]['key'],new_plan[2]['key']);self.assertNotEqual(plan[2]['key'],old_plan[2]['key'])
        second,same=adopt_existing_media(new_plan,adopted,self.scenes,self.config)
        self.assertEqual([r['key'] for r in second],[r['key'] for r in plan]);self.assertEqual(same,adopted)
        changed_model=media_plan(self.scenes,{**self.config,'animate_model':'Omni 1.1 Flash'})
        untouched,unchanged=adopt_existing_media(changed_model,state,self.scenes,{**self.config,'animate_model':'Omni 1.1 Flash'})
        self.assertEqual(untouched,changed_model);self.assertEqual(unchanged,state)


if __name__=='__main__':unittest.main()
