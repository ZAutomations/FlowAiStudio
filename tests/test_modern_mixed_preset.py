import unittest
from ai_studio_pipeline import STYLE_PRESETS
from ai_studio_story import MODERN_MIXED_STORY_STYLE,MODERN_MIXED_STORY_DIRECTION,is_narration_story,narration_direction
from desktop.studio import metadata
from ai_studio_narration import resolve

class ModernMixedPresetTests(unittest.TestCase):
    def test_preset_is_available_and_has_modern_painterly_realistic_style(self):
        self.assertIn(MODERN_MIXED_STORY_STYLE,metadata({})['styles'])
        prompt=STYLE_PRESETS[MODERN_MIXED_STORY_STYLE]
        for phrase in ('hyperrealistic','hand-painted','fully colored modern','No generated voice-over'):
            self.assertIn(phrase,prompt)
    def test_story_narration_is_silent_and_does_not_force_dsp(self):
        c={'style_name':MODERN_MIXED_STORY_STYLE,'narration_style':'auto'}
        self.assertTrue(is_narration_story(c))
        self.assertEqual(narration_direction(c),MODERN_MIXED_STORY_DIRECTION)
        self.assertEqual(resolve(c),'storytelling')
        self.assertIn('Never invent evidence',MODERN_MIXED_STORY_DIRECTION)
