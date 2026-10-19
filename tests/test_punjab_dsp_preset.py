import unittest
from ai_studio_pipeline import STYLE_PRESETS
from ai_studio_story import PUNJAB_DSP_STYLE,PUNJAB_DSP_DIRECTION,is_narration_story,narration_direction
from ai_studio_narration import resolve,settings_for
from ai_studio_animate_options import reference_mode
from desktop.studio import metadata

class PunjabDSPTests(unittest.TestCase):
    def test_shared_preset_has_period_locks_and_case_narration(self):
        self.assertIn(PUNJAB_DSP_STYLE,metadata({})['styles'])
        prompt=STYLE_PRESETS[PUNJAB_DSP_STYLE]
        self.assertIn('hand-painted',prompt);self.assertIn('Before 1947',prompt)
        self.assertIn('after 1947',prompt);self.assertIn('No smartphones',prompt)
        self.assertIn('Do not invent evidence',prompt)
        c={'style_name':PUNJAB_DSP_STYLE}
        self.assertTrue(is_narration_story(c));self.assertEqual(narration_direction(c),PUNJAB_DSP_DIRECTION)
        self.assertEqual(reference_mode(c),'characters')

    def test_auto_gemini_voice_uses_officer_memoir_and_preserves_voice(self):
        c={'style_name':PUNJAB_DSP_STYLE,'narration_style':'auto','voice_engine':'google_cloud',
           'settings':{'gemini_tts_voice':'Orus'},'title':'A village mystery','script':'Original narration.'}
        self.assertEqual(resolve(c),'dsp_memoir')
        s,_=settings_for(c)
        self.assertEqual(s['gemini_tts_voice'],'Orus');self.assertIn('retired police officer',s['gemini_tts_prompt'])
        self.assertEqual(resolve({**c,'narration_style':'documentary'}),'documentary')

    def test_colormix_reuses_cast_only_when_original_source_matches(self):
        import json,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from ai_studio_cast import current,source_key
        from ai_studio_story import PUNJAB_DSP_COLORMIX_STYLE
        with tempfile.TemporaryDirectory() as directory:
            scenes=[{'narration':'Original scene.'}]
            old={'project':directory,'script':'Original story.','style':STYLE_PRESETS[PUNJAB_DSP_STYLE]}
            data={'source_key':source_key(old,scenes),'approved':True}
            Path(directory,'cast_analysis.json').write_text(json.dumps(data),encoding='utf-8')
            new={**old,'style_name':PUNJAB_DSP_COLORMIX_STYLE,'style':STYLE_PRESETS[PUNJAB_DSP_COLORMIX_STYLE]}
            with patch('ai_studio_cast.validate'):
                self.assertEqual(current(new,scenes,approved=True),data)
                self.assertEqual(new['_dsp_previous_style'],old['style'])
                with self.assertRaises(ValueError):current({**new,'script':'Changed story.'},scenes)

if __name__=='__main__':unittest.main()
