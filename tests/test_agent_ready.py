import unittest
import threading
from unittest.mock import Mock,patch
from ai_studio_animate_media import wait_agent_ready

class AgentReadyTests(unittest.TestCase):
    def test_slow_controls_are_rechecked_without_clicking(self):
        page=Mock();page.evaluate.side_effect=[False,False,True]
        with patch('ai_studio_animate_media.time.sleep'):
            wait_agent_ready(page,threading.Event(),Mock())
        self.assertEqual(page.evaluate.call_count,3)
        page.locator.assert_not_called()

    def test_unready_controls_fail_without_submission(self):
        page=Mock();page.evaluate.return_value=False
        with self.assertRaisesRegex(RuntimeError,'No generation submitted'):
            wait_agent_ready(page,threading.Event(),Mock(),timeout=0)
        page.locator.assert_not_called()

    def test_cancel_stops_waiting(self):
        page=Mock();cancel=threading.Event();cancel.set()
        with self.assertRaises(Exception):wait_agent_ready(page,cancel,Mock())
        page.evaluate.assert_not_called()

class BatchProgressTests(unittest.TestCase):
    def test_marks_follow_verified_generation_and_download(self):
        from ai_studio_animate_media import update_batch_progress
        state={'records':[{'token':'a','status':'matched'},{'token':'b','status':'submitted'}],
            'batch_progress':{'batch':{'tokens':['a','b']}}}
        marks=state['batch_progress']['batch']
        update_batch_progress(state)
        self.assertFalse(marks['generated_successfully'])
        state['records'][1]['status']='matched'
        update_batch_progress(state)
        self.assertTrue(marks['generated_successfully'])
        self.assertFalse(marks['downloaded_successfully'])
        for r in state['records']:r['status']='complete'
        update_batch_progress(state)
        self.assertTrue(marks['downloaded_successfully'])
        state['records'][1]['status']='submitted'
        update_batch_progress(state)
        self.assertFalse(marks['downloaded_successfully'])
