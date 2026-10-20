import unittest
from ai_studio_image_models import quota_models,batch_instructions
class ModelMemoryTests(unittest.TestCase):
 def test_common_agent_quota_reports(self):
  for text in ["The daily quota for Nano Banana Pro has been reached.","Nano Banana Pro usage limit reached.","Reached the daily quota for Nano Banana Pro. Switching to Nano Banana 2.1."]:
   self.assertEqual(quota_models(text),('Nano Banana Pro',))
 def test_skips_exhausted_even_when_gui_still_selects_pro(self):
  text=batch_instructions(dict(agent_image_model='Nano Banana Pro',exhausted_image_models=['Nano Banana Pro']))
  self.assertIn('Start this batch with Nano Banana 2.1',text)
  self.assertIn('do not try them again',text)
 def test_offered_alternative_is_not_marked_exhausted(self):
  self.assertEqual(quota_models('Pro is unavailable. Try Nano Banana 2.1 instead.'),())
if __name__=='__main__':unittest.main()
