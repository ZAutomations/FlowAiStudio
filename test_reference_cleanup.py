import tempfile,json,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_studio_reference_cleanup import cleanup_plan,clean_generated_references
class ReferenceCleanupTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'references').mkdir()
  self.image=self.root/'references/DSP.png';Image.new('RGB',(40,40)).save(self.image)
  (self.root/'references/reference_plan.json').write_text(json.dumps({'references':[{'name':'DSP'}]}))
  (self.root/'reference_agent_media.json').write_text(json.dumps({'records':[{'name':'DSP','asset_id':'ref1','token':'AS_SCENE_abcd'}]}))
  self.config={'project':str(self.root),'flow_url':'https://flow.google.com/project/test','references':[str(self.image)],'agent_tool_dir':str(self.root)}
 def test_missing_local_reference_prevents_cleanup(self):
  self.config['references']=[str(self.root/'absent.png')]
  with self.assertRaisesRegex(ValueError,'valid on disk'):cleanup_plan(self.config)
 def test_incomplete_library_prevents_cleanup(self):
  (self.root/'references/reference_plan.json').write_text(json.dumps({'references':[{'name':'DSP'},{'name':'Station'}]}))
  with self.assertRaisesRegex(ValueError,'complete renamed'):cleanup_plan(self.config)
 def test_scene_asset_overlap_prevents_cleanup(self):
  (self.root/'animate_media.json').write_text(json.dumps({'records':[{'asset_id':'ref1','token':'AS_SCENE_scene'}]}))
  with self.assertRaisesRegex(ValueError,'scene asset'):cleanup_plan(self.config)
 def test_completed_same_library_cleanup_is_not_repeated(self):
  plan=cleanup_plan(self.config);(self.root/'references/library_cleanup.json').write_text(json.dumps({**plan,'complete':True}))
  page=object()
  with patch('ai_studio_animate_media.AgentMedia') as inspector:
   clean_generated_references(page,self.config,threading.Event(),lambda text:None)
   inspector.assert_not_called()
 def test_only_reference_copies_removed_and_cleanup_receipt_saved(self):
  from unittest.mock import Mock
  (self.root/'animate_media.json').write_text(json.dumps({'records':[{'asset_id':'scene1','token':'AS_SCENE_scene'}]}))
  assets=[dict(asset_id=i,kind=k,visible=True,busy=False,failed=False,src='') for i,k in [('ref1','image'),('named1','image'),('scene1','image'),('clip1','video')]]
  inspector=Mock();inspector._scene_grid_position.return_value={'top':0,'height':100,'client':100}
  inspector._agent_assets.side_effect=lambda page:list(assets)
  inspector._asset_prompt.side_effect=lambda page,a:'FLOW_REFERENCE:DSP.png' if a['asset_id']=='named1' else ''
  page=Mock();page.get_by_role.return_value.count.return_value=0;page.get_by_role.return_value.evaluate_all.return_value=False
  removed=[]
  def remove(page,asset,cancel):
   removed.append(asset);assets[:]=[a for a in assets if a['asset_id']!=asset]
  with patch('ai_studio_animate_media.AgentMedia',return_value=inspector),patch('ai_studio_reference_cleanup.remove_one',side_effect=remove):
   clean_generated_references(page,self.config,threading.Event(),lambda text:None)
  self.assertEqual(removed,['ref1','named1'])
  self.assertEqual({a['asset_id'] for a in assets},{'scene1','clip1'})
  self.assertTrue(json.loads((self.root/'references/library_cleanup.json').read_text())['complete'])
  self.assertTrue(self.image.exists())
 def test_cleanup_plan_retains_all_local_files(self):
  before=self.image.read_bytes();plan=cleanup_plan(self.config)
  self.assertEqual(plan['asset_ids'],['ref1']);self.assertEqual(self.image.read_bytes(),before)
if __name__=='__main__':unittest.main()
