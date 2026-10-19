import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import gemini_api_tts_helper as tts

class TTSRecoveryTests(unittest.TestCase):
    def test_http_response_is_not_submitted_again_via_urllib(self):
        with patch.object(tts,'_try_requests',return_value=(False,None,'HTTP 400: INVALID_ARGUMENT')),patch.object(tts,'_try_urllib') as fallback:
            self.assertFalse(tts._http_post('https://example',{})[0])
            fallback.assert_not_called()
    def test_transport_failure_can_use_urllib(self):
        with patch.object(tts,'_try_requests',return_value=(False,None,'requests library not available')),patch.object(tts,'_try_urllib',return_value=(True,{},'')) as fallback:
            self.assertTrue(tts._http_post('https://example',{})[0]);fallback.assert_called_once()
    def synthesize(self,error,success=False):
        prompt='Keep the DSP voice calm. Keep one consistent narrator identity across the video. This is the middle. Read ONLY the supplied narration verbatim. Additional delivery direction: Speak softly.'
        responses=[(False,b'',error)]+([(True,b'audio','')] if success else [(False,b'',error)])
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder,patch.object(tts,'_call_gemini_cloud_tts',side_effect=responses) as call,patch.object(tts,'_extract_pcm',return_value=(b'\0\0'*2400,24000,1,2)),patch.object(tts.time,'sleep') as sleep:
            result=tts.generate_speech('Original narration.',Path(folder)/'voice.wav',{'service_account_path':'saved.json','gemini_tts_prompt':prompt,'gemini_tts_voice':'Orus','gemini_tts_model':'saved-model'})
            sleep.assert_not_called()
            return result,call.call_args_list
    def test_compact_recovery_keeps_text_model_voice_and_custom_direction(self):
        result,calls=self.synthesize('HTTP 400: {"status":"INVALID_ARGUMENT"}',True)
        self.assertTrue(result[0]);self.assertEqual(len(calls),2)
        self.assertEqual(calls[0].args,calls[1].args)
        self.assertIn('Keep the DSP voice calm.',calls[1].kwargs['prompt'])
        self.assertIn('Speak softly.',calls[1].kwargs['prompt'])
    def test_permanent_invalid_request_stops_after_one_compact_recovery(self):
        result,calls=self.synthesize('HTTP 400: {"status":"INVALID_ARGUMENT"}')
        self.assertFalse(result[0]);self.assertEqual(len(calls),2)
    def test_safety_refusal_is_not_reprompted(self):
        result,calls=self.synthesize('HTTP 400: INVALID_ARGUMENT: safety policy blocked')
        self.assertFalse(result[0]);self.assertEqual(len(calls),1)
    def test_custom_prompt_is_not_rewritten(self):
        self.assertEqual(tts._compact_studio_delivery('User custom delivery instruction.'),'')

if __name__=='__main__':unittest.main()
