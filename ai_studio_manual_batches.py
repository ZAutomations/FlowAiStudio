"""Export tracked Flow Agent batches and collect them without submitting prompts."""
import json
from pathlib import Path
from ai_studio_pipeline import atomic_json, fingerprint, valid_image


def export_batch_size(config):
    value=config.get('prompt_batch_size',20)
    try:
        count=int(value)
        if isinstance(value,bool) or count<1 or float(value)!=count:raise ValueError()
    except (ValueError,TypeError,OverflowError):
        raise ValueError('Prompt batch size must be a positive whole number') from None
    return count


def download_all(adapter,q,config):
    """Collect all currently available tracked scenes in one grid scan."""
    from ai_studio_animate_media import AgentMedia
    from desktop.browser_accounts import browser_options
    if config.get('provider')!='flow':raise ValueError('Download All Scene Images supports Google Flow Agent projects.')
    root=Path(config['project'])
    file=next((root/name for name in ('studio_agent_images.json','studio_manual_images.json') if (root/name).exists()),None)
    if file is None:raise ValueError('No tracked Agent scene requests exist. Generate Images or Export Prompt Batches first.')
    state=json.loads(file.read_text('utf-8'));records=state.get('records',[])
    if not records or state.get('identity')!=fingerprint([(r['key'],r['index']) for r in records],config.get('flow_url','')):
        raise ValueError('The saved scene checkpoint belongs to another Flow project. Open its saved project before downloading.')
    images=sorted((r for r in records if r['kind']=='image'),key=lambda r:r['index'])
    if len({r['index'] for r in images})!=len(images):raise ValueError('Duplicate scene indices in saved checkpoint; no files changed.')
    for r in images:
        expected=root/'images'/f'scene_{r["index"]+1:04d}.png'
        if not 0<=r['index']<len(adapter.zb_scenes) or Path(r['output']).resolve()!=expected.resolve():
            raise ValueError('Scene output path does not match its saved scene number; no files changed.')
        if r.get('narration') is not None and r['narration']!=adapter.zb_scenes[r['index']]['narration']:
            raise ValueError('Narration differs from the saved scene requests. Restore the matching script before downloading.')
    def save():atomic_json(file,state)
    def media(r,persist=True):
        scene=adapter.zb_scenes[r['index']]
        scene.update(image_path=r['output'],image_key=r['key'],image_status='done')
        if file.name=='studio_manual_images.json':scene['manual_image']=True
        if persist:
            adapter._zb_save_project(config)
            q.put(('refresh',))
    skipped=0;pending=[];metadata_changed=False
    for r in images:
        if valid_image(r['output']):
            r['status']='complete';skipped+=1
            scene=adapter.zb_scenes[r['index']]
            if scene.get('image_path')!=r['output'] or scene.get('image_key')!=r['key']:
                media(r,persist=False);metadata_changed=True
        else:
            if r['status']=='complete':r['status']='submitted'
            pending.append(r)
    if metadata_changed:
        adapter._zb_save_project(config)
        q.put(('refresh',))
    save()
    q.put(('log','info',f'Skipping {skipped} valid saved scene images. Scanning for {len(pending)} missing scene images; character/location references excluded.'))
    if pending:
        generator=AgentMedia('flow',mode='cdp',flow_project_url=config['flow_url'],
            share_google_profile=config.get('share_google_profile',True),cancel=adapter._zb_cancel,
            log=lambda message,level='info':q.put(('log',level,message)),**browser_options(config))
        generator.available_only=True
        for r in records:
            if r.get('asset_id') and r.get('token'):generator._flow_asset_prompts[r['asset_id']]=r['token']
        generator.collect(pending,save,media,timeout=300)
    downloaded=sum(r['status']=='complete' for r in pending)
    q.put(('log','success',f'Downloaded {downloaded} new scene images; skipped {skipped} saved images; {len(pending)-downloaded} not matched in this scan. Files saved by scene number.'))
    highest=max((r['index']+1 for r in images if r['status']=='complete'),default=0)
    gaps=[r['index']+1 for r in images if r['index']<highest and r['status']!='complete']
    if gaps:q.put(('log','warning',f'Unmatched gaps through scene {highest}: '+', '.join(map(str,gaps))+'. Duplicate variants and references do not count as additional scenes.'))
    return {'downloaded':downloaded,'saved':skipped+downloaded,'unmatched':len(pending)-downloaded,
        'highest_saved_scene':highest,'gaps':gaps}


def export_files(state, config, log, index_name='manual_batch_export.json'):
    from ai_studio_animate_media import batch_prompt
    from ai_studio_parts import scene_range
    start,end=scene_range(config,len(state['records']))
    pending=[r for r in state['records'] if start<=r['index']<end and not valid_image(r['output'])]
    size=export_batch_size(config)
    groups=[pending[i:i+size] for i in range(0,len(pending),size)]
    identity=fingerprint(state['identity'],[r['token'] for r in pending],size)
    directory=Path(config['project'])/'prompt_batches'/identity[:16]
    directory.mkdir(parents=True,exist_ok=True)
    entries=[];joined=[]
    for number,group in enumerate(groups,1):
        names={name for r in group for name in r.get('reference_names',[])}
        refs=[p for p in config.get('references',[]) if Path(p).stem in names]
        filenames={Path(p).stem:Path(p).name for p in refs}
        if names-set(filenames):
            raise ValueError('Missing reference files for batch export: '+', '.join(sorted(names-set(filenames))))
        batch_config={**config,'references':refs,
            'reference_descriptions':{k:v for k,v in config.get('reference_descriptions',{}).items() if k in names}}
        text=batch_prompt(group,batch_config)
        for record in group:
            assigned=record.get('reference_names',[])
            if assigned:
                text=text.replace('References for THIS scene only: '+', '.join(assigned),
                    'References for THIS scene only: '+' '.join('@'+filenames[name] for name in assigned))
        attachments=' '.join('@'+Path(p).name for p in refs) or 'NONE'
        text=('REQUIRED REFERENCE ATTACHMENTS FOR THIS BATCH:\n'+attachments+
              '\nSelect these files in Flow so they become actual attachment chips; pasted @names alone are not attachments.'+
              '\nEach scene below uses only its own listed references.\n\n'+text)
        filename=f'batch_{number:03d}_scenes_{group[0]["index"]+1:04d}-{group[-1]["index"]+1:04d}.txt'
        (directory/filename).write_text(text,encoding='utf-8')
        joined.append(f'===== BATCH {number:03d} =====\n\n'+text)
        entries.append({'file':filename,'tokens':[r['token'] for r in group],
            'scenes':[r['index']+1 for r in group],'references':refs})
    (directory/'all_batches.txt').write_text('\n\n'.join(joined),encoding='utf-8')
    index={'version':1,'batch_size':size,'identity':state['identity'],'flow_url':config['flow_url'],
        'directory':str(directory),'batches':entries}
    atomic_json(directory/'index.json',index)
    # Preserve eligibility of earlier exports even if the next export contains fewer scenes.
    file=Path(config['project'])/index_name
    previous=json.loads(file.read_text('utf-8')) if file.exists() else {}
    old=previous.get('tokens',[]) if previous.get('identity')==state['identity'] else []
    index['tokens']=sorted(set(old)|{r['token'] for r in pending})
    atomic_json(file,index)
    log(f'Exported {len(groups)} numbered batch files (up to {size} images each): {directory}')
    log('Combined copy: '+str(directory/'all_batches.txt'))
    log('Attach the reference files listed in index.json for each batch. Keep every AS_SCENE tracking label in the generation prompts. Download Generated Batches never submits prompts.')


def run(adapter, q, config, download=False):
    if config.get('provider')!='flow':raise ValueError('Prompt batches and tracked download currently support Google Flow Agent images.')
    root=Path(config['project'])
    if not config.get('flow_url'):raise ValueError('Set or save this video’s Flow project URL before exporting batches.')
    config={**config,'image_agent':True,'animation_mode':'partial','animate_count':0,
        'animate_model':'Veo 3.1 - Lite','image_batch_size':export_batch_size(config),
        '_export_batches':not download,'_local_references_only':True,
        '_recover_only':download,'_generate_missing':False,'_download_one_batch':download}
    if download:
        file=root/'manual_batch_export.json'
        if not file.exists():raise ValueError('Export Prompt Batches first. No generation or download was started.')
        data=json.loads(file.read_text('utf-8'))
        manifest=root/('studio_agent_images.json' if config.get('character_consistency') else 'studio_manual_images.json')
        state=json.loads(manifest.read_text('utf-8'))
        if data['identity']!=state['identity'] or data['flow_url']!=config['flow_url']:
            raise ValueError('Export belongs to a different scene plan or Flow project. Existing files retained.')
        config['_exported_tokens']=data['tokens']
        config['_exported_groups']=[batch['tokens'] for batch in data['batches']]
    if config.get('character_consistency'):
        from ai_studio_consistency import generate
        return generate(adapter,q,config,recover_only=download)
    if (root/'images/image_batches.json').exists():
        raise ValueError('This project has ordinary browser image requests. Recover those first; use a new video for the Agent batch export workflow. Existing checkpoints retained.')
    from zbot_ai_tab import RES_ASPECT
    from ai_studio_animate_media import generate_agent_media
    config.update(references=[],aspect=RES_ASPECT.get(config['resolution'],'16:9'),_manifest_name='studio_manual_images.json')
    def media(record):
        scene=adapter.zb_scenes[record['index']]
        scene.update(image_path=record['output'],image_key=record['key'],image_status='done',manual_image=True)
        adapter._zb_save_project(config)
        q.put(('refresh',))
    return generate_agent_media(adapter.zb_scenes,config,adapter._zb_cancel,
        lambda message:q.put(('log','info',message)),media)
