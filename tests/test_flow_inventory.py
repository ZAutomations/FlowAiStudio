import json
import unittest
from ai_studio_flow_inventory import response_images

class InventoryTests(unittest.TestCase):
    project='a5e275b8-9c0f-4024-9096-a4c45f1e255c'
    asset='468ce7b5-9d87-4329-8f27-f9a71e0a2d94'
    token='AS_SCENE_09325e9aef885baad5c4'
    def response(self,prompt,project=None,url=None):
        row=[self.asset,project or self.project,None,None,None,[None,None,None,None,None,url or 'https://lh3.googleusercontent.com/asb/existing',[None,None,[[prompt]]]]]
        return ")]}'\n\n100\n"+json.dumps([['wrb.fr','opaque',json.dumps([None,[row]])]])
    def test_recovers_exact_scene_from_unmounted_asset(self):
        images=response_images(self.response(self.token+'. DSP questions Idris.'),self.project)
        self.assertEqual(images[0]['asset_id'],self.asset)
        self.assertFalse(images[0]['visible'])
    def test_excludes_references_ambiguous_prompts_and_other_project(self):
        for prompt in ['Create one location identity reference. '+self.token,self.token+' AS_SCENE_ffffffffffffffffffff','reference upload']:
            self.assertEqual(response_images(self.response(prompt),self.project),[])
        self.assertEqual(response_images(self.response(self.token,project='another-project'),self.project),[])
        self.assertEqual(response_images(self.response(self.token,url='https://example.com/asb/x'),self.project),[])
    def test_unknown_response_falls_back_without_guessing(self):
        self.assertEqual(response_images('not a supported response',self.project),[])

    def test_active_generation_never_reloads_page(self):
        from unittest.mock import Mock
        from ai_studio_flow_inventory import read_project_images
        page=Mock();page.url='https://flow.google.com/project/'+self.project
        page.locator.return_value.evaluate_all.side_effect=[False,True]
        self.assertEqual(read_project_images(page,None,Mock()),[])
        page.reload.assert_not_called()
        page.on.assert_not_called()

if __name__=='__main__':unittest.main()
