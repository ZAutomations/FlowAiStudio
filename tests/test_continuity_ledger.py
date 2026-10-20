import copy,json,queue,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from ai_studio_pipeline import atomic_json,fingerprint
from ai_studio_continuity_ledger import build,save_review,prompt_context
from ai_studio_animate_media import media_plan,batch_prompt


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.root=Path(self.tmp.name)
        lines=['DSP holds the red file, looking worried.','DSP has a bruised left hand.','DSP passes the red file to Ali.',
               'DSP discovers the hidden letter.','Ali stands quietly beside the door.']
        self.scenes=[dict(id=i+1,narration=t,visual_prompt=t,cinematic_kind='video',cinematic_start=i*8,cinematic_end=(i+1)*8) for i,t in enumerate(lines)]
        self.config=dict(project=str(self.root),script=' '.join(lines),style='Handpainted',title='Case',character_names='DSP,Ali',
                         animation_mode='full',animate_model='Veo 3.1 - Lite',animate_clip_seconds=8,animate_narration_mode='cinematic',
                         resolution='1920x1080',continuity_ledger_enabled=True,flow_url='https://flow.google.com/project/test')
        self.updates=[
            [dict(section='props',id='RedFile',fields=dict(description='Red case file',holder='DSP'),evidence='DSP holds the red file'),dict(section='characters',id='DSP',fields=dict(emotion='worried'),evidence='looking worried')],
            [dict(section='characters',id='DSP',fields=dict(injuries='bruised left hand'),evidence='bruised left hand')],
            [dict(section='props',id='RedFile',fields=dict(holder='Ali'),evidence='passes the red file to Ali')],
            [dict(section='clues',id='HiddenLetter',fields=dict(description='hidden letter',status='discovered',known_by=['DSP']),evidence='DSP discovers the hidden letter')],[]]
        def llm(system,user,**kwargs):return json.dumps([dict(clip=r['clip'],updates=self.updates[r['clip']-1]) for r in json.loads(user)['clips']]),None
        self.adapter=SimpleNamespace(zb_scenes=self.scenes,_zb_cancel=threading.Event(),_zb_llm=Mock(side_effect=llm),_zb_save_project=Mock())
    def tearDown(self):self.tmp.cleanup()
    def test_carries_props_injuries_emotions_and_clues_without_touching_existing_work(self):
        for name in ['narration.wav','storyboard.json','scene_0001.png','project.json']:(self.root/name).write_bytes(b'existing work '+name.encode())
        before={p.name:p.read_bytes() for p in self.root.iterdir()};source=copy.deepcopy(self.scenes);keys=[r['key'] for r in media_plan(self.scenes,self.config)]
        ledger=build(self.adapter,queue.Queue(),self.config);last=ledger['entries'][-1]['after']
        self.assertEqual(last['props']['RedFile']['holder'],'Ali');self.assertEqual(last['characters']['DSP']['injuries'],'bruised left hand')
        self.assertEqual(last['characters']['DSP']['emotion'],'worried');self.assertEqual(last['clues']['HiddenLetter']['known_by'],['DSP'])
        self.assertEqual(self.scenes,source);self.assertEqual([r['key'] for r in media_plan(self.scenes,self.config)],keys)
        for name,content in before.items():self.assertEqual((self.root/name).read_bytes(),content)
        self.adapter._zb_save_project.assert_not_called()
        text=batch_prompt(media_plan(self.scenes,self.config)[:1],self.config)
        self.assertIn('DETAILED CONTINUITY LEDGER',text);self.assertIn('RedFile',text)
        calls=self.adapter._zb_llm.call_count;build(self.adapter,queue.Queue(),self.config);self.assertEqual(self.adapter._zb_llm.call_count,calls)
    def test_ready_json_uses_local_state_without_any_gemini_calls(self):
        self.config['planning_source']='chatgpt_ready'
        for scene in self.scenes:scene['cinematic_continuity']=dict(location='Station',start_state='At doorway',end_state='At desk',continues_previous=False)
        result=build(self.adapter,queue.Queue(),self.config)
        self.adapter._zb_llm.assert_not_called()
        self.assertEqual(result['entries'][-1]['after']['scene']['planned_state'],'At desk')
        self.assertEqual(result['entries'][-1]['after']['props'],{})

    def test_retry_resumes_only_unfinished_metadata(self):
        original=self.adapter._zb_llm.side_effect;count=0
        def fail(system,user,**kw):
            nonlocal count
            count+=1
            return ('','temporary API failure') if count==2 else original(system,user,**kw)
        self.adapter._zb_llm.side_effect=fail
        with self.assertRaisesRegex(RuntimeError,'paused'):build(self.adapter,queue.Queue(),self.config)
        self.assertEqual(len(json.loads((self.root/'continuity_ledger.json').read_text('utf-8'))['entries']),4)
        self.adapter._zb_llm=Mock(side_effect=original);build(self.adapter,queue.Queue(),self.config)
        self.assertEqual([r['clip'] for r in json.loads(self.adapter._zb_llm.call_args.args[1])['clips']],[5])
    def test_imported_updates_skip_llm_and_images_need_no_ledger(self):
        for scene,updates in zip(self.scenes,self.updates):scene['continuity_updates']=updates
        build(self.adapter,queue.Queue(),self.config);self.adapter._zb_llm.assert_not_called()
        (self.root/'continuity_ledger.json').unlink()
        self.assertEqual(prompt_context([dict(kind='image')],self.config),'')
    def test_invented_state_or_unknown_character_rejected(self):
        self.scenes[0]['continuity_updates']=[dict(section='characters',id='Stranger',fields={'emotion':'angry'},evidence='DSP holds the red file')]
        for scene in self.scenes[1:]:scene['continuity_updates']=[]
        with self.assertRaisesRegex(ValueError,'approved cast'):build(self.adapter,queue.Queue(),self.config)
        self.scenes[0]['continuity_updates']=[dict(section='characters',id='DSP',fields={'injuries':'broken leg'},evidence='A nonexistent event')]
        with self.assertRaisesRegex(ValueError,'exact supporting'):build(self.adapter,queue.Queue(),self.config)
        self.assertFalse((self.root/'continuity_ledger.json').exists())
    def test_issued_updates_lock_but_upcoming_updates_edit_without_media_reset(self):
        ledger=build(self.adapter,queue.Queue(),self.config)
        atomic_json(self.root/'animate_media.json',{'records':[dict(index=0,status='submitted',token='AS_SCENE_old')]})
        original=(self.root/'animate_media.json').read_bytes();edits=copy.deepcopy(ledger)
        edits['entries'][0]['updates']=[]
        with self.assertRaisesRegex(ValueError,'locked'):save_review(self.adapter,queue.Queue(),self.config,edits)
        edits=copy.deepcopy(ledger);edits['entries'][-1]['updates']=[dict(section='characters',id='Ali',fields={'emotion':'quiet'},evidence='stands quietly')]
        save_review(self.adapter,queue.Queue(),self.config,edits)
        self.assertEqual(json.loads((self.root/'continuity_ledger.json').read_text('utf-8'))['entries'][-1]['after']['characters']['Ali']['emotion'],'quiet')
        self.assertEqual((self.root/'animate_media.json').read_bytes(),original)
    def test_worker_ledger_action_reuses_plan_and_never_runs_voice_or_media(self):
        from desktop.worker import studio
        from unittest.mock import patch
        from ai_studio_pipeline import STYLE_PRESETS
        atomic_json(self.root/'project.json',dict(title='Case',script=self.config['script'],scenes=self.scenes,options={**self.config,'style_name':'Cinematic realistic','style':STYLE_PRESETS['Cinematic realistic'],'voice_engine':'google_cloud'}))
        synth='ai_studio_animate.AnimateStudio._zb_voice_pass'
        with patch(synth) as voice,patch('ai_studio_animate.AnimateStudio._zb_images_pass') as media,patch('ai_studio_animate.AnimateStudio._zb_llm',side_effect=self.adapter._zb_llm.side_effect):
            result=studio(dict(project=str(self.root),action='continuity-ledger'),{},threading.Event(),animated=True,emit=lambda **e:None)
        voice.assert_not_called();media.assert_not_called();self.assertEqual(result['scenes'],5)
        self.assertEqual(json.loads((self.root/'project.json').read_text('utf-8'))['scenes'],self.scenes)


if __name__=='__main__':unittest.main()
