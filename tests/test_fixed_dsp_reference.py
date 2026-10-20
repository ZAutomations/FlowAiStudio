import tempfile,threading,unittest
from pathlib import Path
from PIL import Image
from ai_studio_animate_setup import apply_fixed_dsp_reference

class FixedDSPTests(unittest.TestCase):
    def test_reuses_same_dsp_across_stories_without_touching_other_references(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root=Path(folder);source=root/'master.jpg';Image.new('RGB',(512,512),'yellow').save(source)
            original=source.read_bytes()
            for name in ('story1','story2'):
                project=root/name;refs=[{'name':n,'kind':k,'output':str(project/'references'/(n+'.png'))} for n,k in [('DSPMalik','character'),('Witness','character'),('PoliceStation','location')]]
                config={'project':str(project),'dsp_malik_reference_path':str(source)}
                apply_fixed_dsp_reference(config,refs,threading.Event(),lambda m:None)
                self.assertTrue(Path(refs[0]['output']).exists())
                self.assertFalse(Path(refs[1]['output']).exists());self.assertFalse(Path(refs[2]['output']).exists())
                before=Path(refs[0]['output']).stat().st_mtime_ns
                apply_fixed_dsp_reference(config,refs,threading.Event(),lambda m:None)
                self.assertEqual(before,Path(refs[0]['output']).stat().st_mtime_ns)
            self.assertEqual(original,source.read_bytes())

    def test_invalid_path_fails_before_dsp_generation(self):
        with self.assertRaises(ValueError):
            apply_fixed_dsp_reference({'dsp_malik_reference_path':'nonexistent.jpg'},[],threading.Event(),lambda m:None)

    def test_previous_reference_is_archived_on_replacement(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root=Path(folder);source=root/'master.png';Image.new('RGB',(512,512),'yellow').save(source)
            output=root/'references/DSP.png';output.parent.mkdir();Image.new('RGB',(512,512),'red').save(output)
            original=output.read_bytes()
            apply_fixed_dsp_reference({'project':folder,'dsp_malik_reference_path':str(source)},[{'name':'DSP','kind':'character','output':str(output)}],threading.Event(),lambda m:None)
            self.assertEqual(next((root/'references/fixed_reference_history').glob('*.png')).read_bytes(),original)
            self.assertNotEqual(output.read_bytes(),original)



    def test_three_main_characters_reused_and_remaining_assets_untouched(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root=Path(folder);rows=[];refs=[]
            for i,name in enumerate(['DSPMalik','Ali','Mother']):
                source=root/(name+'.jpg');Image.new('RGB',(512,512),['red','blue','green'][i]).save(source)
                rows.append(dict(name=name,path=str(source)))
                refs.append(dict(name=name,kind='character',output=str(root/'references'/(name+'.png'))))
            refs.append(dict(name='Witness',kind='character',output=str(root/'references/Witness.png')))
            apply_fixed_dsp_reference({'project':folder,'main_character_references':json.dumps(rows)},refs,threading.Event(),lambda m:None)
            for ref in refs[:3]:self.assertTrue(Path(ref['output']).is_file())
            self.assertFalse(Path(refs[-1]['output']).exists())
            times=[Path(ref['output']).stat().st_mtime_ns for ref in refs[:3]]
            apply_fixed_dsp_reference({'project':folder,'main_character_references':rows},refs,threading.Event(),lambda m:None)
            self.assertEqual(times,[Path(ref['output']).stat().st_mtime_ns for ref in refs[:3]])

