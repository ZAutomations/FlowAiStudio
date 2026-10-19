from __future__ import annotations
import hmac,json,os,secrets,shutil,sys
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from .storage import ROOT,Store,public,read,redact
from .jobs import Jobs

def validate(kind,p,settings):
    if kind not in ('studio','animate'):raise ValueError('Only AI Studio and Animate are supported')
    if not isinstance(p,dict) or not p.get('project'):raise ValueError('Choose a project folder')
    if p.get('voice_engine','google_cloud') not in ('google_cloud','local','piper'):raise ValueError('Choose Gemini TTS, Kokoro or Piper')
    from ai_studio_narration import validate as narration
    narration(p)
    from ai_studio_manual_batches import export_batch_size
    export_batch_size(p)
    value=p.get('image_batch_size',6)
    try:
        count=int(value)
        if isinstance(value,bool) or count<1 or float(value)!=count:raise ValueError()
    except (TypeError,ValueError,OverflowError):raise ValueError('Image batch size must be a positive integer')
    if not 3<=float(p.get('shot_seconds',7))<=20:raise ValueError('Shot target must be 3–20 seconds')
    from ai_studio_parts import scene_range
    if kind=='animate':
        from ai_studio_animate_options import animation_count
        animation_count(p,0)
    if p.get('dsp_malik_reference_path'):
        from ai_studio_pipeline import valid_image
        if not valid_image(p['dsp_malik_reference_path']):raise ValueError('Choose a valid DSPMalik image')
def create_app(store=None, jobs=None, token=None):
    store = store or Store()
    jobs = jobs or Jobs(store)
    token = token or secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.jobs, app.state.token = (store, jobs, token)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def security(request: Request, call_next):
        if request.url.path.startswith('/api/'):
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': 'Foreign origin rejected'}, status_code=403)
            if not hmac.compare_digest(request.headers.get('x-desktop-token', ''), token):
                return JSONResponse({'detail': 'Local session required'}, status_code=401)
        result = await call_next(request)
        result.headers['Cache-Control'] = 'no-store'
        result.headers['X-Content-Type-Options'] = 'nosniff'
        result.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return result

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({'detail': redact(error, store.settings())}, status_code=400)

    @app.get('/')
    def index():
        html = (ROOT / 'desktop/ui/index.html').read_text('utf-8')
        return HTMLResponse(html.replace('__SESSION__', token))

    @app.get('/api/state')
    def state():
        return {**store.snapshot(), 'drafts': store.drafts(), 'jobs': jobs.list(), 'templates': [p.stem for p in (store.root / 'templates').glob('*.json')], 'health': {'ffmpeg': bool(shutil.which('ffmpeg')), 'python': sys.version.split()[0]}}

    @app.get('/api/jobs')
    def list_jobs():
        return jobs.list()

    @app.post('/api/settings/{section}')
    def save(section: str, patch: dict):
        store.update(section, patch)
        return {'ok': True}

    @app.post('/api/credentials')
    def credentials(patch: dict):
        key=patch.get('key','');value=patch.get('value')
        if key in ('gemini_service_account','service_account_path'):
            path=Path(str(value)).expanduser()
            if not path.is_file():raise ValueError('Choose an existing service-account JSON file')
            data=json.loads(path.read_text('utf-8'))
            if data.get('type')!='service_account':raise ValueError('This JSON is not a Google service account')
            private=ROOT/'private/google_service_account.json';private.parent.mkdir(exist_ok=True)
            if path.resolve()!=private.resolve():shutil.copy2(path,private)
            value=str(private)
        store.credential(key,value)
        return {'ok': True}

    @app.post('/api/drafts')
    def drafts(body: dict):
        if public(body) != body:
            raise ValueError('Credentials cannot be saved in drafts')
        with store.lock:
            from .storage import atomic
            atomic(store.root / '.desktop/drafts.json', body)
        return {'ok': True}

    @app.post('/api/jobs/clear-finished')
    def clear_finished_jobs():
        return {'removed': jobs.clear_finished()}

    @app.post('/api/jobs/{job_id}/{action}')
    def control(job_id: str, action: str):
        if action == 'stop':
            jobs.stop(job_id)
            return {'ok': True}
        if action == 'retry':
            return jobs.retry(job_id)
        raise ValueError('Unknown job action')

    @app.get('/api/studio/metadata')
    def studio_metadata():
        from .studio import metadata
        return metadata(store.settings(), store.root)

    @app.get('/api/studio/accounts')
    def studio_accounts():
        from .browser_accounts import profiles
        return profiles(store.root)

    @app.get('/api/animate/metadata')
    def animate_metadata():
        from .animate import metadata
        return metadata(store.settings(), store.root)

    @app.post('/api/animate/preset')
    def animate_preset(body: dict):
        from .animate import save_preset
        return save_preset(body.get('name', ''), body.get('options', {}), store.root)

    @app.post('/api/studio/accounts')
    def studio_add_account(body: dict):
        from .browser_accounts import add
        return add(body.get('label', ''), store.root)

    @app.post('/api/studio/import')
    def studio_import(body: dict):
        path = Path(body.get('path', '')).expanduser().resolve()
        if not path.is_file():
            raise ValueError('Choose an existing script file')
        if path.stat().st_size > 5000000:
            raise ValueError('Script file is too large')
        return {'script': path.read_text('utf-8', errors='replace')}

    @app.post('/api/studio/references')
    def studio_references(body: dict):
        import base64
        import io
        from PIL import Image
        project = Path(body.get('project', '')).expanduser().resolve()
        data = read(project / 'project.json')
        if not isinstance(data.get('scenes'), list):
            raise ValueError('Open or create a project first')
        from .studio import reference_inventory
        inventory = reference_inventory(project, data)
        previews = []
        for ref in inventory['references']:
            path = Path(ref['path'])
            try:
                with Image.open(path) as original:
                    image = original.convert('RGB')
                    image.thumbnail((360, 240))
                    buffer = io.BytesIO()
                    image.save(buffer, format='JPEG', quality=85)
                previews.append({'name': path.stem, 'path': str(path), 'image': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')})
            except (OSError, ValueError):
                continue
        return {'references': previews, 'expected': inventory['expected'], 'missing': inventory['missing']}

    @app.post('/api/studio/cast-review')
    def studio_cast_review(body: dict):
        project = Path(body.get('project', '')).expanduser().resolve()
        data = read(project / 'cast_analysis.json')
        from ai_studio_cast import MASTER_PROMPT
        return {'analysis': data or None, 'master_prompt': MASTER_PROMPT}

    @app.post('/api/studio/excel')
    def studio_excel(body: dict):
        from .studio_batch import workbook
        return workbook(body.get('path', ''), body.get('sheet'))

    @app.post('/api/project')
    def project(body: dict):
        path = Path(body['path']).expanduser().resolve()
        if path.is_dir():
            path /= 'project.json'
        if path.name != 'project.json':
            raise ValueError('Select a project.json file or its folder')
        data = read(path)
        if not isinstance(data.get('scenes'), list):
            raise ValueError('This is not an AI Studio project')
        return {'path': str(path.parent), 'data': public(data)}
    @app.post('/api/jobs')
    def submit(body:dict):
        kind=body.get('kind');payload=body.get('payload',{})
        if kind not in ('studio','animate','studio-batch','animate-batch'):raise ValueError('Only AI Studio and Animate jobs are supported')
        settings=store.worker_settings();patch=body.get('settings',{})
        if not isinstance(patch,dict) or public(patch)!=patch:raise ValueError('Invalid settings')
        settings.update(patch)
        from .studio import prepare
        if kind.endswith('-batch'):
            from .studio_batch import prepare_batch
            payload=prepare_batch(payload,settings,store.root/'.desktop',[],animated=kind=='animate-batch')
            for row in payload['rows']:validate('animate' if kind=='animate-batch' else 'studio',{**payload,**row,'action':'build'},settings)
        else:
            if kind=='animate' and payload.get('action') in ('new','import'):
                payload=dict(payload);source=payload.pop('project','');payload['animate_source']=payload.get('animate_source') or source
                payload.pop('source_project',None)
            occupied=[j['payload'].get('project') for j in jobs.list() if j['state'] not in ('completed','failed','stopped','interrupted') and j['payload'].get('project')]
            payload=prepare(payload,settings,occupied);validate(kind,payload,settings)
        return jobs.submit(kind,payload,settings)

    @app.get('/api/configuration')
    def configuration():
        return read(ROOT/'desktop/ui/configuration.json')

    app.mount('/assets' , StaticFiles(directory=ROOT / 'desktop/ui'), name='assets')
    return app
