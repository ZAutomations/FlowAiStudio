import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from desktop.jobs import worker_python
class WorkerRuntimeTests(unittest.TestCase):
 def test_managed_environment_wins_over_gui_base_interpreter(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
   python=Path(tmp)/'python.exe';python.write_bytes(b'test')
   with patch('bootstrap.PYTHON',python),patch('desktop.jobs.sys.executable','wrong-base-python'):
    self.assertEqual(worker_python(),str(python))
 def test_missing_environment_uses_current_interpreter(self):
  with patch('bootstrap.PYTHON',Path('missing-test-python.exe')),patch('desktop.jobs.sys.executable','current-python'):
   self.assertEqual(worker_python(),'current-python')
