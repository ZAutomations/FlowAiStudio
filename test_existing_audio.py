import copy,queue,tempfile,threading,unittest,wave
from pathlib import Path
from types import SimpleNamespace
from ai_studio_existing_audio import generate,verify,recover_saved_boundaries

class ExistingAudioTests(unittest.TestCase):
 def test_import_resume_and_sample_exact_scene_join(self):
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.wav'
   with wave.open(str(source),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\x01\x00'*96000)
   original=source.read_bytes()
   rows=[{'narration':'one two'},{'narration':'three four'}]
   a=SimpleNamespace(zb_scenes=copy.deepcopy(rows),_zb_cancel=threading.Event(),_zb_save_project=lambda c:None)
   config={'project':d,'existing_audio_path':str(source),'script':'one two three four','narration_alignment_model':'base'}
   calls=[]
   def recognize(*args):
    calls.append(1);return [{'word':v,'offset':i*.5,'duration':.4} for i,v in enumerate('one two three four'.split())]
   generate(a,queue.Queue(),config,recognize)
   self.assertEqual(len(calls),1)
   joined=b''
   for row in a.zb_scenes:
    with wave.open(row['audio_path'],'rb') as f:joined+=f.readframes(f.getnframes())
   with wave.open(str(source),'rb') as f:self.assertEqual(joined,f.readframes(f.getnframes()))
   generate(a,queue.Queue(),config,recognize)
   self.assertEqual(len(calls),1);self.assertEqual(source.read_bytes(),original)
 def test_complementary_recovery_requires_global_coverage(self):
  from unittest.mock import patch
  good=[{'word':'verified'}];other=[{'word':'other'}]
  with patch('ai_studio_existing_audio.verify_coverage',side_effect=[(.95,.95),ValueError('mismatch')]), patch('ai_studio_continuous_voice.combine_verified_boundaries',return_value=([0,1],good)) as combine:
   self.assertEqual(recover_saved_boundaries([], [other,good],1),([0,1],good))
   self.assertEqual(combine.call_args.args[1],[other,good])
  with patch('ai_studio_existing_audio.verify_coverage',side_effect=ValueError('mismatch')):
   with self.assertRaisesRegex(ValueError,'coverage'):recover_saved_boundaries([], [good,other],1)
 def test_repeated_recording_rejected(self):
  rows=[{'narration':'one two three four'}]
  words=[{'word':v,'offset':i*.2,'duration':.1} for i,v in enumerate(('one two three four '*2).split())]
  with self.assertRaisesRegex(ValueError,'mismatch'):verify(rows,words,3)
 def test_missing_passages_rejected(self):
  with self.assertRaisesRegex(ValueError,'mismatch'):verify([{'narration':'one two three four five six'}],[{'word':'one','offset':0,'duration':.3}],3)
 def test_generated_project_not_retimed(self):
  with tempfile.TemporaryDirectory() as d:
   file=Path(d)/'audio.wav';file.write_bytes(b'not needed')
   rows=[{'narration':'one','image_path':'saved.png','audio_key':'old'}]
   a=SimpleNamespace(zb_scenes=copy.deepcopy(rows))
   with self.assertRaisesRegex(ValueError,'fresh project'):generate(a,queue.Queue(),{'project':d,'existing_audio_path':str(file)})
   self.assertEqual(a.zb_scenes,rows)
if __name__=='__main__':unittest.main()
