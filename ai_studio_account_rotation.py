"""Quota and explicit user-selected handover for reference-based Flow images."""
import json
from pathlib import Path
from ai_studio_pipeline import atomic_json, fingerprint, check_cancel, valid_image
from desktop.browser_accounts import profiles, browser_options


def select_account(config, previous, cancel, log):
    """Explicit user-selected account handover, independent of quota detection.

    Local outputs remain authoritative; old remote requests stay archived with
    their original account/project rather than being matched in the new project.
    """
    account=config.get('browser_account','')
    old_account=previous.get('browser_account','')
    if account==old_account:return
    if not config.get('character_consistency') or config.get('provider','flow')!='flow':
        raise ValueError('Changing accounts in an existing project currently requires reference-based Flow image generation.')
    opts=browser_options({**config,'provider':'flow'})
    profile=Path(opts.get('profile_dir',Path(__file__).parent/'zbot_profiles'))
    if config.get('browser_type','chrome')=='edge':profile=profile/'edge'
    profile=profile/('profile_gemini' if config.get('share_google_profile',True) else 'profile_flow')
    if not profile.is_dir():
        raise ValueError('Sign in to the selected browser account using Login first. Existing project and progress are retained.')
    root=Path(config['project']);file=root/('animate_media.json' if config.get('workflow')=='animate' else 'studio_agent_images.json')
    state=json.loads(file.read_text('utf-8')) if file.exists() else None
    from ai_studio_animate_media import valid_video
    def valid_output(record):return valid_video(record['output']) if record.get('kind')=='video' else valid_image(record['output'])
    if state:
        active=state.get('account_binding',{}).get('account',old_account)
        if active==account:
            binding=state['account_binding']
            config.update(browser_account=account,flow_url=binding['flow_url'],_rotation_scope=True,
                          _rotation_restored=True,_reference_flow_url=state['reference_flow_url'])
            return
        if active!=old_account:
            raise ValueError('The project account changed since this screen was loaded. Reopen the saved project before selecting another account.')
        for record in state.get('records',[]):
            if record.get('status')=='complete' and not valid_output(record):
                raise RuntimeError('A completed scene image is missing locally. Recover it using its original account before switching.')
    check_cancel(cancel)
    from ai_studio_animate_setup import ensure_project
    target={**config,'flow_url':'','auto_project':True,'_rotation_scope':True,'_rotation_restored':False}
    if not target.get('agent_tool_dir'):target['agent_tool_dir']=str(Path(__file__).parent/'animate_flow_backend')
    log('Selected another saved browser account. Preparing its separate Flow project; local references and completed scene images are retained.')
    url=ensure_project(target,cancel,log)
    check_cancel(cancel)
    old_url=previous.get('flow_url','')
    reference_url=(state or {}).get('reference_flow_url') or previous.get('_reference_flow_url') or old_url
    history=root/'account_history'/fingerprint('manual-selection',old_account,account,old_url,url,state)
    history.mkdir(parents=True,exist_ok=True)
    atomic_json(history/'binding.json',{'account':old_account,'flow_url':old_url,'new_account':account,'new_flow_url':url})
    if state:
        atomic_json(history/file.name,state)
        sessions=[row for row in state.get('account_sessions',[]) if row['account']!=old_account]
        sessions.append({'account':old_account,'flow_url':old_url,'status':'manually_switched',
                         'models':state.get('exhausted_image_models',[])})
        state.update(account_sessions=sessions,account_binding={'account':account,'flow_url':url},
                     reference_flow_url=reference_url,
                     identity=fingerprint([(r['key'],r['index']) for r in state['records']],url),
                     exhausted_image_models=[],active_image_model=state.get('preferred_image_model','Nano Banana Pro'))
        state.pop('quota_verified_missing',None)
        for record in state['records']:
            if valid_output(record):
                record['status']='complete'
                record.setdefault('source_account',old_account);record.setdefault('source_flow_url',old_url)
            else:
                record.update(status='pending',handover_unsubmitted=True)
                for key in ('asset_id','preparation_started','generation_model','pause_reason','last_error'):record.pop(key,None)
        # The archived manifest retains uncertain IDs for recovery on the old account.
    for name in ('references/image_batches.json','manual_reference_images.json','reference_agent_media.json'):
        source=root/name
        if source.exists():
            destination=history/name;destination.parent.mkdir(parents=True,exist_ok=True)
            source.replace(destination)
    if state:atomic_json(file,state)
    config.update(browser_account=account,flow_url=url,_rotation_scope=True,_rotation_restored=True,
                  _reference_flow_url=reference_url)
    log('Account selection applied. Reusing valid local references; missing references can be generated and all references uploaded in the selected account. Prior remote request identities are archived under account_history.')


def account_order(config):
    rows=profiles()
    lookup={row['id']:row['id'] for row in rows}
    lookup.update({row['label'].casefold():row['id'] for row in rows})
    raw=config.get('account_fallback_order','')
    if not isinstance(raw,str):raise ValueError('Account fallback order must contain saved account labels separated by commas.')
    order=[]
    for value in raw.replace('\n',',').split(','):
        value=value.strip()
        if not value:continue
        account=lookup.get(value) or lookup.get(value.casefold())
        if account is None:raise ValueError('Unknown fallback account: '+value+'. Add its profile and sign in first.')
        if account not in order:order.append(account)
    return order


def restore(config):
    """Use the manifest binding even if the UI/job carries an older account."""
    file=Path(config['project'])/('animate_media.json' if config.get('workflow')=='animate' else 'studio_agent_images.json')
    if not file.is_file():return
    state=json.loads(file.read_text('utf-8'))
    active=state.get('account_binding')
    if not active:return
    supplied=config.get('browser_account','')
    allowed={row.get('account','') for row in state.get('account_sessions',[])}|{active['account']}
    if supplied not in allowed:
        raise ValueError('This project has a saved account handover. Select its original or active account to resume.')
    config.update(browser_account=active['account'],flow_url=active['flow_url'],
                  _rotation_scope=True,_rotation_restored=True,
                  _reference_flow_url=state['reference_flow_url'])
    browser_options({**config,'provider':'flow'})


def handover(config,cancel,log):
    """Called only after all model quotas and a verified idle missing batch."""
    if not config.get('account_fallback'):
        raise RuntimeError('All configured image models reached quota. Account fallback is disabled. Progress saved.')
    if not config.get('image_agent') or config.get('provider')!='flow':
        raise ValueError('Account fallback currently supports reference-based Flow Agent image batches only.')
    check_cancel(cancel)
    file=Path(config['project'])/'studio_agent_images.json'
    state=json.loads(file.read_text('utf-8'))
    verified=set(state.get('quota_verified_missing',[]))
    if not verified:raise RuntimeError('Account handover requires verified missing requests after model quota exhaustion.')
    records=state['records']
    for record in records:
        uncertain=record.get('status') in ('submitting','submitted','matched') or record.get('preparation_started')
        if record['status']!='complete' and uncertain and record['index'] not in verified:
            raise RuntimeError('Recover other uncertain scene requests before switching accounts. Progress retained.')
    current=config.get('browser_account','')
    sessions=state.get('account_sessions',[])
    exhausted={row['account'] for row in sessions if row.get('status')=='quota_exhausted'}|{current}
    next_account=next((account for account in account_order(config) if account not in exhausted),None)
    if next_account is None:
        raise RuntimeError('All selected fallback accounts have been tried. Progress saved; wait for quota or add another signed-in profile.')
    opts=browser_options({**config,'browser_account':next_account,'provider':'flow'})
    if not Path(opts['profile_dir']).is_dir():
        raise RuntimeError('The next account has no saved browser profile. Select it, click Login (once), and sign in before resuming.')
    from ai_studio_animate_setup import ensure_project
    next_config={**config,'browser_account':next_account,'flow_url':'','auto_project':True,
                 '_rotation_scope':True,'_rotation_restored':False}
    label=next(row['label'] for row in profiles() if row['id']==next_account)
    log('Account model quotas exhausted. Preparing saved account '+label+'; existing local images and reference files are retained.')
    url=ensure_project(next_config,cancel,log)
    check_cancel(cancel)
    old_url=config['flow_url']
    # Archive every request identity before changing its account/project binding.
    atomic_json(file.parent/'account_history'/(fingerprint(state)+'.json'),state)
    sessions=[row for row in sessions if row['account']!=current]
    sessions.append({'account':current,'flow_url':old_url,'status':'quota_exhausted',
                     'models':state.get('exhausted_image_models',[])})
    state.update(account_sessions=sessions,account_binding={'account':next_account,'flow_url':url},
                 reference_flow_url=state.get('reference_flow_url',old_url),
                 identity=fingerprint([(r['key'],r['index']) for r in records],url),
                 exhausted_image_models=[],active_image_model=state.get('preferred_image_model','Nano Banana Pro'))
    state.pop('quota_verified_missing',None)
    for record in records:
        if record['status']=='complete':
            if not valid_image(record['output']):raise RuntimeError('A completed local image is missing; recover it before switching accounts.')
            record.setdefault('source_account',current);record.setdefault('source_flow_url',old_url)
        else:
            record['status']='pending'
            record['handover_unsubmitted']=True
            for key in ('asset_id','preparation_started','generation_model','pause_reason','last_error'):record.pop(key,None)
    atomic_json(file,state) # one authoritative, restart-safe handover commit
    config.update(browser_account=next_account,flow_url=url,_rotation_scope=True,_rotation_restored=True,
                  _reference_flow_url=state['reference_flow_url'])
    log('Account switched to '+label+'. Using its saved Flow project; only unfinished images will be generated. Exact named local references will be uploaded by the Agent preparation step.')
