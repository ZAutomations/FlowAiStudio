import unittest
from ai_studio_animate_media import scene_tracking_tokens,agent_label_conflicts,batch_prompt

class AgentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.records=[{'index':96,'token':'AS_SCENE_c693d7c44e4fed8e6e73','status':'submitted','kind':'image','prompt':'Sakina room','reference_names':[]}]

    def test_foreign_reference_id_is_not_a_scene_receipt(self):
        reply='Already generated: OUTPUT 0097 / AS_SCENE_6a26902c7b504222bd7f (ID: image123)'
        self.assertEqual(agent_label_conflicts(reply,self.records),[97])

    def test_exact_and_completed_receipts_do_not_conflict(self):
        self.assertEqual(agent_label_conflicts('OUTPUT 0097 / '+self.records[0]['token'],self.records),[])
        self.records[0]['status']='complete'
        self.assertEqual(agent_label_conflicts('OUTPUT 0097 / AS_SCENE_1234',self.records),[])

    def test_variants_are_not_silently_truncated(self):
        label=self.records[0]['token']
        self.assertEqual(scene_tracking_tokens(label+'_1 '+label+'_2'),set())
        self.assertEqual(scene_tracking_tokens('('+label+').'),{label})
        self.assertEqual(agent_label_conflicts('OUTPUT 0097 / '+label+'_1',self.records),[97])

    def test_prompt_has_authoritative_mapping(self):
        text=batch_prompt(self.records,{'image_agent':True,'animate_model':'Omni 1.1 Flash','references':[]})
        self.assertIn('OUTPUT 0097 = '+self.records[0]['token'],text)
        self.assertIn('Never recycle earlier labels',text)

if __name__=='__main__':unittest.main()

class DuplicateReplayGuardTests(__import__('unittest').TestCase):
    def test_ordinary_retry_cannot_authorize_replay(self):
        from ai_studio_animate_media import explicit_missing_recovery
        for config in ({},{'action':'images'},{'action':'build'},{'_generate_missing':False},{'_generate_missing':'true'}):
            self.assertFalse(explicit_missing_recovery(config))
        self.assertTrue(explicit_missing_recovery({'_generate_missing':True}))

class ProviderMissingAuditTests(__import__('unittest').TestCase):
    def test_only_fresh_exact_confirmed_absence_authorizes_recovery(self):
        import json
        from ai_studio_animate_media import parse_missing_audit
        records=[{'index':206,'token':'AS_SCENE_abc'},{'index':207,'token':'AS_SCENE_def'}]
        data={'audit_id':'fresh','generation_allowed':True,'outputs':[{'scene':207,'token':'AS_SCENE_abc','status':'missing','checked_saved_prompts':True},{'scene':208,'token':'AS_SCENE_def','status':'existing'}]}
        self.assertEqual(parse_missing_audit(json.dumps(data),records,'fresh'),records[:1])
        self.assertEqual(parse_missing_audit(json.dumps(data),records,'old'),[])
        data['outputs'][0]['token']='AS_SCENE_abc_1'
        self.assertEqual(parse_missing_audit(json.dumps(data),records,'fresh'),[])
    def test_restrictions_or_uncertainty_never_authorize_generation(self):
        import json
        from ai_studio_animate_media import parse_missing_audit
        records=[{'index':0,'token':'AS_SCENE_abc'}]
        for status in ('uncertain','processing','blocked','existing'):
            data={'audit_id':'fresh','generation_allowed':True,'outputs':[{'scene':1,'token':'AS_SCENE_abc','status':status,'checked_saved_prompts':True}]}
            self.assertEqual(parse_missing_audit(json.dumps(data),records,'fresh'),[])
        data['outputs'][0]['status']='missing';data['generation_allowed']=False
        self.assertEqual(parse_missing_audit(json.dumps(data),records,'fresh'),[])
        data['generation_allowed']=True;data['outputs'][0]['checked_saved_prompts']=False
        self.assertEqual(parse_missing_audit(json.dumps(data),records,'fresh'),[])

class ImageBatchSchedulingTests(__import__('unittest').TestCase):
    def test_independent_images_are_queued_together_without_duplicate_variants(self):
        from ai_studio_animate_media import batch_prompt
        records=[{'index':i,'token':'AS_SCENE_'+str(i),'kind':'image','prompt':'A specific illustration','narration':'Story beat'} for i in range(24)]
        text=batch_prompt(records,{'style_name':'Documentary','script':'Story','title':'Test','aspect':'16:9','animate_model':'Omni 1.1 Flash'})
        self.assertIn('ONE batch containing 24 independent scene images',text)
        self.assertIn('enqueue ALL confirmed missing scene requests together',text)
        self.assertIn('do not bypass limits',text)
        self.assertEqual(text.count('Generation prompt tracking reference:'),24)
