import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_studio_consistency import ensure_uploaded_reference_library
class LibraryUploadTests(unittest.TestCase):
 def test_scope_and_file_changes_upload_once_and_failures_are_not_marked(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
   root=Path(folder);ref=root/'DSPMalik.png';Image.new('RGB',(64,64),'red').save(ref)
   c={'project':str(root),'flow_url':'one','browser_account':'a','references':[str(ref)]}
   cancel=threading.Event()
   with patch('ai_studio_consistency.upload_reference_library') as upload:
    ensure_uploaded_reference_library(c,cancel,lambda m:None);ensure_uploaded_reference_library(c,cancel,lambda m:None)
    self.assertEqual(upload.call_count,1)
    c['flow_url']='two';ensure_uploaded_reference_library(c,cancel,lambda m:None);self.assertEqual(upload.call_count,2)
    c['browser_account']='b';ensure_uploaded_reference_library(c,cancel,lambda m:None);self.assertEqual(upload.call_count,3)
    Image.new('RGB',(64,64),'blue').save(ref);ensure_uploaded_reference_library(c,cancel,lambda m:None);self.assertEqual(upload.call_count,4)
    c['flow_url']='failed';upload.side_effect=RuntimeError('upload failed')
    for _ in range(2):
     with self.assertRaisesRegex(RuntimeError,'upload failed'):ensure_uploaded_reference_library(c,cancel,lambda m:None)
    self.assertEqual(upload.call_count,6)
 def test_invalid_reference_blocks_before_upload(self):
  with patch('ai_studio_consistency.upload_reference_library') as upload:
   with self.assertRaisesRegex(ValueError,'invalid'):ensure_uploaded_reference_library({'references':['missing.png']},threading.Event(),lambda m:None)
   upload.assert_not_called()
if __name__=='__main__':unittest.main()
