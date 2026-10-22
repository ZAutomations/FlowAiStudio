"""Replace generated reference originals only after the complete local library is safe."""
import json,re
from pathlib import Path
from ai_studio_pipeline import atomic_json,check_cancel,fingerprint,valid_image

def cleanup_plan(config):
    root=Path(config['project']);files=[Path(p) for p in config.get('references',[])]
    if not files or any(not valid_image(p) for p in files):
        raise ValueError('All renamed reference images must be valid on disk before Flow cleanup. Nothing deleted.')
    plan_file=root/'references/reference_plan.json'
    expected={r['name'] for r in json.loads(plan_file.read_text('utf-8')).get('references',[])} if plan_file.exists() else {p.stem for p in files}
    if {p.stem for p in files}!=expected:
        raise ValueError('The complete renamed reference library is not saved yet. Nothing deleted.')
    ids=set();tokens=set()
    for name in ('reference_agent_media.json','manual_reference_images.json','references/image_batches.json'):
        file=root/name
        if not file.exists():continue
        data=json.loads(file.read_text('utf-8'));rows=data.get('records',[])
        if name.endswith('image_batches.json'):rows=list(data.get('requests',{}).values())
        for row in rows:
            if row.get('name') and row['name'] not in expected:continue
            if row.get('asset_id'):ids.add(row['asset_id'])
            ids.update(row.get('alternate_asset_ids',[]))
            if row.get('token'):tokens.add(row['token'])
    protected=set()
    for name in ('studio_agent_images.json','animate_media.json'):
        file=root/name
        if file.exists():
            for row in json.loads(file.read_text('utf-8')).get('records',[]):
                if row.get('asset_id'):protected.add(row['asset_id'])
                protected.update(row.get('alternate_asset_ids',[]))
                if row.get('token') in tokens:raise ValueError('Reference and scene tracking identities overlap. Nothing deleted.')
    if ids & protected:raise ValueError('A reference candidate is also a scene asset. Nothing deleted.')
    identity=fingerprint('reference-cleanup-v1',config['flow_url'],[(p.name,fingerprint(p.read_bytes().hex())) for p in files],sorted(ids),sorted(tokens))
    return dict(identity=identity,asset_ids=sorted(ids),tokens=sorted(tokens),protected=sorted(protected))

def remove_one(page,asset_id,cancel):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',asset_id):raise RuntimeError('Reference asset ID is invalid. Nothing deleted.')
    check_cancel(cancel)
    tile=page.locator(f'flow-image-tile[data-ai-studio-media="{asset_id}"]').first
    tile.scroll_into_view_if_needed(timeout=5000);tile.hover(timeout=5000)
    tile.get_by_role('button',name='More options',exact=True).click(timeout=5000)
    trash=page.get_by_role('menuitem',name='Move to trash',exact=True)
    trash.wait_for(state='visible',timeout=5000)
    if trash.count()!=1:raise RuntimeError('Reference trash control is ambiguous. Cleanup stopped.')
    trash.click(timeout=5000);page.wait_for_timeout(400)
    dialog=page.get_by_role('dialog').filter(has_text=re.compile(r'trash|delete',re.I))
    if dialog.count():
        if dialog.count()!=1 or re.search(r'delete (?:this |the )?project',dialog.inner_text(),re.I):
            raise RuntimeError('Unexpected cleanup confirmation. Nothing else deleted.')
        confirm=dialog.get_by_role('button',name=re.compile(r'^(Move to trash|Delete|Trash|Confirm)$',re.I))
        if confirm.count()!=1:raise RuntimeError('Reference deletion confirmation is ambiguous.')
        confirm.click(timeout=5000)
    page.wait_for_function('id=>![...document.querySelectorAll("flow-image-tile")].some(t=>t.getAttribute("data-ai-studio-media")===id)',arg=asset_id,timeout=15000)

def clean_generated_references(page,config,cancel,log):
    plan=cleanup_plan(config);file=Path(config['project'])/'references/library_cleanup.json'
    old=json.loads(file.read_text('utf-8')) if file.exists() else {}
    if old.get('identity')==plan['identity'] and old.get('complete'):return
    from ai_studio_animate_media import AgentMedia
    inspector=AgentMedia('flow',cancel=cancel,log=lambda message,level='info':log(message))
    reference_names={Path(p).stem.casefold() for p in config['references']}
    inspector._flow_reference_filenames={name+suffix for name in reference_names for suffix in ('.png','.jpg','.jpeg','.webp')}
    state=old if old.get('identity')==plan['identity'] else {**plan,'deleted_ids':[],'complete':False}
    atomic_json(file,state)
    def scan():
        inspector._scene_grid_position(page,0);found={};passes=0
        for step in range(250):
            check_cancel(cancel)
            if page.get_by_role('button',name=re.compile(r'^Stop(?: generation| generating)?$',re.I)).evaluate_all("buttons=>buttons.some(b=>!b.disabled && b.getBoundingClientRect().width>0)"):
                raise RuntimeError('Flow is generating. Reference cleanup paused; no active requests will be deleted.')
            assets=inspector._agent_assets(page)
            for asset in assets:
                if asset['kind']!='image' or asset['asset_id'] in plan['protected']:continue
                if asset.get('busy'):raise RuntimeError('An image is processing. Wait before reference cleanup.')
                known=asset['asset_id'] in plan['asset_ids']
                if not known and asset.get('visible') is not False:
                    text=inspector._asset_prompt(page,asset)
                    labels=set(re.findall(r'AS_SCENE_[a-f0-9]+',text))
                    known=(len(labels)==1 and next(iter(labels)) in plan['tokens']) or (text.startswith('FLOW_REFERENCE:') and Path(text.removeprefix('FLOW_REFERENCE:')).stem.casefold() in reference_names)
                if known:found[asset['asset_id']]=asset
            position=inspector._scene_grid_position(page)
            if not position:raise RuntimeError('Cannot verify full reference gallery. No bulk deletion attempted.')
            at_end=position['top']+position['client']>=position['height']-5
            if at_end:
                passes+=1
                if passes>=2:return found
            inspector._scene_grid_position(page,0 if at_end else position['top']+position['client']*.7)
            page.wait_for_timeout(250)
        raise RuntimeError('Reference cleanup scan incomplete; saved files retained.')
    targets=scan()
    log(f'All {len(config["references"])} renamed references verified locally. Removing {len(targets)} matched generated reference copies before uploading the named library.')
    for asset_id in targets:
        # Re-locate by immutable identity after virtualized scrolling.
        inspector._scene_grid_position(page,0)
        for attempt in range(250):
            if any(a['asset_id']==asset_id for a in inspector._agent_assets(page)):break
            pos=inspector._scene_grid_position(page)
            if not pos or pos['top']+pos['client']>=pos['height']-5:raise RuntimeError('Reference tile could not be relocated; cleanup paused.')
            inspector._scene_grid_position(page,pos['top']+pos['client']*.7);page.wait_for_timeout(200)
        remove_one(page,asset_id,cancel)
        if asset_id not in state['deleted_ids']:state['deleted_ids'].append(asset_id)
        atomic_json(file,state);log(f'Reference original moved to Flow Trash ({len(state["deleted_ids"])} verified removals). Local renamed file retained.')
    remaining=scan()
    if remaining:raise RuntimeError('Some generated reference copies remain. Cleanup retained; upload waits until cleanup finishes.')
    # Invalidate only this browser/project upload receipt. The following upload
    # must verify the named files instead of trusting earlier gallery contents.
    cache=Path(config.get('agent_tool_dir') or Path(__file__).parent/'animate_flow_backend')/'logs/verified_reference_uploads.json'
    if cache.exists():
        data=json.loads(cache.read_text('utf-8'));url=config['flow_url'].rstrip('/')
        data={key:value for key,value in data.items() if key.split('|',1)[-1].rstrip('/')!=url};atomic_json(cache,data)
    state.update(complete=True);atomic_json(file,state)
    log('Generated reference originals removed from Flow. Uploading the verified renamed library next.')
