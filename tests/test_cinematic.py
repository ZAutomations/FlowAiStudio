import copy,json,math,queue,struct,tempfile,threading,unittest,wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from ai_studio_cinematic import prepare, validate_plan, handoff
from ai_studio_pipeline import run_ffmpeg, probe


class CinematicTests(unittest.TestCase):
    def director(self,system,payload,**kwargs):
        data=json.loads(payload);previous=data['previous_end_state'];result=[]
        for row in data['clips']:
            n=row['clip'];item={'clip':n,'visual_prompt':'The father continues walking through the same courtyard.',
                'location':'Courtyard','start_state':previous['end_state'] if previous else 'At the doorway',
                'end_state':f'Courtyard position {n}','continues_previous':bool(previous),'references':[],
                'shots':[{'start':0,'end':4,'visual_prompt':'Continue the action.'},{'start':4,'end':8,'visual_prompt':'A natural reaction.'}] if row['media_type']=='video' else []}
            result.append(item);previous=item
        return json.dumps(result),None
    def fixture(self,tmp):
        scenes=[{'id':i+1,'narration':text,'visual_prompt':'An exact village illustration.'} for i,text in enumerate(['One two three four.','Five six seven eight.','Nine ten eleven twelve.'])]
        adapter=SimpleNamespace(zb_scenes=scenes,_zb_cancel=threading.Event(),_zb_save_project=Mock(),_zb_llm=Mock(side_effect=self.director),zb_last_video=None)
        config={'project':str(tmp),'script':' '.join(s['narration'] for s in scenes),'style':'Hand painted village story.',
            'voice_engine':'piper','settings':{},'reference_mode':'none','animate_narration_mode':'cinematic','animation_mode':'full',
            'animate_model':'Veo 3.1 - Lite','resolution':'160x90'}
        def tts(text,path,settings):
            with wave.open(str(path),'wb') as stream:
                stream.setparams((1,2,48000,0,'NONE','not compressed'))
                stream.writeframes(b''.join(struct.pack('<h',int(6000*math.sin(i/30))) for i in range(960000)))
            return True,[]
        words=[{'word':w,'offset':i*1.6+.1,'duration':.8} for i,w in enumerate(config['script'].split())]
        return adapter,config,Mock(side_effect=tts),Mock(return_value=words)
    def test_actual_audio_grouping_resume_and_render(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);adapter,config,tts,asr=self.fixture(root)
            prepare(adapter,queue.Queue(),config,tts,asr)
            self.assertEqual([probe(s['audio_path'])[0] for s in adapter.zb_scenes],[8,8,4])
            self.assertEqual(' '.join(s['narration'] for s in adapter.zb_scenes),config['script'])
            self.assertEqual(len(json.loads(adapter._zb_llm.call_args.args[1])['clips']),3)
            self.assertNotIn('full_story',json.loads(adapter._zb_llm.call_args.args[1]))
            samples=[]
            for row in adapter.zb_scenes:
                with wave.open(row['audio_path'],'rb') as stream:samples.append(stream.readframes(stream.getnframes()))
            with wave.open(str(next((root/'voice/continuous').glob('*/narration.wav'))),'rb') as stream:
                self.assertEqual(b''.join(samples),stream.readframes(stream.getnframes()))
            first=copy.deepcopy(adapter.zb_scenes)
            videos=[]
            for i,scene in enumerate(adapter.zb_scenes):
                from PIL import Image
                image=root/f'image_{i}.png';Image.new('RGB',(160,90),'navy').save(image)
                video=root/f'clip_{i}.mp4'
                run_ffmpeg(['-f','lavfi','-i',f'color=c=navy:s=160x90:r=25:d=8','-c:v','libx264','-pix_fmt','yuv420p',video])
                scene.update(video_path=str(video),video_status='done',image_path=str(image));videos.append(video)
            del adapter._cinematic_ready
            prepare(adapter,queue.Queue(),config,tts,asr)
            self.assertEqual(adapter.zb_scenes[1]['video_path'],str(videos[1]))
            tts.assert_called_once();adapter._zb_llm.assert_called_once()
            from ai_studio_animate_render import render_animated_video
            out=render_animated_video(adapter.zb_scenes,root/'render',{**config,'transition':'Cut','captions':False,'use_captions_tab':False,'use_effects_tab':False})
            self.assertAlmostEqual(probe(out)[0],20,delta=.12)
            records=[{'index':i,'kind':'video','status':'complete','output':str(p)} for i,p in enumerate(videos)]
            changed=handoff(adapter.zb_scenes,records,records[1],{**config,'references':[]},None,lambda m:None)
            self.assertEqual(changed['cinematic_previous_frame'],'PreviousClip0001')
            self.assertTrue(Path(changed['references'][-1]).is_file())
            records[0]['status']='submitted'
            with self.assertRaisesRegex(RuntimeError,'must be downloaded'):
                handoff(adapter.zb_scenes,records,records[1],config,None,lambda m:None)
            (root/'animate_media.json').write_text('{}')
            del adapter._cinematic_ready
            with self.assertRaisesRegex(ValueError,'changed after media'):
                prepare(adapter,queue.Queue(),{**config,'style':'Different style'},tts,asr)
            tts.assert_called_once()
    def test_ready_split_json_skips_director_and_reuses_image_prompts(self):
        from ai_studio_animate_prompts import parse_split
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            adapter,config,tts,asr=self.fixture(Path(tmp))
            first=adapter.zb_scenes[0];rest=adapter.zb_scenes[1:]
            clip={**first,'references':[],'continuity':{'location':'Courtyard','start_state':'Door','end_state':'Table','continues_previous':False},
                  'shots':[{'start':0,'end':4,'visual_prompt':'Walk'},{'start':4,'end':8,'visual_prompt':'React'}]}
            video={'version':1,'title':'Story','script':config['script'],'video_clips':[clip]}
            images={'version':1,'image_scenes':rest}
            ready=parse_split(json.dumps(video),json.dumps(images),config['script'])
            adapter.zb_scenes=ready['scenes'];config.update(ready['options'])
            # Audio boundaries may overlap semantic beats, but no LLM is needed.
            prepare(adapter,queue.Queue(),config,tts,asr)
            adapter._zb_llm.assert_not_called()
            self.assertEqual([r['cinematic_kind'] for r in adapter.zb_scenes],['video','image','image'])
            self.assertIn('village',adapter.zb_scenes[-1]['visual_prompt'])
            with self.assertRaisesRegex(ValueError,'preserve'):
                parse_split(json.dumps({**video,'script':'Changed narration'}),json.dumps(images))
    def test_split_import_through_worker_preserves_source_and_strips_raw_json(self):
        from desktop.worker import studio
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            video={'version':1,'title':'Split test','script':'Walk home. Rest inside.','video_clips':[{'narration':'Walk home.','visual_prompt':'Walk through courtyard.','references':[],
                'continuity':{'location':'Courtyard','start_state':'Door','end_state':'Table','continues_previous':False},
                'shots':[{'start':0,'end':4,'visual_prompt':'Walk'},{'start':4,'end':8,'visual_prompt':'Arrive'}]}]}
            image={'version':1,'image_scenes':[{'narration':'Rest inside.','visual_prompt':'Rest at table.','references':[]}]}
            payload={'project':tmp,'title':'Split test','action':'import-ready-animation','voice_engine':'google_cloud','reference_mode':'none',
                     'animation_video_ready':json.dumps(video),'animation_image_ready':json.dumps(image),'script':video['script']}
            from desktop.server import validate
            validate('animate',payload,{})
            studio(payload,{},threading.Event(),animated=True,emit=lambda **event:None)
            saved=json.loads((Path(tmp)/'project.json').read_text('utf-8'))
            self.assertEqual(len(saved['scenes']),2)
            self.assertTrue(saved['options']['cinematic_ready_prompts'])
            self.assertEqual(saved['options']['animate_count'],1)
            self.assertNotIn('animation_video_ready',saved['options'])
            self.assertNotIn('cinematic_media_kind',saved['options'])
            self.assertEqual(saved['scenes'][0]['cinematic_continuity']['location'],'Courtyard')

    def test_partial_eight_seconds_then_original_image_beats(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            adapter,config,tts,asr=self.fixture(Path(tmp))
            config.update(animation_mode='partial',partial_animation_unit='seconds',animate_seconds=8)
            adapter.zb_scenes[-1]['visual_prompt']=''
            prepare(adapter,queue.Queue(),config,tts,asr)
            self.assertIn('Narration:',adapter.zb_scenes[-1]['visual_prompt'])
            self.assertEqual(adapter.zb_scenes[0]['cinematic_end'],8)
            self.assertEqual(len(json.loads(adapter._zb_llm.call_args.args[1])['clips']),1)
            self.assertEqual([s['cinematic_kind'] for s in adapter.zb_scenes],['video','image','image'])
            self.assertEqual(sum(probe(s['audio_path'])[0] for s in adapter.zb_scenes),20)
            self.assertEqual(' '.join(s['narration'] for s in adapter.zb_scenes),config['script'])
    def test_existing_generated_project_cannot_be_replanned(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            adapter,config,tts,asr=self.fixture(Path(tmp));adapter.zb_scenes[0]['video_path']='existing.mp4'
            with self.assertRaisesRegex(ValueError,'new empty Animate project'):
                prepare(adapter,queue.Queue(),config,tts,asr)
            tts.assert_not_called()
    def test_agent_generates_sequentially_and_attaches_real_previous_frame(self):
        from test_animate_full import FullAnimateTests
        from ai_studio_animate_media import generate_agent_media
        import shutil
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);adapter,config,tts,asr=self.fixture(root)
            prepare(adapter,queue.Queue(),config,tts,asr)
            config.update(flow_url='https://flow.google.com/project/offline-test',references=[])
            prepared=[];submitted=[];attached=[]
            base=FullAnimateTests().fake_agent(prepared,submitted)
            fixture=root/'fixture.mp4'
            run_ffmpeg(['-f','lavfi','-i','color=c=red:s=160x90:r=25:d=8','-c:v','libx264','-pix_fmt','yuv420p',fixture])
            class Agent(base):
                def _batch_page(agent,ctx):
                    page=super()._batch_page(ctx)
                    page.locator('anything').first.all_text_contents.return_value=[Path(p).stem for p in attached[-1]] if attached else []
                    return page
                def collect(agent,records,save,on_media):
                    for record in records:
                        path=Path(record['output']);path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(fixture,path)
                        record['status']='complete';save();on_media(record)
            def stage(cfg,path,refs,*args):
                prepared.append(Path(path).read_text('utf-8'));attached.append(list(refs))
            with patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=stage):
                generate_agent_media(adapter.zb_scenes,config,threading.Event(),lambda m:None,lambda record:None)
                self.assertEqual(len(submitted),3)
                self.assertEqual(attached[0],[])
                self.assertTrue(attached[1][0].endswith('PreviousClip0001.png'))
                self.assertIn('CONTINUATION FRAME @PreviousClip0001',submitted[1])
                self.assertTrue(all(prompt.count(' \u2014 VIDEO \u2014 ')==1 for prompt in submitted))
                generate_agent_media(adapter.zb_scenes,config,threading.Event(),lambda m:None,lambda record:None)
                self.assertEqual(len(submitted),3)
    def test_separate_video_and_image_generation_share_checkpoint(self):
        from test_animate_full import FullAnimateTests
        from ai_studio_animate_media import generate_agent_media
        from PIL import Image
        import shutil
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);adapter,config,tts,asr=self.fixture(root)
            config.update(animation_mode='partial',partial_animation_unit='seconds',animate_seconds=8)
            prepare(adapter,queue.Queue(),config,tts,asr)
            config.update(flow_url='https://flow.google.com/project/offline-test',references=[])
            prepared=[];submitted=[];seen=[];base=FullAnimateTests().fake_agent(prepared,submitted)
            fixture=root/'fixture.mp4'
            run_ffmpeg(['-f','lavfi','-i','color=c=red:s=160x90:r=25:d=8','-c:v','libx264','-pix_fmt','yuv420p',fixture])
            class Agent(base):
                def _batch_page(agent,ctx):
                    page=super()._batch_page(ctx)
                    page.locator('anything').first.all_text_contents.return_value=[]
                    return page
                def collect(agent,records,save,on_media):
                    for record in records:
                        seen.append(record['kind']);path=Path(record['output']);path.parent.mkdir(parents=True,exist_ok=True)
                        if record['kind']=='video':shutil.copy2(fixture,path)
                        else:Image.new('RGB',(160,90),'blue').save(path)
                        record['status']='complete';save();on_media(record)
            with patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda cfg,path,*args:prepared.append(Path(path).read_text('utf-8'))):
                for kind,expected in [('video',['video']),('image',['video','image','image'])]:
                    generate_agent_media(adapter.zb_scenes,{**config,'cinematic_media_kind':kind},threading.Event(),lambda m:None,lambda r:None)
                    self.assertEqual(seen,expected)
                generate_agent_media(adapter.zb_scenes,config,threading.Event(),lambda m:None,lambda r:None)
                self.assertEqual(seen,['video','image','image'])

    def test_broken_continuity_or_unknown_reference_rejected(self):
        rows=[{'id':2,'cinematic_kind':'video'}]
        valid={'clip':2,'visual_prompt':'Walk','location':'Room','start_state':'At door','end_state':'At desk',
            'continues_previous':True,'references':[],'shots':[{'start':0,'end':4,'visual_prompt':'Walk'},{'start':4,'end':8,'visual_prompt':'Sit'}]}
        previous={'location':'Room','end_state':'At door'}
        self.assertEqual(len(validate_plan(json.dumps([valid]),rows,set(),previous)),1)
        for patch in ({'start_state':'Different clothes'},{'references':['InventedPerson']},{'shots':[{'start':0,'end':8,'visual_prompt':'One shot'}]}):
            with self.assertRaises(RuntimeError):validate_plan(json.dumps([{**valid,**patch}]),rows,set(),previous)

    def test_full_cast_survives_measured_timeline_and_cached_resume(self):
        from ai_studio_pipeline import atomic_json
        from ai_studio_cast import source_key
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            adapter,config,tts,asr=self.fixture(Path(tmp));config['character_consistency']=True
            assets=[dict(name=n,kind='location' if n=='Courtyard' else 'character',aliases=[],description='Fixed appearance for '+n) for n in ['Father','Mother','Child','Courtyard']]
            rows=[dict(scene=i+1,narration=s['narration'],visual_prompt=s['visual_prompt'],references=[assets[i]['name'],'Courtyard']) for i,s in enumerate(adapter.zb_scenes)]
            atomic_json(Path(tmp)/'cast_analysis.json',dict(assets=assets,scenes=rows,approved=True,source_key=source_key(config,adapter.zb_scenes)))
            prepare(adapter,queue.Queue(),config,tts,asr)
            self.assertEqual(set(adapter.zb_scenes[0]['reference_names']),{'Father','Mother','Courtyard'})
            self.assertEqual(adapter.zb_scenes[-1]['reference_names'],['Child','Courtyard'])
            expected=copy.deepcopy(config['scene_reference_map']);calls=adapter._zb_llm.call_count
            del adapter._cinematic_ready
            prepare(adapter,queue.Queue(),config,tts,asr)
            self.assertEqual(config['scene_reference_map'],expected)
            self.assertEqual(adapter._zb_llm.call_count,calls);tts.assert_called_once()

    def test_cast_added_after_review_reuses_original_audio_plan_and_existing_image(self):
        from ai_studio_pipeline import atomic_json
        from ai_studio_cast import source_key
        from PIL import Image
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            adapter,config,tts,asr=self.fixture(Path(tmp))
            prepare(adapter,queue.Queue(),config,tts,asr)
            original=copy.deepcopy(adapter.zb_scenes);old_audio=[Path(s['audio_path']).read_bytes() for s in original]
            image=Path(tmp)/'already_saved.png';Image.new('RGB',(160,90),'red').save(image)
            adapter.zb_scenes[0].update(image_path=str(image),image_key='existing-key',image_status='done')
            assets=[dict(name='Father',kind='character',aliases=[],description='Fixed father design')]
            rows=[dict(scene=i+1,narration=s['narration'],visual_prompt=s['visual_prompt'],references=['Father']) for i,s in enumerate(original)]
            atomic_json(Path(tmp)/'cast_analysis.json',dict(assets=assets,scenes=rows,approved=True,source_key=source_key(config,original)))
            config['character_consistency']=True;del adapter._cinematic_ready
            calls=adapter._zb_llm.call_count;prepare(adapter,queue.Queue(),config,tts,asr)
            self.assertEqual(adapter._zb_llm.call_count,calls);tts.assert_called_once()
            self.assertEqual([Path(s['audio_path']).read_bytes() for s in adapter.zb_scenes],old_audio)
            self.assertEqual([s['shots'] for s in adapter.zb_scenes],[s['shots'] for s in original])
            self.assertEqual(adapter.zb_scenes[0]['image_path'],str(image));self.assertEqual(adapter.zb_scenes[0]['image_key'],'existing-key')


if __name__=='__main__':unittest.main()
