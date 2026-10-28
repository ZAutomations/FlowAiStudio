"""Checkpointed recovery of persistent generic Flow failures, never restrictions."""
import json,time
from pathlib import Path
from ai_studio_pipeline import atomic_json,valid_image,check_cancel

WAIT_SECONDS=300

def generic_error(text):
    text=str(text).lower()
    blocked=('unusual activity','unusual-activity','usage limit','quota','policy','policies','permission denied','sign in','sign-in','captcha','unsupported region')
    return ('something went wrong' in text and not any(word in text for word in blocked))

def recover(adapter,q,config,error,animated=False,now=None):
    if not config.get('account_fallback') or config.get('provider')!='flow' or not config.get('character_consistency'):return False
    if config.get('action') not in ('images','generate-missing','cinematic-images','build'):return False
    root=Path(config['project']);file=root/'generic_failure_recovery.json'
    state=json.loads(file.read_text('utf-8')) if file.exists() else {}
    text=str(error);account=config.get('browser_account','');url=config.get('flow_url','')
    count=sum(valid_image(s.get('image_path','')) for s in adapter.zb_scenes)
    scope=(account,url,count)
    waiting=tuple(state.get('scope',[]))==scope and state.get('first_failure') is not None
    if not generic_error(text):
        if not waiting or 'ACTION REQUIRED: Existing submission remains unresolved' not in text:return False
    clock=time.time() if now is None else now
    if not waiting:state.update(scope=list(scope),first_failure=clock,compiled=None)
    state.update(last_failure=clock,error=text)
    atomic_json(file,state)
    elapsed=max(0,clock-state['first_failure'])
    if elapsed<WAIT_SECONDS:
        raise RuntimeError(f'Flow temporary failure recovery: same generic error, {elapsed:.0f}/300s without image progress. Saved submissions are recovered before any account handover; no new audit or duplicate generation.') from error
    check_cancel(adapter._zb_cancel)
    from ai_studio_account_rotation import account_order,select_account
    tried=set(state.get('tried_accounts',[]))|{account}
    next_account=next((a for a in account_order(config) if a not in tried),None)
    if next_account is None:raise RuntimeError('ACTION REQUIRED: No untried saved fallback account remains. Progress retained; sign in to another saved profile or wait.') from error
    # Resolve an actually signed-in profile before spending time rendering.
    from desktop.browser_accounts import browser_options
    opts=browser_options({**config,'browser_account':next_account,'provider':'flow'})
    profile=Path(opts['profile_dir'])
    if config.get('browser_type')=='edge':profile=profile/'edge'
    profile=profile/('profile_gemini' if config.get('share_google_profile',True) else 'profile_flow')
    if not profile.is_dir():raise RuntimeError('ACTION REQUIRED: Next fallback profile is not signed in. Use Login first; current progress retained.')
    end=0
    for scene in adapter.zb_scenes:
        if not valid_image(scene.get('image_path','')):break
        end+=1
    log=lambda message:q.put(('log','info',message))
    if end and state.get('compiled')!=end:
        from ai_studio_parts import compile_part
        log(f'Persistent generic Flow failure: compiling contiguous saved scenes 1–{end} before switching account. No missing scenes skipped.')
        result=compile_part(adapter,q,{**config,'scene_start':1,'scene_end':end},animated=animated)
        if not result.get('video'):raise RuntimeError('Recovery part did not produce a video; account unchanged.')
        state['compiled']=end;state['part']=result;atomic_json(file,state)
    elif not end:log('No contiguous saved scenes from scene 1; preserving isolated completed assets. No empty part rendered.')
    # Existing handover archives uncertain requests with the old project and
    # preserves valid local outputs. Never claim old in-flight work was absent.
    previous=dict(config);target={**config,'browser_account':next_account,'flow_url':'','auto_project':True}
    if animated:target['workflow']='animate'
    select_account(target,previous,adapter._zb_cancel,log)
    config.update(target)
    adapter._zb_save_project(config)
    state.update(tried_accounts=sorted(tried),scope=None,first_failure=None,switched_to=next_account)
    atomic_json(file,state)
    from ai_studio_consistency import ensure_uploaded_reference_library
    log('Uploading/reusing the complete local reference library before continuing scene generation in the selected account.')
    ensure_uploaded_reference_library(config,adapter._zb_cancel,log)
    adapter._zb_save_project(config)
    return True
