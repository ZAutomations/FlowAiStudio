"""Offline tests only: no Tk windows, browser, running app or live Agent."""
import copy, io, json, tempfile, threading, unittest, wave
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from desktop.storage import ROOT, read
from desktop.worker import studio
from desktop.server import validate
from ai_studio_animate_options import animation_count, VIDEO_MODELS
from ai_studio_animate_media import media_plan, batch_prompt, generate_agent_media, prepare_agent_prompt, MissingAgentOutputs
from ai_studio_animate_render import render_animated_video
from ai_studio_pipeline import run_ffmpeg, probe, atomic_json

class FullAnimateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        self.config={'project':str(self.root),'agent_tool_dir':str(ROOT/'animate_flow_backend'),'resolution':'320x180','aspect':'16:9','style':'Cartoon','continuity':'','animate_count':3,'animate_model':'Omni 1.1 Flash','flow_url':'https://flow.google.com/project/test','references':[]}
        self.scenes=[{'narration':f'Scene {i+1}'} for i in range(13)]
    def tearDown(self):self.temp.cleanup()
    def fake_agent(self,prepared,submitted):
        parent=self
        class Agent:
            def __init__(self,*args,**kwargs):self._flow_asset_prompts={};self.cdp_port=10312;self.session_active=False
            @contextmanager
            def _session(self,**kwargs):
                self.session_active=True
                try:yield None
                finally:self.session_active=False
            def _batch_page(self,ctx):
                page=Mock();element=Mock();element.first=element
                element.inner_text.side_effect=lambda:prepared[-1]
                element.get_attribute.return_value='true';element.is_enabled.return_value=True
                element.click.side_effect=lambda **kwargs:submitted.append(prepared[-1]);page.locator.return_value=element
                return page
            def collect(self,records,save,on_media):
                for record in records:
                    path=Path(record['output']);path.parent.mkdir(parents=True,exist_ok=True)
                    if record['kind']=='image':Image.new('RGB',(32,32),'red').save(path)
                    else:path.write_bytes(record['key'].encode())
                    record['status']='complete';save();on_media(record)
        return Agent
    def generate(self,config,delivered=None):
        prepared=[];submitted=[]
        with patch('ai_studio_animate_media.AgentMedia',self.fake_agent(prepared,submitted)),patch('ai_studio_animate_media.valid_video',side_effect=lambda p:bool(p) and Path(p).is_file()),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda c,p,*args:prepared.append(Path(p).read_text('utf-8'))):
            generate_agent_media(self.scenes,config,threading.Event(),lambda m:None,(delivered if delivered is not None else []).append)
        return submitted
    def test_prompt_driver_uses_live_session_port_instead_of_stale_default(self):
        prepared=[];submitted=[];base=self.fake_agent(prepared,submitted);instances=[]
        class Agent(base):
            def __init__(agent,*args,**kwargs):
                super().__init__(*args,**kwargs);instances.append(agent)
        def prepare(config,path,*args):
            self.assertEqual(config['_agent_cdp_port'],10312)
            self.assertTrue(instances[0].session_active)
            prepared.append(Path(path).read_text('utf-8'))
        with patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=prepare),patch('ai_studio_animate_media.valid_video',side_effect=lambda p:bool(p) and Path(p).is_file()):
            generate_agent_media(self.scenes[:1],self.config,threading.Event(),lambda m:None,lambda r:None)
        self.assertEqual(len(submitted),1)

    def test_generate_selected_image_range_only_keeps_global_numbering(self):
        delivered=[]
        submitted=self.generate({**self.config,'animation_mode':'partial','animate_count':0,'scene_start':4,'scene_end':6},delivered)
        self.assertEqual([r['index'] for r in delivered],[3,4,5])
        self.assertEqual(len(submitted),1)
        self.assertTrue(all(Path(r['output']).name==f'scene_{r["index"]+1:04d}.png' for r in delivered))
        self.assertFalse((self.root/'images/scene_0001.png').exists())

    def test_image_continuation_preserves_completed_clips_after_model_selection_change(self):
        original={**self.config,'animate_model':'Veo 3.1 - Lite','scene_start':1,'scene_end':3}
        self.generate(original)
        before=[(self.root/'videos'/f'scene_{i:04d}.mp4').read_bytes() for i in range(1,4)]
        submitted=self.generate({**original,'animate_model':'Omni 1.1 Flash','animate_video_resolution':'360p','cinematic_media_kind':'image','scene_start':4,'scene_end':13})
        self.assertTrue(submitted)
        self.assertTrue(all(' - VIDEO - ' not in p for p in submitted))
        self.assertTrue(all((self.root/'images'/f'scene_{i:04d}.png').exists() for i in range(4,14)))
        self.assertEqual(before,[(self.root/'videos'/f'scene_{i:04d}.mp4').read_bytes() for i in range(1,4)])

    def test_image_batch_count_follows_gui_for_ten_and_twenty(self):
        for size in (10,20):
            from ai_studio_animate_media import cast_groups
            rows=[dict(index=i,kind='image',reference_names=[f'Person{i%20}','Station']) for i in range(45)]
            groups=cast_groups(rows,size=size,video_size=5)
            self.assertEqual([len(g) for _,g in groups],([10,10,10,10,5] if size==10 else [20,20,5]))
            self.assertEqual([r['index'] for _,g in groups for r in g],list(range(45)))

    def test_default_partial_full_and_selected_models(self):
        partial=media_plan(self.scenes,self.config);self.assertEqual([r['kind'] for r in partial],['video']*3+['image']*10)
        for model in VIDEO_MODELS:
            full=media_plan(self.scenes,{**self.config,'animation_mode':'full','animate_model':model})
            self.assertEqual([r['kind'] for r in full],['video']*13);self.assertIn(model,batch_prompt(full[:6],{**self.config,'animate_model':model}))
            self.assertEqual(len({r['token'] for r in full}),13);self.assertTrue(all(r['output'].endswith('.mp4') for r in full))
        self.assertEqual(animation_count({'animation_mode':'full','animate_count':0},60),60)
        for invalid in ({'animation_mode':'wrong'},{'animate_model':'wrong'},{'animate_count':-1},{'animate_count':1.5}):
            with self.assertRaises(ValueError):animation_count(invalid,20)
    def test_every_batch_video_and_completed_retry_no_resubmission(self):
        config={**self.config,'animation_mode':'full','animate_model':'Veo 3.1 - Lite'};delivered=[]
        submitted=self.generate(config,delivered)
        self.assertEqual(len(submitted),3);self.assertEqual([p.count(' — VIDEO — ') for p in submitted],[5,5,3]);self.assertTrue(all(' — IMAGE — ' not in p and 'Veo 3.1 - Lite' in p for p in submitted))
        self.assertEqual(len(delivered),13);self.assertEqual(self.generate(config),[])
    def test_switch_partial_full_preserves_clips_images_and_checkpoint(self):
        self.generate(self.config);before=read(self.root/'animate_media.json');old_video=(self.root/'videos/scene_0001.mp4').read_bytes();old_image=(self.root/'images/scene_0004.png').read_bytes()
        submitted=self.generate({**self.config,'animation_mode':'full'})
        self.assertEqual(sum(p.count(' — VIDEO — ') for p in submitted),10)
        self.assertEqual((self.root/'videos/scene_0001.mp4').read_bytes(),old_video);self.assertEqual((self.root/'images/scene_0004.png').read_bytes(),old_image)
        self.assertEqual(read(self.root/'animate_media.json')['records'][0]['key'],before['records'][0]['key'])
        self.assertTrue((self.root/'animate_plan_history'/f'{before["identity"]}.json').is_file())
        self.assertEqual(self.generate(self.config),[])

    def test_unsent_plan_can_change_style_and_archives_old_checkpoint(self):
        from ai_studio_pipeline import fingerprint
        old=media_plan(self.scenes,self.config)
        identity=fingerprint([(r['key'],r['index']) for r in old],self.config['flow_url'])
        atomic_json(self.root/'animate_media.json',{'version':1,'identity':identity,'records':[dict(r,status='pending') for r in old]})
        untouched=self.root/'old-reference.png';Image.new('RGB',(20,20)).save(untouched);before=untouched.read_bytes()
        changed={**self.config,'style':'2D object illustrations','animation_mode':'full'}
        submitted=self.generate(changed)
        self.assertEqual(len(submitted),3);self.assertTrue((self.root/'animate_plan_history'/f'{identity}.json').is_file())
        self.assertEqual(untouched.read_bytes(),before)
    def test_uncertain_mode_switch_and_model_change_do_not_submit(self):
        self.generate(self.config);state=read(self.root/'animate_media.json');state['records'][3]['status']='submitting';atomic_json(self.root/'animate_media.json',state);before=(self.root/'animate_media.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'previous animation mode'):self.generate({**self.config,'animation_mode':'full'})
        self.assertEqual((self.root/'animate_media.json').read_bytes(),before)
        with self.assertRaisesRegex(RuntimeError,'model'):self.generate({**self.config,'animation_mode':'full','animate_model':'Veo 3.1 - Lite'})
        self.assertEqual((self.root/'animate_media.json').read_bytes(),before)
    def test_api_worker_save_and_resume_keep_mode_and_model(self):
        for model in VIDEO_MODELS:
            payload={'project':str(self.root/model),'action':'plan','script':'One scene. Two scenes.','animation_mode':'full','animate_model':model}
            validate('animate',payload,{})
            studio(payload,{},threading.Event(),animated=True,emit=lambda **e:None)
            saved=read(Path(payload['project'])/'project.json');self.assertEqual(saved['options']['animation_mode'],'full');self.assertEqual(saved['options']['animate_model'],model)
            studio({'project':payload['project'],'action':'plan'}, {},threading.Event(),animated=True,emit=lambda **e:None)
            self.assertEqual(read(Path(payload['project'])/'project.json')['options']['animation_mode'],'full')
        with self.assertRaises(ValueError):validate('animate',{**payload,'animation_mode':'wrong'}, {})
    def test_model_is_forwarded_to_existing_agent_driver(self):
        prompt=self.root/'prompt.txt';prompt.write_text('No live generation')
        for model in VIDEO_MODELS:
            process=Mock();process.poll.return_value=0;process.returncode=0;process.stdout=io.StringIO('')
            with patch('ai_studio_animate_media.subprocess.Popen',return_value=process) as launch:
                prepare_agent_prompt({**self.config,'animate_model':model},prompt,[],threading.Event(),lambda m:None)
                args=launch.call_args.args[0];self.assertEqual(args[args.index('--video-model')+1],model);self.assertIn('--no-submit',args)

    def test_generate_missing_submits_only_verified_missing_outputs(self):
        self.scenes=self.scenes[:6];config={**self.config,'animation_mode':'full'}
        self.generate(config)
        state=read(self.root/'animate_media.json')
        for r in state['records'][:3]:
            Path(r['output']).unlink();r['status']='submitted';r.pop('asset_id',None)
        atomic_json(self.root/'animate_media.json',state)
        prepared=[];submitted=[];Agent=self.fake_agent(prepared,submitted);original=Agent.collect
        def collect(agent,records,save,on_media):
            if not prepared:raise MissingAgentOutputs('Settled grid: scenes 1, 2, 3 absent')
            return original(agent,records,save,on_media)
        Agent.collect=collect
        with patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.valid_video',side_effect=lambda p:bool(p) and Path(p).is_file()),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda c,p,*args:prepared.append(Path(p).read_text('utf-8'))):
            # Normal Build/Retry uses no special recovery flag.
            generate_agent_media(self.scenes,config,threading.Event(),lambda m:None,lambda r:None)
        self.assertEqual(len(submitted),1);self.assertEqual(submitted[0].count(' — VIDEO — '),3)
        self.assertNotIn('OUTPUT 0004',submitted[0]);self.assertNotIn('OUTPUT 0005',submitted[0]);self.assertNotIn('OUTPUT 0006',submitted[0])
        self.assertTrue(all(r['status']=='complete' for r in read(self.root/'animate_media.json')['records']))

    def test_missing_recovery_attempt_is_bounded_and_ambiguous_errors_never_replay(self):
        self.scenes=self.scenes[:6];config={**self.config,'animation_mode':'full'}
        self.generate(config);state=read(self.root/'animate_media.json')
        for r in state['records'][:3]:Path(r['output']).unlink();r['status']='submitted'
        atomic_json(self.root/'animate_media.json',state)
        prepared=[];submitted=[];Agent=self.fake_agent(prepared,submitted)
        Agent.collect=lambda *a:(_ for _ in ()).throw(RuntimeError('Unreadable identity; generation may be active'))
        with patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.valid_video',side_effect=lambda p:bool(p) and Path(p).is_file()),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda c,p,*args:prepared.append(Path(p).read_text('utf-8'))):
            with self.assertRaisesRegex(RuntimeError,'Unreadable identity'):
                generate_agent_media(self.scenes,config,threading.Event(),lambda m:None,lambda r:None)
            self.assertFalse(submitted)
            Agent.collect=lambda *a:(_ for _ in ()).throw(MissingAgentOutputs('Confirmed absent'))
            with self.assertRaises(MissingAgentOutputs):
                generate_agent_media(self.scenes,config,threading.Event(),lambda m:None,lambda r:None)
        self.assertEqual(len(submitted),1);self.assertEqual(submitted[0].count(' — VIDEO — '),3)
        saved=read(self.root/'animate_media.json')
        self.assertTrue(all(r['status']=='submitted' for r in saved['records'][:3]))
        self.assertTrue(all(r['status']=='complete' for r in saved['records'][3:]))

    def test_missing_character_chip_blocks_submit_and_retry_preserves_pending(self):
        refs=[]
        for name in ('CharacterA','CharacterB'):
            file=self.root/(name+'.jpg');Image.new('RGB',(32,32),'red').save(file);refs.append(str(file))
        config={**self.config,'references':refs,'animation_mode':'full'}
        prepared=[];submitted=[];Agent=self.fake_agent(prepared,submitted);original=Agent._batch_page
        labels=['CharacterA.jpg']
        def page(agent,ctx):
            result=original(agent,ctx);result.locator.return_value.all_text_contents.side_effect=lambda:list(labels)
            return result
        Agent._batch_page=page
        original_collect=Agent.collect
        def collect(agent,records,save,on_media):
            # No manual click in this scenario: the failed preparation produced
            # no remote outputs. Retry must verify absence before submitting.
            if not submitted:raise MissingAgentOutputs('Confirmed absent on idle grid')
            return original_collect(agent,records,save,on_media)
        Agent.collect=collect
        with patch('ai_studio_animate_media.AgentMedia',Agent),patch('ai_studio_animate_media.valid_video',side_effect=lambda p:bool(p) and Path(p).is_file()),patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=lambda c,p,*args:prepared.append(Path(p).read_text('utf-8'))):
            with self.assertRaisesRegex(RuntimeError,'missing required character'):
                generate_agent_media(self.scenes,config,threading.Event(),lambda m:None,lambda r:None)
            self.assertFalse(submitted);self.assertTrue(all(r['status']=='pending' for r in read(self.root/'animate_media.json')['records']))
            labels.append('CharacterB.jpg')
            generate_agent_media(self.scenes,config,threading.Event(),lambda m:None,lambda r:None)
        self.assertEqual(len(submitted),3);self.assertTrue(all(r['status']=='complete' for r in read(self.root/'animate_media.json')['records']))
    def test_mode_change_invalidates_old_render_and_keeps_portrait_aspect(self):
        script='\n\n'.join(s['narration'] for s in self.scenes)
        atomic_json(self.root/'project.json',{'version':3,'workflow':'animate','title':'Test','script':script,'scenes':self.scenes,'last_video':'final.mp4','options':{'animation_mode':'partial','animate_count':3,'animate_model':'Omni 1.1 Flash'}})
        (self.root/'final.mp4').write_bytes(b'Original render is preserved')
        studio({'project':str(self.root),'script':script,'action':'plan','resolution':'720x1280','animation_mode':'full'}, {},threading.Event(),animated=True,emit=lambda **e:None)
        saved=read(self.root/'project.json');self.assertFalse(saved['last_video']);self.assertEqual(saved['options']['aspect'],'9:16')
        self.assertEqual((self.root/'final.mp4').read_bytes(),b'Original render is preserved')
    def test_full_render_uses_moving_footage_after_third_scene_and_voice_clock(self):
        video=self.root/'source.mp4';run_ffmpeg(['-f','lavfi','-i','testsrc2=size=320x180:rate=25','-t','1','-c:v','libx264','-pix_fmt','yuv420p',video])
        voice=self.root/'voice.wav'
        with wave.open(str(voice),'wb') as audio:audio.setparams((1,2,16000,0,'NONE','not compressed'));audio.writeframes(b'\0\0'*16000)
        image=self.root/'thumbnail.png';Image.new('RGB',(320,180),'red').save(image)
        scenes=[{'narration':'test','video_path':str(video),'image_path':str(image),'audio_path':str(voice)} for _ in range(4)]
        options={**self.config,'animation_mode':'full','transition':'Cut','captions':False,'use_captions_tab':False,'use_transitions_tab':False,'use_effects_tab':False,'settings':{}}
        out=render_animated_video(scenes,self.root,options);duration,streams=probe(out)
        self.assertAlmostEqual(duration,4,delta=.15);self.assertEqual({s['codec_type'] for s in streams},{'video','audio'})
        timeline=read(self.root/'timeline.json');self.assertEqual(timeline['animation_mode'],'full');self.assertEqual(timeline['animated_scenes'],4)
        images=[]
        for t in (.08,.72):
            path=self.root/f'frame-{t}.png';run_ffmpeg(['-ss',str(t),'-i',self.root/'clips/shot_0003.mp4','-frames:v','1',path]);images.append(path.read_bytes())
        self.assertNotEqual(*images)
        scenes[-1].pop('video_path')
        with self.assertRaisesRegex(RuntimeError,'Scene 4 needs'):render_animated_video(scenes,self.root,options)

if __name__=='__main__':unittest.main()
