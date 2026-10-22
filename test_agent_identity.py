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
