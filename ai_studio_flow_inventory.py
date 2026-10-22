"""Read existing Flow media without relying on its virtualized thumbnail grid."""
import json
import re
import time
from urllib.parse import urlsplit


def response_images(text, project_id):
    def strings(value):
        if isinstance(value,str):yield value
        elif isinstance(value,list):
            for item in value:yield from strings(item)
    def walk(value):
        if not isinstance(value,list):return
        if (len(value)>5 and isinstance(value[0],str)
                and re.fullmatch(r'[a-f0-9-]{36}',value[0])
                and value[1]==project_id and isinstance(value[5],list)):
            meta=value[5]
            if len(meta)<7 or not isinstance(meta[5],str):return
            url=urlsplit(meta[5])
            if url.scheme!='https' or not (url.hostname or '').endswith('.googleusercontent.com') or not url.path.startswith('/asb/'):return
            prompts=[s for s in strings(meta[6]) if 'AS_SCENE_' in s]
            if not prompts:return
            prompt=prompts[0]
            if prompt.startswith(('Create one location identity reference.','Create one full-body character identity reference,')):return
            if len(set(re.findall(r'(?<![A-Za-z0-9_])AS_SCENE_[a-f0-9]+(?![A-Za-z0-9_])',prompt)))!=1:return
            yield {'asset_id':value[0],'src':meta[5],'kind':'image','busy':False,'failed':False,'visible':False,'prompt':prompt}
            return
        for item in value:yield from walk(item)
    found={}
    for line in text.splitlines():
        if not line.startswith('[['):continue
        try:envelope=json.loads(line)
        except ValueError:continue
        for entry in envelope:
            if not isinstance(entry,list) or len(entry)<3 or entry[0]!='wrb.fr' or not isinstance(entry[2],str):continue
            try:data=json.loads(entry[2])
            except ValueError:continue
            for image in walk(data):found[image['asset_id']]=image
    return list(found.values())


def read_project_images(page, cancel, log):
    from ai_studio_pipeline import check_cancel
    project_id=urlsplit(page.url).path.rstrip('/').split('/')[-1]
    if not re.fullmatch(r'[a-f0-9-]{36}',project_id):return []
    # Do not discard a user's unsubmitted editor draft to refresh the listing.
    if page.locator('[contenteditable="true"]').evaluate_all(
            "els => els.some(e => (e.innerText || '').trim())"):
        log('Unsubmitted editor text retained; using the existing grid for download inspection.')
        return []
    if page.locator('button').evaluate_all("""buttons => buttons.some(b => !b.disabled &&
            (/^stop(?: generation| generating)?$/i.test(b.getAttribute('aria-label') || b.innerText || '')
            || /stop-button|stop-icon-button/.test(b.className || '')))"""):
        log('Agent generation is active; keeping the page open and collecting without a reload.')
        return []
    images={}
    def receive(response):
        if not urlsplit(response.url).path.endswith('/data/batchexecute'):return
        try:
            for image in response_images(response.text(),project_id):images[image['asset_id']]=image
        except Exception:pass # A changed response format falls back to the grid.
    page.on('response',receive)
    try:
        log('Reading the existing project media index; no generation requests will be submitted.')
        page.reload(wait_until='domcontentloaded',timeout=30000)
        deadline=time.monotonic()+20
        while not images and time.monotonic()<deadline:
            check_cancel(cancel)
            page.wait_for_timeout(200)
    except Exception as error:
        check_cancel(cancel)
        log('Project media index could not finish loading; continuing with the existing grid: '+str(error))
    finally:page.remove_listener('response',receive)
    log(f'Existing media index: {len(images)} labeled scene image assets found.')
    return list(images.values())
