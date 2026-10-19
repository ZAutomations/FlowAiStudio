"""Checkpoint private Flow projects and named reference designs."""
import json
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from ai_studio_pipeline import atomic_json, check_cancel, fingerprint, valid_image
from zbot_browser_images import ZBotImageGenerator


def project_tabs(port=10312):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=3) as response:
        tabs = json.load(response)
    return sorted({m.group(0) for t in tabs for m in [re.search(r'https://flow\.google\.com/project/[a-zA-Z0-9-]+', t.get('url', ''))] if m})


def ensure_project(config, cancel, log):
    file = Path(config['project']) / 'flow_project.json'
    if config.get('_rotation_scope'):
        account=config.get('browser_account','')
        if account and not re.fullmatch(r'[a-f0-9]{32}',account):raise ValueError('Invalid rotation account')
        file=Path(config['project'])/'flow_accounts'/(account or 'default')/'flow_project.json'
    if not file.exists() and config.get('_rotation_restored') and config.get('flow_url'):
        atomic_json(file,{'url':config['flow_url'],'status':'ready'})
    state = json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}
    if state.get('url'):
        log('Reusing saved Flow project: '+state['url'])
        return state['url']
    if not config.get('auto_project', True):
        url = config.get('flow_url', '')
        if not re.fullmatch(r'https://flow\.google\.com/project/[a-zA-Z0-9-]+(?:[/?].*)?', url):
            raise RuntimeError('Enter a Flow project URL or enable automatic project creation.')
        atomic_json(file, {'url': url, 'status': 'ready'})
        return url
    from desktop.browser_accounts import browser_options
    generator = ZBotImageGenerator('flow', mode='cdp', share_google_profile=config.get('share_google_profile', True), cancel=cancel, log=lambda m, level='info': log(m), **browser_options({**config, 'provider': 'flow', 'share_google_profile': config.get('share_google_profile', True)}))
    if not generator._cdp_alive():
        generator._start_real_chrome()
    before = project_tabs(generator.cdp_port)
    if state.get('status') == 'creating':
        new = [url for url in before if url not in state.get('before', [])]
        if len(new) == 1:
            atomic_json(file, {'url': new[0], 'status': 'ready'})
            return new[0]
        raise RuntimeError('Project creation was interrupted. Open its Flow project and retry; another project will not be created automatically.')
    check_cancel(cancel)
    driver = Path(config.get('agent_tool_dir') or Path(__file__).parent/'animate_flow_backend') / 'project_setup.js'
    node = shutil.which('node')
    if not driver.is_file() or not node:
        raise RuntimeError('The bundled Animate project driver and Node.js are required.')
    atomic_json(file, {'status': 'creating', 'before': before})
    log('Creating a new Flow project for this video…')
    process = subprocess.Popen([node, str(driver), '--cdp', str(generator.cdp_port), '--new-tab', '--timeout', '60'], cwd=driver.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    started = time.monotonic()
    try:
        while process.poll() is None:
            check_cancel(cancel)
            if time.monotonic() - started > 90:
                raise RuntimeError('Flow project creation timed out; its checkpoint is retained.')
            time.sleep(.2)
        output = process.communicate()[0]
        found = re.search(r'project_url:\s*(https://flow\.google\.com/project/[a-zA-Z0-9-]+)', output)
        if process.returncode or not found:
            raise RuntimeError('Flow project creation failed: ' + output[-1200:])
        url = found.group(1)
        atomic_json(file, {'url': url, 'status': 'ready'})
        log('Flow project saved: ' + url)
        return url
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        process.stdout.close()


def reference_plan(config):
    if 'cast_assets' in config:
        context=' Visual style: '+config['style']+'. Continuity: '+config.get('continuity','')
        refs=[]
        for asset in config['cast_assets']:
            prompt=('Create one full-body character identity reference, neutral pose, plain grey background, one person only. Fix face, age, hair, build, clothing and colors.' if asset['kind']=='character' else
                    'Create one location identity reference. Establish the fixed architecture, layout, entrances and distinctive props. No people.')
            refs.append(dict(name=asset['name'],kind=asset['kind'],prompt=prompt+' No text. Identity: '+asset['name']+'. Approved design: '+asset['description']+context,
                             output=str(Path(config['project'])/'references'/(asset['name']+'.png'))))
        return refs
    names = [n.strip() for n in config.get('character_names', 'CharacterA, CharacterB').split(',') if n.strip()]
    place = config.get('place_name', 'StoryPlace').strip()
    places=[n.strip() for n in place.split(',') if n.strip()] if config.get('image_agent') else [place]
    if (len(names)+len(places)>6 if config.get('image_agent') else len(names)>2) or not names or not place:
        raise ValueError('Use one or two character names and one location name.')
    all_names = names + places
    if len({n.lower() for n in all_names}) != len(all_names) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}', n) for n in all_names):
        raise ValueError('Reference names must be unique; use letters, numbers, underscores or hyphens, starting with a letter.')
    context = 'Style: ' + config['style'] + '. Character/location design: ' + config.get('reference_design', '') + '. Continuity: ' + config.get('continuity', '') + '. Story: ' + config['script']
    descriptions = config.get('reference_descriptions', {})
    refs = []
    for i, name in enumerate(names):
        refs.append({'name': name, 'kind': 'character', 'prompt': f'Create one character reference image of {name}, recurring character {i+1} of {len(names)} in the story. Design: ' + descriptions.get(name, '') + '. Establish a distinctive fixed face, clothing and colors for reuse. Only this character, full body, neutral pose, plain grey background, no text. ' + context})
    for place in places:
        refs.append({'name': place, 'kind': 'location', 'prompt': 'Create one environment reference image of ' + place + ', the recurring story location. Design: ' + descriptions.get(place, '') + '. Establish its layout, grey background palette and distinctive colored props. No people or text. ' + context})
    for ref in refs:
        ref['output'] = str(Path(config['project']) / 'references' / (ref['name'] + '.png'))
    return refs


def apply_fixed_dsp_reference(config,refs,cancel,log):
    source=str(config.get('dsp_malik_reference_path','')).strip()
    if not source:return
    path=Path(source).expanduser()
    if not valid_image(path):raise ValueError('Permanent DSPMalik image path is missing or is not a valid image. Select an existing image; DSPMalik was not generated.')
    matches=[r for r in refs if r['kind']=='character' and re.sub(r'[^a-z0-9]','',r['name'].lower()) in ('dspmalik','dsp')]
    if len(matches)>1:raise ValueError('Both DSP and DSPMalik are in the reference plan. Keep one DSPMalik identity before using the permanent image.')
    if not matches:
        log('Permanent DSPMalik image retained in settings; this story has no DSPMalik/DSP character to replace.')
        return
    from PIL import Image
    output=Path(matches[0]['output'])
    check_cancel(cancel)
    if valid_image(output):
        with Image.open(path) as source_image,Image.open(output) as saved:
            a=source_image.convert('RGB');b=saved.convert('RGB')
            if a.size==b.size and a.tobytes()==b.tobytes():
                log('Permanent DSPMalik reference already saved; generation skipped.')
                return
        import hashlib
        history=Path(config['project'])/'references'/'fixed_reference_history'
        history.mkdir(parents=True,exist_ok=True)
        backup=history/(hashlib.sha256(output.read_bytes()).hexdigest()+output.suffix)
        if not backup.exists():shutil.copy2(output,backup)
    output.parent.mkdir(parents=True,exist_ok=True)
    ZBotImageGenerator._save_image_bytes(path.read_bytes(),output,cancel)
    if not valid_image(output):raise RuntimeError('Could not save permanent DSPMalik reference. No replacement reference generated.')
    log('Permanent DSPMalik image copied from '+str(path)+' as '+output.name+'; AI generation skipped for this character.')


def ensure_references(config, cancel, log, plan_designs=None):
    from ai_studio_animate_options import reference_mode
    if reference_mode(config)=='none':
        log('No recurring references: scenes follow their narration and selected visual style; no CharacterA/CharacterB or fixed location generated.')
        return []
    if config.get('references') or not config.get('auto_reference', True):
        supplied=list(config.get('references', []))
        if config.get('dsp_malik_reference_path'):
            refs=[{'name':Path(p).stem,'kind':'character','output':str(Path(config['project'])/'references'/(Path(p).stem+'.png'))} for p in supplied]
            apply_fixed_dsp_reference(config,refs,cancel,log)
            supplied=[str(Path(config['project'])/'references'/(Path(p).stem+'.png'))
                if re.sub(r'[^a-z0-9]','',Path(p).stem.lower()) in ('dspmalik','dsp') else p for p in supplied]
        return supplied
    refs = reference_plan(config)
    directory = Path(config['project']) / 'references'
    directory.mkdir(exist_ok=True)
    if plan_designs:
        bible_file = directory / 'reference_bible.json'
        bible_key = fingerprint(config['script'], config['style'], config.get('reference_design',''), config.get('continuity',''), [r['name'] for r in refs])
        if bible_file.is_file():
            bible = json.loads(bible_file.read_text(encoding='utf-8'))
            if bible.get('identity') != bible_key:
                raise RuntimeError('Saved cast/location plan changed. Start a new Animate project.')
        else:
            log('Planning distinct character identities and the recurring location…')
            descriptions = plan_designs(refs)
            if not isinstance(descriptions,dict) or any(not isinstance(descriptions.get(r['name']),str) or not descriptions[r['name']].strip() for r in refs):
                raise RuntimeError('Character/location planning returned incomplete designs. Check the selected writing provider and retry.')
            bible = {'identity':bible_key,'descriptions':descriptions}
            atomic_json(bible_file,bible)
        config['reference_descriptions'] = bible['descriptions']
        refs = reference_plan(config)
    file = directory / 'reference_plan.json'
    identity = fingerprint([(r['name'], r['kind'], r['prompt']) for r in refs], config.get('_reference_flow_url') or config['flow_url'])
    if file.is_file():
        saved=json.loads(file.read_text(encoding='utf-8'))
        if saved.get('identity') != identity:
            root=Path(config['project']).resolve()
            old_refs=saved.get('references',[])
            foreign=bool(old_refs) and all(isinstance(row,dict) and isinstance(row.get('output'),str)
                and Path(row['output']).resolve().parent.parent!=root for row in old_refs)
            media_started=any((root/name).exists() for name in ('studio_agent_images.json','animate_media.json','images/image_batches.json'))
            media_started=media_started or any(valid_image(path) for path in (root/'images').glob('scene_*'))
            if not foreign or media_started:
                raise RuntimeError('Character/location designs changed. The saved reference plan belongs to a different design or scene generation already started. Existing files are preserved; restore the matching plan before resuming.')
            check_cancel(cancel)
            # Use a content hash as the path, never a path supplied by copied JSON.
            history=directory/'plan_history'/fingerprint(saved)
            history.mkdir(parents=True,exist_ok=True)
            for name in ('reference_plan.json','reference_bible.json','image_batches.json','verified_flow_assets.json'):
                source=directory/name
                if source.is_file():
                    backup=history/name
                    if backup.exists():
                        if backup.read_bytes()!=source.read_bytes():raise RuntimeError('Reference metadata archive conflicts with an earlier backup; no files overwritten.')
                        source.unlink()
                    else:source.replace(backup)
            atomic_json(file,{'identity':identity,'references':refs})
            log('Detected reference metadata copied from another project. Archived that metadata and rebuilt this project’s reference plan. Local reference images and scene analysis are preserved; only exact current reference names are reused.')
    else:
        atomic_json(file, {'identity': identity, 'references': refs})
    apply_fixed_dsp_reference(config,refs,cancel,log)
    for ref in refs:
        if valid_image(ref['output']):continue
        output=Path(ref['output'])
        alternative=next((output.with_suffix(ext) for ext in ('.jpg','.jpeg','.webp') if valid_image(output.with_suffix(ext))),None)
        if alternative:
            ZBotImageGenerator._save_image_bytes(alternative.read_bytes(),output,cancel)
            log('Reused the saved local reference '+alternative.name+' as '+output.name+'; no new generation.')
    if all(valid_image(ref['output']) for ref in refs):
        return [ref['output'] for ref in refs]
    missing_refs=[ref for ref in refs if not valid_image(ref['output'])]
    if config.get('_local_references_only'):
        raise RuntimeError('Create the missing reference images first: '+', '.join(ref['name'] for ref in missing_refs)+'. Batch export/download never generates references.')
    log('Generating missing named reference images only: ' + ', '.join(ref['name'] for ref in missing_refs))
    check_cancel(cancel)
    setup = Path(config['agent_tool_dir']) / 'prepare_reference_mode.js'
    from desktop.browser_accounts import browser_options
    account_options=browser_options({**config,'provider':'flow'})
    browser = ZBotImageGenerator('flow', mode='cdp', share_google_profile=config.get('share_google_profile',True), flow_project_url=config['flow_url'], cancel=cancel, **account_options)
    with browser._session(headless=False) as ctx:
        browser._batch_page(ctx)
    result = subprocess.run([shutil.which('node') or 'node', str(setup), config['flow_url'], str(browser.cdp_port)], cwd=setup.parent, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError('Reference Image mode setup failed: ' + (result.stdout + result.stderr)[-1200:])
    check_cancel(cancel)
    generator = ZBotImageGenerator('flow', mode='cdp', share_google_profile=config.get('share_google_profile',True), flow_project_url=config['flow_url'], cancel=cancel, flow_aspect_ratio='16:9', log=lambda m, level='info': log(m), **account_options)
    log('Reference queue: submit up to 6 separate prompts before waiting for their matched images.')
    results = generator.generate_batch([(r['prompt'], r['output']) for r in missing_refs], batch_size=6, timeout=300)
    if not results or not all(result[0] for result in results):
        raise RuntimeError('Named references are incomplete. Resume to recover the saved requests.')
    return [r['output'] for r in refs]
