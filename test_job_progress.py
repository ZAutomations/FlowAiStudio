"""Execute the real JS progress helper, including ordinary non-download jobs."""
import json,shutil,subprocess,unittest
from pathlib import Path

class JobProgressTests(unittest.TestCase):
    def test_progress_helper_does_not_recurse_for_ordinary_jobs(self):
        root=Path(__file__).resolve().parent
        node=shutil.which('node') or str(root/'runtime/node/node.exe')
        helper=next(line for line in (root/'desktop/ui/studio.js').read_text('utf-8').splitlines() if line.startswith('function workflowJobProgress('))
        cases=[{'state':'running','progress':42},{'state':'queued','progress':0},{'state':'failed','progress':33},
               {'state':'completed','progress':100}, {'state':'completed','progress':100,'result':{'download':{'saved':96,'unmatched':133}}}]
        code=helper+'\nconsole.log(JSON.stringify('+json.dumps(cases)+'.map(workflowJobProgress)));'
        result=subprocess.run([node,'-e',code],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),[42,0,33,100,42])

if __name__=='__main__':unittest.main()
