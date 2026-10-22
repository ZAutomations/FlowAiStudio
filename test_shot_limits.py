import unittest
from ai_studio_multishot import shot_instructions
class ShotLimitTests(unittest.TestCase):
 def test_default_is_two(self):
  text=shot_instructions({})
  self.assertEqual(sum(line.startswith('SHOT ') for line in text.splitlines()),2)
  self.assertIn('[0-4s]',text);self.assertIn('[4-8s]',text)
 def test_three_explicit_shots_supported(self):
  text=shot_instructions({'shots':[{'start':a,'end':b,'visual_prompt':str(a)} for a,b in [(0,3),(3,6),(6,8)]]})
  self.assertEqual(sum(line.startswith('SHOT ') for line in text.splitlines()),3)
 def test_legacy_four_actions_consolidated_without_losing_events(self):
  text=shot_instructions({'shots':[{'start':i*2,'end':i*2+2,'visual_prompt':f'Action{i}'} for i in range(4)]})
  self.assertEqual(sum(line.startswith('SHOT ') for line in text.splitlines()),2)
  for i in range(4):self.assertIn(f'Action{i}',text)
if __name__=='__main__':unittest.main()
