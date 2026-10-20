"""Download the Upscaled menu version of an exactly matched Flow video tile."""
import os
import re
from pathlib import Path
from ai_studio_pipeline import check_cancel, probe

MENU_ITEMS = r"""() => [...document.querySelectorAll('.cdk-overlay-container [role="menuitem"],.cdk-overlay-container mat-option,.cdk-overlay-container button')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height;}).map(e=>({text:(e.innerText||e.textContent||'').trim(),disabled:e.disabled||e.getAttribute('aria-disabled')==='true'}))"""
CLICK_ITEM = r"""text => {const matches=[...document.querySelectorAll('.cdk-overlay-container [role="menuitem"],.cdk-overlay-container mat-option,.cdk-overlay-container button')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&(e.innerText||e.textContent||'').trim()===text&&!e.disabled&&e.getAttribute('aria-disabled')!=='true';});if(matches.length!==1)return false;matches[0].click();return true;}"""
OPEN_MENU = r"""tile => {tile.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));let owner=tile,menu=null,direct=null;for(let d=0;owner&&d<8;d++,owner=owner.parentElement){if(owner.querySelectorAll('flow-video-tile').length>1)break;menu=owner.querySelector('button[aria-label="More options"]');direct=owner.querySelector('button[aria-label="Download batch"]')||direct;if(menu)break;}const b=menu||direct;if(!b||b.disabled||b.getAttribute('aria-disabled')==='true')return {ok:false};b.click();return {ok:true,direct:!menu};}"""

def choose_upscaled(items):
    options=[i for i in items if not i.get('disabled') and re.search(r'\bupscaled\b',i['text'],re.I) and not re.search(r'original',i['text'],re.I)]
    if len(options)!=1:raise RuntimeError('One unambiguous Upscaled option is required. Original size was not selected; saved progress retained.')
    return options[0]['text']

def download(page,asset_id,path,cancel,log):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',asset_id):raise ValueError('Invalid matched video asset identity')
    tile=page.locator(f'flow-video-tile[data-ai-studio-media="{asset_id}"]')
    if tile.count()!=1:raise RuntimeError('Matched video tile is unavailable; no other scene selected.')
    check_cancel(cancel);page.keyboard.press('Escape');tile.scroll_into_view_if_needed(timeout=10000);tile.hover(timeout=10000)
    opened=tile.evaluate(OPEN_MENU)
    if not opened.get('ok'):raise RuntimeError('Matched video Download menu is unavailable. Retry when Flow is ready.')
    if not opened.get('direct'):
        page.wait_for_function(r"() => [...document.querySelectorAll('.cdk-overlay-container [role=menuitem],.cdk-overlay-container button')].some(e=>e.getBoundingClientRect().width && /(?:^|\s)Download\s*$/i.test((e.innerText||'').trim()))",timeout=15000)
        items=page.evaluate(MENU_ITEMS)
        choices=[i for i in items if not i.get('disabled') and re.search(r'(?:^|\s)Download\s*$',i['text'],re.I)]
        if len(choices)!=1 or not page.evaluate(CLICK_ITEM,choices[0]['text']):raise RuntimeError('Could not select the matched video Download submenu.')
    page.wait_for_function(r"() => [...document.querySelectorAll('.cdk-overlay-container [role=menuitem],.cdk-overlay-container mat-option,.cdk-overlay-container button')].some(e=>e.getBoundingClientRect().width && /upscaled/i.test(e.innerText||''))",timeout=30000)
    text=choose_upscaled(page.evaluate(MENU_ITEMS))
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_name(target.stem+'.upscaled.downloading.mp4')
    log('Matched video: Download > '+text.replace('\n',' ')+'; waiting for the upscaled file.')
    with page.expect_download(timeout=90000) as pending:
        if not page.evaluate(CLICK_ITEM,text):raise RuntimeError('Upscaled menu item was not uniquely clickable. No original-size fallback.')
    transfer=pending.value
    try:
        check_cancel(cancel)
        transfer.save_as(str(temporary))
        check_cancel(cancel)
        from ai_studio_animate_media import valid_video
        if not valid_video(temporary):raise RuntimeError('Upscaled download is not a playable video; source progress retained.')
        _,streams=probe(temporary);video=next(s for s in streams if s.get('codec_type')=='video')
        if min(int(video.get('width',0)),int(video.get('height',0)))<720:raise RuntimeError('Downloaded Upscaled file is below 720p. File retained for review; scene not marked complete.')
        os.replace(temporary,target)
        log(f'Upscaled clip saved: {video["width"]}x{video["height"]}.')
        return {'download_version':'upscaled','download_width':video['width'],'download_height':video['height']}
    except BaseException:
        try:transfer.cancel()
        except Exception:pass
        raise
