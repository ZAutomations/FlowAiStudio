import tempfile,threading,unittest
from pathlib import Path
from desktop.job_automation import schedule_retry,should_compile,verify_part_media
from desktop.jobs import Jobs

class JobAutomationTests(unittest.TestCase):
 def test_unlimited_retries_are_delayed_and_same_job(self):
  job={'id':'same','kind':'studio','state':'failed','payload':{'action':'images','auto_retry':True,'auto_retry_seconds':5},'result':{'old':1}}
  for n in range(1,101):
   self.assertTrue(schedule_retry(job,now=100));self.assertEqual(job['retry_at'],105);self.assertEqual(job['id'],'same');self.assertEqual(job['auto_retry_count'],n);self.assertIsNone(job['result']);job['state']='failed'
 def test_legacy_payload_defaults_to_retry(self):
  job={'kind':'studio','state':'failed','payload':{'action':'images'}}
  self.assertTrue(schedule_retry(job,now=100));self.assertEqual(job['retry_at'],110)
 def test_worker_failure_schedules_retry_end_to_end(self):
  from unittest.mock import patch
  import io
  with tempfile.TemporaryDirectory() as folder:
   jobs=Jobs.__new__(Jobs);jobs.lock=threading.RLock();jobs.directory=Path(folder);jobs.closed=False;jobs.processes={};jobs._save=lambda:None
   class Store:
    def worker_settings(self):return {}
   jobs.store=Store()
   job={'id':'legacy','kind':'studio','state':'running','payload':{'action':'images'},'settings':{},'logs':[]}
   class Process:
    stdin=io.StringIO();stdout=io.StringIO('[ERROR] temporary connection failed\n')
    def wait(self):return 1
   with patch('desktop.jobs.subprocess.Popen',return_value=Process()):jobs._run(job)
   self.assertEqual(job['state'],'queued');self.assertEqual(job['auto_retry_count'],1)
   self.assertGreater(job['retry_at'],0);self.assertIn('Auto retry 1',job['logs'][-1])
 def test_submission_persists_default_and_respects_off(self):
  with tempfile.TemporaryDirectory() as folder:
   jobs=Jobs.__new__(Jobs);jobs.lock=threading.RLock();jobs.directory=Path(folder);jobs.closed=False;jobs.items=[];jobs._save=lambda:None
   enabled=jobs.submit('studio',{'action':'images'},settings={})
   self.assertIs(enabled['payload']['auto_retry'],True)
   disabled=jobs.submit('animate',{'action':'images','auto_retry':False},settings={})
   self.assertIs(disabled['payload']['auto_retry'],False)
 def test_uncertain_submission_does_not_repeat_forever(self):
  job={'kind':'studio','state':'failed','payload':{'action':'images'},'logs':['[ERROR] ACTION REQUIRED: Existing submission remains unresolved for scene(s) 97.']}
  self.assertFalse(schedule_retry(job))
  job['logs']=['[ERROR] Flow generation request failed: Something went wrong.']
  self.assertTrue(schedule_retry(job,now=10))
 def test_stop_and_disabled_and_completed_never_retry(self):
  for patch in ({'retry_disabled':True},{'state':'stopped'},{'state':'completed'},{'payload':{'auto_retry':False}},{'payload':{'auto_retry':True,'action':'import-ready-animation'}}):
   job={'kind':'studio','state':'failed','payload':{'action':'images','auto_retry':True},**patch}
   self.assertFalse(schedule_retry(job))
  self.assertFalse(schedule_retry({'kind':'studio','state':'failed','payload':{'auto_retry':True}},closed=True))
 def test_stop_during_retry_delay(self):
  with tempfile.TemporaryDirectory() as folder:
   jobs=Jobs.__new__(Jobs);jobs.lock=threading.RLock();jobs.directory=Path(folder);jobs._save=lambda:None
   jobs.items=[{'id':'same','state':'queued','retry_at':999,'payload':{'auto_retry':True}}]
   jobs.stop('same');self.assertEqual(jobs.items[0]['state'],'stopped');self.assertTrue(jobs.items[0]['retry_disabled'])
 def test_compile_requires_all_selected_files(self):
  from PIL import Image
  with tempfile.TemporaryDirectory() as folder:
   file=Path(folder)/'scene.png';Image.new('RGB',(100,100),'red').save(file)
   scenes=[{'image_path':''},{'image_path':str(file)},{'image_path':str(file)}]
   self.assertEqual(verify_part_media(scenes,{'scene_start':2,'scene_end':3}),(2,3))
   with self.assertRaisesRegex(ValueError,'missing/invalid'):verify_part_media(scenes,{'scene_start':1,'scene_end':3})
 def test_compile_not_on_partial_scan_without_media_verification(self):
  self.assertTrue(should_compile({'action':'download-all-images','auto_compile_part':True}))
  self.assertFalse(should_compile({'action':'build','auto_compile_part':True}))
  self.assertFalse(should_compile({'action':'images','auto_compile_part':True},review_required=True))
if __name__=='__main__':unittest.main()
