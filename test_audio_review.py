import json,queue,tempfile,threading,unittest,wave
from pathlib import Path
from unittest.mock import patch
from ai_studio_pipeline import atomic_json,fingerprint
from ai_studio_audio_review import targeted_repair,save_review,review_data,preview

class AudioReviewTests(unittest.TestCase):
 def fixture(self,folder):
  root=Path(folder)/'voice/imported/1234567890abcdef';root.mkdir(parents=True)
  pcm=root/'narration.wav'
  with wave.open(str(pcm),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*32000)
  scenes=[{'narration':'one two'},{'narration':'three four'}]
  atomic_json(Path(folder)/'project.json',{'scenes':scenes,'options':{}})
  atomic_json(root.parent/'active_alignment.json',{'cache':root.name})
  return root,pcm,scenes
 def test_only_short_repair_cached_and_reused(self):
  with tempfile.TemporaryDirectory() as folder:
   root,pcm,scenes=self.fixture(folder);calls=[]
   words=[{'word':w,'offset':i,'duration':.5} for i,w in enumerate('one two three four'.split())]
   def recognize(*args):calls.append(args[0]);return words
   with patch('ai_studio_audio_review.partial_boundaries',return_value=[0,None,4]):
    bounds,_=targeted_repair(scenes,[words],4,pcm,root,'small',recognize,threading.Event(),lambda m:None)
   self.assertEqual(bounds,[0,1.75,4]);self.assertEqual(len(calls),1);self.assertIn('repair_',calls[0].name)
   with patch('ai_studio_audio_review.partial_boundaries',return_value=[0,None,4]):
    targeted_repair(scenes,[words],4,pcm,root,'small',recognize,threading.Event(),lambda m:None)
   self.assertEqual(len(calls),1)
 def test_manual_review_rejects_invalid_and_locks_verified(self):
  with tempfile.TemporaryDirectory() as folder:
   root,pcm,scenes=self.fixture(folder)
   data={'scene_key':fingerprint([s['narration'] for s in scenes]),'coverage_verified':True,'duration':4,'boundaries':[0,None,4],'unresolved':[{'boundary':1,'earliest':0,'latest':4}]}
   atomic_json(root/'boundary_review.json',data)
   for value in [float('nan'),-1,4,True]:
    with self.assertRaises(ValueError):save_review(folder,{'1':value})
   with self.assertRaises(ValueError):save_review(folder,{'0':1})
   self.assertTrue(preview(folder,1)['audio'].startswith('data:audio/wav;base64,'))
   self.assertEqual(save_review(folder,{'1':2})['remaining'],0)
   self.assertEqual(review_data(folder)['manual'],{'1':2})
 def test_coverage_failure_cannot_be_manually_overridden(self):
  with tempfile.TemporaryDirectory() as folder:
   root,pcm,scenes=self.fixture(folder)
   with self.assertRaisesRegex(ValueError,'coverage failed'):
    targeted_repair(scenes,[[{'word':'different','offset':0,'duration':1}]],4,pcm,root,'small',lambda *a:[],threading.Event(),lambda m:None)
   with self.assertRaisesRegex(ValueError,'mismatch'):save_review(folder,{'1':2})
if __name__=='__main__':unittest.main()
