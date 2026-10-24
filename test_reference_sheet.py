import unittest
from ai_studio_reference_agent import sheet_prompt
class ReferenceSheetTests(unittest.TestCase):
 def test_all_presets_and_kinds_share_four_view_contract(self):
  for style in ('DSP','handpainted','documentary','realistic'):
   for kind,detail in [('character','face close-up'),('location','reverse angle'),('prop','rear view')]:
    prompt=sheet_prompt({'kind':kind,'prompt':'Style: '+style+'; one person only; neutral pose'})
    self.assertIn('exactly FOUR',prompt);self.assertIn(detail,prompt)
    self.assertIn('ABSOLUTELY NO VISIBLE TEXT',prompt);self.assertIn('not a story scene',prompt)
 def test_manual_records_use_reference_kind(self):
  self.assertIn('reverse angle',sheet_prompt({'reference_kind':'location','kind':'image','prompt':'design'}))
if __name__=='__main__':unittest.main()
