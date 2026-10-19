"""Account selection is public job metadata; credentials remain rejected."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from desktop.jobs import Jobs
from desktop.storage import Store, atomic, public, read


class AccountPayloadTests(unittest.TestCase):
    def test_login_and_reference_jobs_accept_account_selection(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);atomic(root/'overlay_settings.json',{})
            with patch.object(Jobs,'_schedule',return_value=None):
                jobs=Jobs(Store(root))
            try:
                for action in ('login','references'):
                    payload={'action':action,'browser_account':'b'*32,'account_selection_from':'a'*32}
                    self.assertEqual(public(payload),payload)
                    job=jobs.submit('studio',payload,{})
                    self.assertEqual(job['state'],'queued')
                    self.assertEqual(read(root/'.desktop/jobs.json')[-1]['payload'],payload)
                for blocked in ({'gemini_api_key':'test-secret'},{'nested':{'password':'test-secret'}},{'_internal':'test'}):
                    with self.assertRaisesRegex(ValueError,'Credentials are not allowed'):
                        jobs.submit('studio',blocked,{})
                self.assertEqual(len(jobs.list()),2)
            finally:jobs.close()


if __name__=='__main__':unittest.main()
