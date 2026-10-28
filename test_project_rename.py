import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from ai_studio_animate_setup import ensure_project

class ProjectRenameTests(unittest.TestCase):
    def test_failed_rename_retries_same_project(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            url='https://flow.google.com/project/12345678-abcd'
            config={'project':folder,'title':'آخری خط','auto_project':True}
            generator=MagicMock(); generator.cdp_port=9232
            failed=MagicMock(); failed.poll.return_value=1; failed.returncode=1
            failed.communicate.return_value=(f'project_url: {url}\nFAILED: rename unavailable',)
            success=MagicMock(); success.poll.return_value=0; success.returncode=0
            success.communicate.return_value=(f'project_url: {url}\nproject_renamed: true',)
            with patch('ai_studio_animate_setup.ZBotImageGenerator',return_value=generator), patch('desktop.browser_accounts.browser_options',return_value={}), patch('ai_studio_animate_setup.project_tabs',return_value=[]), patch('ai_studio_animate_setup.shutil.which',return_value='node'), patch('ai_studio_animate_setup.subprocess.Popen',side_effect=[failed,success]) as launch:
                with self.assertRaises(RuntimeError): ensure_project(config,None,lambda x:None)
                state=json.loads((Path(folder)/'flow_project.json').read_text(encoding='utf-8'))
                self.assertEqual(state['status'],'renaming'); self.assertEqual(state['url'],url)
                self.assertEqual(ensure_project(config,None,lambda x:None),url)
                args=launch.call_args_list[1].args[0]
                self.assertIn('--project-url',args); self.assertNotIn('--new-tab',args)
                self.assertEqual(args[args.index('--title')+1],config['title'])
                self.assertEqual(json.loads((Path(folder)/'flow_project.json').read_text(encoding='utf-8'))['status'],'ready')

if __name__=='__main__':unittest.main()
