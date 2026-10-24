"""Manual reference generation with exact identity recovery and no submissions."""
import json
from pathlib import Path
from ai_studio_pipeline import atomic_json,fingerprint,valid_image,check_cancel
from ai_studio_reference_agent import sheet_prompt


def run(config,cancel,log,download=False):
    from ai_studio_animate_setup import reference_plan,apply_fixed_dsp_reference
    if not config.get('flow_url'):raise ValueError('Choose this story’s Flow project before exporting or downloading references.')
    root=Path(config['project']);refs=reference_plan(config)
    if not refs:raise ValueError('No approved characters or locations in this story.')
    directory=root/'references';directory.mkdir(parents=True,exist_ok=True)
    plan_identity=fingerprint([(r['name'],r['kind'],r['prompt']) for r in refs],config.get('_reference_flow_url') or config['flow_url'])
    plan_file=directory/'reference_plan.json'
    if plan_file.exists():
        previous=json.loads(plan_file.read_text('utf-8'))
        if previous.get('identity')!=plan_identity:raise ValueError('The reference plan differs from this story’s saved plan. Restore its approved cast/style before exporting; existing references retained.')
    else:atomic_json(plan_file,{'identity':plan_identity,'references':refs})
    apply_fixed_dsp_reference(config,refs,cancel,log)
    identity=fingerprint(plan_identity,config['flow_url'])
    file=root/'manual_reference_images.json'
    if file.exists():
        state=json.loads(file.read_text('utf-8'))
        if state.get('identity')!=identity:raise ValueError('Reference export belongs to another design or Flow project; existing checkpoint retained.')
    else:
        if download:raise ValueError('Export reference prompts first, then generate them manually before downloading.')
        state={'identity':identity,'records':[dict(r,index=i,kind='image',reference_kind=r['kind'],
            token='AS_SCENE_'+fingerprint('manual-reference-v1',identity,r['name'])[:20],status='pending') for i,r in enumerate(refs)]}
    expected={r['name']:r for r in refs}
    if len(state['records'])!=len(refs) or any(r.get('name') not in expected or Path(r['output']).resolve()!=Path(expected[r['name']]['output']).resolve() for r in state['records']):
        raise ValueError('Reference output paths differ from the approved reference plan; no download started.')
    def save():atomic_json(file,state)
    for r in state['records']:
        check_cancel(cancel)
        if valid_image(r['output']):r['status']='complete'
        elif r['status']=='complete':r['status']='submitted'
    save()
    pending=[r for r in state['records'] if r['status']!='complete']
    if not download:
        text=['CHARACTERS AND LOCATIONS PROMPTS','Selected visual preset: '+config.get('style_name',''),
            'Visual style: '+config['style'],
            'Generate exactly one separate image per numbered reference below. Each identity must be one four-view sheet. Never combine different identities into one sheet.',
            'Begin each individual saved image generation prompt with its exact AS_SCENE tracking label. This identifies a REFERENCE, not a story scene. Never display the label or reference name inside the artwork.',
            'Keep the labels unchanged so the app can download and rename each image correctly. Do not generate references listed as already saved.']
        saved=[r['name'] for r in state['records'] if r['status']=='complete']
        if saved:text.append('Already saved — do not generate: '+', '.join(saved))
        for i,r in enumerate(pending,1):
            text.append(f"REFERENCE {i}: {r['name']} ({r['reference_kind']}) — save locally as {r['name']}.png\n{r['token']}\n{sheet_prompt(r)}")
        path=root/'characters_and_locations_prompts.txt';path.write_text('\n\n'.join(text),encoding='utf-8')
        log(f'Exported {len(pending)} character/location prompts: {path}. Generate these in this story’s Flow project, then click Download / rename / upload references. No generation submitted.')
        return None
    if pending:
        from ai_studio_animate_media import AgentMedia
        from desktop.browser_accounts import browser_options
        generator=AgentMedia('flow',mode='cdp',flow_project_url=config['flow_url'],share_google_profile=config.get('share_google_profile',True),cancel=cancel,
            log=lambda m,level='info':log(m),**browser_options({**config,'provider':'flow'}))
        generator.available_only=True;generator.reference_collection=True
        for r in state['records']:
            if r.get('asset_id'):generator._flow_asset_prompts[r['asset_id']]=r['token']
        generator.collect(pending,save,lambda r:log('Saved reference '+r['name']+'.png'),timeout=300)
    available=[r['output'] for r in state['records'] if valid_image(r['output'])]
    missing=[r['name'] for r in state['records'] if not valid_image(r['output'])]
    log(f'References saved: {len(available)}/{len(refs)}. Existing files skipped; exact tracking labels used for filenames.')
    if missing:log('Still missing: '+', '.join(missing)+'. Generate or finish these references and run this button again; no automatic generation submitted.')
    return available
