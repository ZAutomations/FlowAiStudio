import copy,unittest
from ai_studio_animate_media import compact_image_records
class CompactBatchTests(unittest.TestCase):
 def test_exact_shared_lines_only_and_identities_unchanged(self):
  style='Visual style: '+('period illustration ' * 40)
  rows=[dict(kind='image',index=i,key=str(i),token='AS_SCENE_'+str(i),prompt='Unique scene '+str(i)+'\n'+style,reference_names=['DSPMalik']) for i in range(24)]
  original=copy.deepcopy(rows);short,shared=compact_image_records(rows)
  self.assertEqual(rows,original);self.assertEqual(shared,[style])
  for a,b in zip(rows,short):
   self.assertEqual(a['token'],b['token']);self.assertEqual(a['key'],b['key']);self.assertIn('Unique scene',b['prompt'])
  self.assertLess(sum(len(r['prompt']) for r in short)+len(style),sum(len(r['prompt']) for r in rows))
 def test_video_and_single_requests_unchanged(self):
  for rows in ([{'kind':'video','prompt':'x'}]*2,[{'kind':'image','prompt':'x'}]):
   self.assertEqual(compact_image_records(rows),(rows,[]))
if __name__=='__main__':unittest.main()
