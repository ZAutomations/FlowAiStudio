import unittest
from unittest.mock import patch
from ai_studio_narration_quality import repeated_passages,validate_narration
from ai_studio_cinematic import measured_words

class StoryQualityTests(unittest.TestCase):
    def test_long_repeated_filler_stops_before_generation(self):
        phrase='The officer wrote down every detail in his notebook before questioning the witness.'
        with self.assertRaisesRegex(ValueError,'3 times'):
            validate_narration(' '.join([phrase]*3))
    def test_urdu_repetition_detected(self):
        phrase='میں نے اس مرحلے پر اپنی نوٹ بک میں دو باتیں الگ درج کیں۔'
        self.assertEqual(repeated_passages(' '.join([phrase]*4))[0]['count'],4)
    def test_short_dialogue_and_two_occurrences_are_preserved(self):
        validate_narration('Yes! Yes! Yes!')
        validate_narration('The officer wrote down every detail in his notebook before questioning the witness. '*2)
    def test_each_source_word_stays_in_its_own_measured_audio(self):
        scenes=[]
        for n in range(3):
            text='The officer checked the register and spoke to the witness.'
            words=text.split()
            scenes.append({'narration':text,'audio_path':str(n),'word_timings':[{'word':w,'offset':i*.5,'duration':.3} for i,w in enumerate(words)]})
        with patch('ai_studio_cinematic.probe',return_value=(8,[])):
            words,durations=measured_words(scenes)
        count=len(scenes[0]['narration'].split())
        for n in range(3):
            for word in words[n*count:(n+1)*count]:
                self.assertGreaterEqual(word['offset'],n*8)
                self.assertLess(word['offset'],(n+1)*8)
        self.assertEqual(durations,[8,8,8])

if __name__=='__main__':unittest.main()
