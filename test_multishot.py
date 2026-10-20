import copy,unittest
from ai_studio_multishot import shot_instructions
from ai_studio_animate_media import batch_prompt
from ai_studio_animate_prompts import master_prompt,split_master_prompt

class MultiShotTests(unittest.TestCase):
 def test_explicit_three_shots_keep_actions_and_record_identity(self):
  r=dict(index=0,kind='video',token='AS_SCENE_saved',key='locked-key',prompt='A detective examines a box.',shots=[dict(start=0,end=3,visual_prompt='Wide: detective enters the room.'),dict(start=3,end=6,visual_prompt='Close: hands open the box.'),dict(start=6,end=8,visual_prompt='Insert: the empty box interior.')])
  before=copy.deepcopy(r)
  text=batch_prompt([r],dict(animate_model='Omni 1.1 Flash',animate_clip_seconds=8,animate_multishot=True))
  self.assertIn('SHOT 2 [3-6s] HARD CUT',text);self.assertIn('hands open the box',text)
  self.assertIn('SHOT 3 [6-8s]',text);self.assertEqual(r,before)
 def test_legacy_missing_or_invalid_shots_get_three_local_directions(self):
  for shots in [None,[],[dict(start=0,end=8,visual_prompt='Only one shot')],[dict(start=0,end=2),dict(start=4,end=8)]]:
   text=shot_instructions(dict(shots=shots))
   self.assertIn('SHOT 1 [0-3s]',text);self.assertIn('SHOT 2 [3-6s]',text);self.assertIn('SHOT 3 [6-8s]',text)
 def test_all_animation_master_prompts_explain_visible_cuts(self):
  for text in [master_prompt('partial'),master_prompt('full'),split_master_prompt()]:
   self.assertIn('HARD CUT',text.upper());self.assertIn('2-3',text.replace('–','-'))
 def test_images_never_receive_edit_decision_list(self):
  text=batch_prompt([dict(index=0,kind='image',token='AS_SCENE_image',prompt='A still image.')],dict(animate_model='Omni 1.1 Flash'))
  self.assertNotIn('EDIT DECISION LIST',text)

if __name__=='__main__':unittest.main()
