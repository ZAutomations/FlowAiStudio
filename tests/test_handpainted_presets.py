import unittest
from ai_studio_pipeline import STYLE_PRESETS
from ai_studio_story import (HANDPAINTED_DOCUMENTARY_STYLE,HANDPAINTED_RELATIONSHIP_STYLE,
                            DOCUMENTARY_DIRECTION,SILENT_DIRECTION,is_narration_story,narration_direction)
from ai_studio_animate_options import reference_mode
from desktop.studio import metadata

class HandpaintedPresetsTests(unittest.TestCase):
    def test_presets_inherit_workflow_and_reference_rules(self):
        for name,direction,refs in ((HANDPAINTED_DOCUMENTARY_STYLE,DOCUMENTARY_DIRECTION,'none'),
                                     (HANDPAINTED_RELATIONSHIP_STYLE,SILENT_DIRECTION,'characters')):
            with self.subTest(name=name):
                self.assertIn(name,metadata({})['styles'])
                prompt=STYLE_PRESETS[name]
                self.assertIn('watercolor paper',prompt);self.assertIn('fine graphite',prompt)
                self.assertIn(direction,prompt)
                config={'style_name':name,'reference_files':'stale.png'}
                self.assertTrue(is_narration_story(config));self.assertEqual(narration_direction(config),direction)
                self.assertEqual(reference_mode(config),refs)
        self.assertEqual(reference_mode({'style_name':HANDPAINTED_DOCUMENTARY_STYLE,'reference_mode':'characters'}),'characters')

if __name__=='__main__':unittest.main()
