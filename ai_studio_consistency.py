"""Reference-first Nano Banana Agent images; never alter ordinary image queues."""
import json
import re
from pathlib import Path
from ai_studio_pipeline import valid_image


def generate(adapter,q,config,recover_only=False,references_only=False):
    from ai_studio_animate_setup import ensure_references
    from ai_studio_animate_media import generate_agent_media
    from zbot_ai_tab import RES_ASPECT
    if config['provider']!='flow':
        raise ValueError('Character consistency requires Google Flow (browser).')
    project=Path(config['project'])
    if not (project/'studio_agent_images.json').exists() and (
        (project/'images/image_batches.json').exists() or any(valid_image(s.get('image_path','')) for s in adapter.zb_scenes)):
        raise RuntimeError('This video already has ordinary image outputs or requests. Start a new video to enable reference-based Agent images; existing work is preserved.')
    if recover_only and not (project/'studio_agent_images.json').exists():
        raise RuntimeError('No reference Agent batch exists to recover. Use Generate Images first.')
    config.update(image_agent=True,animation_mode='partial',animate_count=0,
                  animate_model='Veo 3.1 - Lite',reference_mode='characters',auto_reference=True,
                  aspect=RES_ASPECT.get(config['resolution'],'16:9'))
    config.setdefault('character_names','DSP, HelpingPoliceman')
    config.setdefault('place_name','PoliceStation')
    config.setdefault('reference_design','')
    cast=None
    if config.get('auto_cast',True):
        from ai_studio_cast import current
        cast=current(config,adapter.zb_scenes,approved=True)
        if cast is None:raise ValueError('Analyze the full script, review the cast and Approve Cast before creating references.')
        used={name for r in cast['scenes'] for name in r['references']}
        config['cast_assets']=[a for a in cast['assets'] if a['name'] in used]
        config['scene_reference_map']=[r['references'] for r in cast['scenes']]
        config['reference_descriptions']={a['name']:a['description'] for a in cast['assets']}
    supplied=[p.strip() for p in config.get('reference_files','').split('|') if p.strip()]
    if supplied:
        if len(supplied)>40 or any(not valid_image(p) for p in supplied):
            raise ValueError('Use up to forty valid reference image paths separated by |.')
        names=[Path(p).stem for p in supplied]
        if len(set(n.casefold() for n in names))!=len(names) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',n) for n in names):
            raise ValueError('Reference filenames must have unique simple names, e.g. DSP.png or PoliceStation.png.')
        config['references']=supplied
        if cast and set(names)!={a['name'] for a in config['cast_assets']}:
            raise ValueError('Reference filenames must match all approved cast/location identifiers exactly.')
    else:
        # Revalidate the saved bible/plan rather than bypassing it with paths
        # inherited from the previous job's saved options.
        config.pop('references',None)
    log=lambda m:q.put(('log','info',m))
    def plan(refs):
        system=('Return ONLY a JSON object mapping each supplied permanent asset name to a detailed immutable reference design. '
                'Derive its actual role from the full narration. Characters: age, face shape, skin tone, hair, moustache, build, '
                'fixed clothing and colors. Locations: architecture, layout, entrances and distinctive props. '
                'Honor the selected historical period and region exactly. No modern police equipment in historical Punjab. '
                'Different characters must have visibly distinct faces. Do not invent story events. Names are attachment identifiers, not visible text.')
        raw,error=adapter._zb_llm(system,json.dumps({'assets':refs,'title':config['title'],'script':config['script'],
            'style':config['style'],'design':config['reference_design'],'continuity':config.get('continuity','')},ensure_ascii=False),
            max_tokens=3000,provider=config.get('llm','gemini'))
        if error:raise RuntimeError('Reference planning failed: '+str(error))
        try:return json.loads(re.search(r'\{.*\}',raw,re.S).group())
        except (ValueError,AttributeError):raise RuntimeError('Reference planner returned invalid JSON. Retry; no scene images submitted.')
    reference_config=config
    if config.get('_dsp_previous_style'):
        reference_config={**config,'style':config['_dsp_previous_style']}
        log('DSP ColorMix selected: retaining approved cast and saved reference identities; applying color treatment to new scene images only.')
    if config.get('_manual_reference_action'):
        adapter._zb_save_project(config)
        from ai_studio_manual_references import run
        files=run(reference_config,adapter._zb_cancel,log,download=config['_manual_reference_action']=='download')
        if files is not None:
            config['references']=files
            adapter._zb_save_project(config)
            upload_reference_library(adapter,config,log)
        return
    config['references']=ensure_references(reference_config,adapter._zb_cancel,log,None if cast is not None or config.get('_local_references_only') else plan)
    adapter._zb_save_project(config)
    log('Reference identities locked: '+(', '.join(Path(p).stem for p in config['references']) or 'none needed')+'. Each scene group attaches only its assigned references; Nano Banana model is verified before submission.')
    if references_only:
        upload_reference_library(adapter,config,log)
        return
    def media(record):
        scene=adapter.zb_scenes[record['index']]
        if record.get('_reused') and scene.get('image_path')==record['output'] and scene.get('image_key')==record['key']:
            return
        scene.update(image_path=record['output'],image_key=record['key'],image_status='done')
        adapter._zb_save_project(config)
        q.put(('refresh',))
        if not record.get('_reused'):q.put(('log','success',f"Scene {record['index']+1}: reference-consistent image saved."))
    from ai_studio_image_models import ImageModelsExhausted
    while True:
        try:
            generate_agent_media(adapter.zb_scenes,{**config,'_generate_missing':not recover_only,'_recover_only':recover_only},adapter._zb_cancel,log,media)
            break
        except ImageModelsExhausted:
            if recover_only:raise
            from ai_studio_account_rotation import handover
            handover(config,adapter._zb_cancel,log)
            adapter._zb_save_project(config)

def upload_reference_library(adapter,config,log):
    project=Path(config['project'])
    if config['references']:
        from ai_studio_animate_media import prepare_agent_prompt
        from zbot_browser_images import ZBotImageGenerator
        from desktop.browser_accounts import browser_options
        connection={**config,'provider':'flow','share_google_profile':config.get('share_google_profile',True)}
        browser=ZBotImageGenerator('flow',mode='cdp',flow_project_url=config['flow_url'],
            share_google_profile=connection['share_google_profile'],cancel=adapter._zb_cancel,
            log=lambda m,level='info':log(m),**browser_options(connection))
        prompt=project/'reference_library_upload.txt'
        prompt.write_text('Upload the complete saved reference library only. Do not generate scene media.',encoding='utf-8')
        # Keep the verified browser connection alive through the Node upload.
        # Use the actual session port, never a second independently defaulted port.
        with browser._session(headless=False) as ctx:
            browser._batch_page(ctx)
            log(f'Uploading/reusing all {len(config["references"])} reference images on {browser.browser_label} port {browser.cdp_port}…')
            prepare_agent_prompt({**config,'_upload_references_only':True,'_agent_cdp_port':browser.cdp_port},
                                 prompt,config['references'],adapter._zb_cancel,log)
        log('All supplied saved references are available in Flow. Future batches attach only their assigned references.')
