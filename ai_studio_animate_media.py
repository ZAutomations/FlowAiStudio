"""Durable mixed image/video batches for the isolated Animate workflow."""
from __future__ import annotations
import base64
import copy
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from ai_studio_pipeline import atomic_json, check_cancel, fingerprint, image_prompt, probe, valid_image, run_ffmpeg
from zbot_browser_images import ZBotImageGenerator
from ai_studio_animate_options import animation_count, clip_seconds
from ai_studio_image_models import IMAGE_MODELS, preferred, quota_model, quota_models, ModelQuotaExhausted, ImageModelsExhausted


class MissingAgentOutputs(RuntimeError):
    """A settled, fully walked grid has no assets for these saved requests."""
    pass


def scene_tracking_tokens(text):
    """Only exact labels count; invented _1/_2 variants are other identities."""
    import re
    return set(re.findall(r'(?<![A-Za-z0-9_])AS_SCENE_[a-f0-9]+(?![A-Za-z0-9_])',text or ''))


def agent_label_conflicts(reply,records):
    """An Agent audit cannot rename an unrelated asset to a requested scene."""
    import re
    wanted={r['index']+1:r['token'] for r in records if r['status']!='complete'}
    pairs=re.findall(r'\bOUTPUT\s+(\d+)\s*[/|—–:]\s*(AS_SCENE_[A-Za-z0-9_]+)',reply or '',re.I)
    return sorted({int(number) for number,token in pairs if int(number) in wanted and token!=wanted[int(number)]})


def label_conflict_message(conflicts):
    return ('Flow Agent used incorrect tracking labels for scene(s) '+', '.join(map(str,conflicts))+
            '. Its claimed outputs do not match the submitted scene identities. Saved images are retained; no unrelated image was renamed and no automatic regeneration was submitted. Retry with the exact identity table or review the affected outputs.')


def wrong_batch_reply(reply,records):
    """An explicit response naming only other OUTPUT numbers is not this batch."""
    import re
    numbers={int(n) for n in re.findall(r'\bOUTPUT\s+(\d+)\b',reply,re.I)}
    expected={r['index']+1 for r in records}
    return bool(numbers) and numbers.isdisjoint(expected)


def wait_agent_ready(page,cancel,log,timeout=60):
    predicate=(Path(__file__).parent/"animate_flow_backend"/"agent_submit_ready.js").read_text("utf-8").split("if (typeof module")[0]+"\nagentSubmitReady"
    predicate="() => {"+predicate.replace("\nagentSubmitReady","\nreturn agentSubmitReady();")+"}"
    deadline=time.monotonic()+timeout
    reported=False
    while True:
        check_cancel(cancel)
        ready=page.evaluate(predicate)
        if ready:return
        if time.monotonic()>=deadline:
            raise RuntimeError(f'Agent controls did not become ready within {timeout}s. No generation submitted; prepared prompt and references retained. Retry resumes this batch.')
        if not reported:
            log('Waiting up to 60s for Agent controls and attached images to finish loading; checking again automatically.')
            reported=True
        time.sleep(.5)


def update_batch_progress(state):
    by_token={r['token']:r for r in state['records']}
    # Per-kind watermarks never jump across a missing scene. Batch size changes
    # do not invalidate the individual downloaded receipts.
    state['scene_progress']={}
    for kind in ('image','video'):
        rows=sorted((r for r in state['records'] if r['kind']==kind),key=lambda r:r['index'])
        through=0
        for row in rows:
            if row.get('status')!='complete':break
            through=row['index']+1
        state['scene_progress'][kind]={'downloaded_through':through,
            'completed_scene_numbers':[r['index']+1 for r in rows if r.get('status')=='complete']}
    for batch in state.get('batch_progress',{}).values():
        rows=[by_token[t] for t in batch['tokens'] if t in by_token]
        batch['generated_successfully']=bool(rows) and len(rows)==len(batch['tokens']) and all(
            r.get('status') in ('matched','complete') for r in rows)
        batch['downloaded_successfully']=bool(rows) and len(rows)==len(batch['tokens']) and all(
            r.get('status')=='complete' for r in rows)


def valid_video(path):
    if not path or not Path(path).is_file():return False
    try:
        duration, streams = probe(path)
        return duration > .05 and any(s.get('codec_type') == 'video' and int(s.get('width',0)) > 0 for s in streams)
    except Exception:
        return False


def media_plan(scenes, config):
    from zbot_ai_tab import RES_ASPECT
    aspect=RES_ASPECT.get(config['resolution'],'16:9')
    references=[(Path(p).name,fingerprint(Path(p).read_bytes().hex())) for p in config.get('references',[]) if Path(p).is_file()]
    records=[]
    animated = animation_count(config, len(scenes), scenes)
    for i, scene in enumerate(scenes):
        scene_refs=config.get('scene_reference_map')
        used=sorted(scene_refs[i]) if scene_refs is not None else None
        selected_references=[r for r in references if used is None or Path(r[0]).stem in used]
        kind='video' if i < animated and not config.get('image_agent') else 'image'
        prompt=image_prompt(scene,config['style'],aspect,config.get('continuity',''))
        from ai_studio_story import is_narration_story, scene_direction, video_direction, narration_direction
        if is_narration_story(config):prompt=video_direction(prompt,narration_direction(config),clip_seconds(config),config.get('animate_multishot',False)) if kind=='video' else scene_direction(prompt,narration_direction(config))
        elif kind=='video' and config.get('animate_multishot'):prompt=video_direction(prompt,'Silent on-screen characters; local narration is added separately.',clip_seconds(config),True)
        if kind=='video' and config.get('animate_multishot') and scene.get('shots'):
            prompt+='\nTIMED SHOTS INSIDE THIS SINGLE CLIP (not separate outputs): '+json.dumps(scene['shots'],ensure_ascii=False)
        if scene.get('cinematic_continuity'):
            prompt+='\nLOCKED FILM CONTINUITY: '+json.dumps(scene['cinematic_continuity'],ensure_ascii=False)
        key=fingerprint('animate-v2',i,kind,clip_seconds(config) if kind=='video' else 0,prompt,config.get('animate_model') if kind=='video' else 'Nano Banana',selected_references)
        if used is not None:key=fingerprint('scene-cast-v1',key,used)
        token='AS_SCENE_'+key[:20]
        records.append({'index':i,'kind':kind,'key':key,'token':token,'prompt':prompt,
                        'continuity_source_key':__import__('ai_studio_continuity_ledger').scene_key(scene),
                        'shots':scene.get('shots',[]),
                        **({'reference_names':used} if used is not None else {}),
                        'output':str(Path(config['project'])/('videos' if kind=='video' else 'images')/f'scene_{i+1:04d}.{"mp4" if kind=="video" else "png"}')})
    return records


RETRY_SAFE_BATCH_INSTRUCTIONS = """MANDATORY EXISTING-OUTPUT CHECK BEFORE ANY GENERATION, INCLUDING RETRY AND MODEL FALLBACK:
Inspect this project's existing gallery, saved generation prompts and current generation activity for EACH requested exact AS_SCENE tracking label and OUTPUT number. Check only the requested identities; do not confuse earlier story batches, reference images or similar-looking pictures with these scenes.
If a completed matching output already exists, reuse it and do NOT generate another copy, variant, upscale-as-new-scene or replacement. Report: 'Already generated: OUTPUT <number> / <exact label>. I will not regenerate it; reuse the existing asset.' Include the existing asset identity when available.
If ALL requested outputs already exist, submit ZERO generation requests. Confirm the batch already exists and list the existing identities so the downloader can collect them.
If only PART of the batch exists, list existing versus confirmed missing scene labels first. Generate ONLY the confirmed missing identities, exactly ONE image per missing scene (x1). Retain each original scene number, exact tracking label, assigned references and settings; never renumber the missing subset or recreate the full batch.
A queued, processing or still-generating matching request is NOT missing: wait for it; do not submit a duplicate. If identity/existence cannot be verified, report 'Uncertain — existing output could not be verified' and do not regenerate that scene on a guess. A failed download, stale gallery, quota warning or inability to see an earlier tile does not prove the image was never generated.
Finish with an audit listing existing/reused, newly generated, pending and uncertain OUTPUT numbers with their exact tracking labels. Never claim the whole batch is complete while any requested identity is unresolved. These rules override any older instruction to generate the entire batch again.
"""


def parse_missing_audit(reply,records,audit_id):
    """Accept a fresh, exhaustive provider audit; never infer missing from a scan."""
    decoder=json.JSONDecoder();data=None
    for i,c in enumerate(reply or ''):
        if c!='{':continue
        try:value,_=decoder.raw_decode(reply[i:])
        except ValueError:continue
        if isinstance(value,dict) and value.get('audit_id')==audit_id:data=value;break
    if not data or data.get('generation_allowed') is not True:return []
    rows=data.get('outputs')
    if not isinstance(rows,list) or len(rows)!=len(records):return []
    wanted={(r['index']+1,r['token']) for r in records};seen=set();missing=[]
    for row in rows:
        if not isinstance(row,dict):return []
        pair=(row.get('scene'),row.get('token'))
        if pair not in wanted or pair in seen:return []
        seen.add(pair)
        if row.get('status')=='missing' and row.get('checked_saved_prompts') is True:missing.append(pair)
        elif row.get('status') not in ('existing','processing','blocked','uncertain'):return []
    return [r for r in records if (r['index']+1,r['token']) in missing]


def audit_missing_outputs(generator,records,config,cancel,log):
    """Ask Flow to inspect exact IDs without generating anything, then reconcile."""
    import uuid
    audit_id=uuid.uuid4().hex
    table=[{'scene':r['index']+1,'token':r['token']} for r in records]
    prompt=('AUDIT ONLY. DO NOT GENERATE, retry, edit, rename or delete ANY media. '
        'Inspect saved media generation prompts and in-flight jobs for these EXACT output identities. '
        'Output numbers alone and similar pictures do not prove identity. A gallery search miss alone is uncertain. '
        'If policy refusal, unusual activity or a current generation restriction prevents continuation, set generation_allowed false. '
        'For every requested identity, return status existing, processing, missing, blocked or uncertain. '
        'Use missing only after checking saved generation prompts and confirming there is no matching output or in-flight request. '
        'Return ONLY JSON: {"audit_id":"'+audit_id+'","generation_allowed":true,"outputs":'
        '[{"scene":1,"token":"EXACT REQUESTED TOKEN","status":"missing","checked_saved_prompts":true}]}. '
        'Use the exact scene/token pairs below. No generation is authorized by this audit.\n'+json.dumps(table))
    path=Path(config['project'])/'agent_missing_audit.txt';path.write_text(prompt,encoding='utf-8')
    log('Reconciling only unresolved scene identities with Flow Agent (audit only; no image generation).')
    with generator._session(headless=False) as ctx:
        page=generator._batch_page(ctx)
        prepare_batch_prompt({**config,'references':[],'reference_descriptions':{},'_agent_cdp_port':generator.cdp_port},path,cancel,log)
        composer=page.locator('div.ProseMirror[contenteditable=true]').first
        if audit_id not in composer.inner_text():raise RuntimeError('Reconciliation audit was not prepared correctly; no resubmission authorized.')
        wait_agent_ready(page,cancel,log)
        page.locator('button[aria-label="Start generation"]').first.click(timeout=5000)
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            check_cancel(cancel)
            reply=generator._agent_batch_reply(page,records)
            verified=parse_missing_audit(reply,records,audit_id)
            if verified:
                atomic_json(Path(config['project'])/'agent_missing_audit.json',{'audit_id':audit_id,'requested':table,'reply':reply,'confirmed_missing':[r['index']+1 for r in verified]})
                return verified
            # A complete negative audit is retained and must not lead to generation.
            if audit_id in reply and '"outputs"' in reply and '}' in reply:
                try:
                    for i,c in enumerate(reply):
                        if c=='{':
                            data,_=json.JSONDecoder().raw_decode(reply[i:])
                            if isinstance(data,dict) and data.get('audit_id')==audit_id:
                                atomic_json(Path(config['project'])/'agent_missing_audit.json',{'audit_id':audit_id,'requested':table,'reply':reply,'confirmed_missing':[]})
                                return []
                except ValueError:pass
            time.sleep(1)
    raise RuntimeError('Flow did not provide a complete exact-identity audit. No uncertain scenes resubmitted; saved progress retained.')


def explicit_missing_recovery(config):
    """Only an explicit user stage may retry a previously submitted identity."""
    return config.get('_generate_missing') is True

def batch_prompt(records,config):
    from ai_studio_story import is_narration_story, narration_direction
    from ai_studio_visual_context import TOPIC_DIRECTION,MEANING_DIRECTION
    lines=['Reconcile the numbered media outputs below, reusing existing outputs and generating only confirmed missing identities. One separate asset per scene; no combined film, collage or storyboard.',
           'IMAGES: exactly ONE image per scene (x1 / number_of_images=1), never 2x, x2, x3 or x4. Override any default requesting multiple variations. No alternate versions or quality-selection variants. A batch of N scenes means N total images. Once one image for a scene exists, it is complete; do not request a second variation, including during model fallback.',
           ('Use the attached named character AND location reference image pixels in EVERY output. Preserve the same faces, clothing, colors and visual style.' if config.get('references') else 'No reference images attached. Follow each scene subject and the selected visual style; do not invent a recurring named cast or force a fixed story location.'),
           'Output aspect ratio: '+config.get('aspect','16:9')+'. '+('All images MUST be 16:9 landscape, width greater than height. Never generate portrait, vertical or square images; keep this ratio through every model fallback.' if config.get('aspect','16:9')=='16:9' else 'This aspect ratio was explicitly selected. Keep it through every model fallback.'),
           ('Permanent reference names: '+', '.join(Path(p).stem for p in config.get('references',[]))+'. Character/location bible: '+json.dumps(config.get('reference_descriptions',{}),ensure_ascii=False)+'. Keep story roles mapped to these same named assets.' if config.get('references') else 'Choose subjects, objects, environments and explanatory visual actions from the scene prompts. Do not introduce CharacterA, CharacterB or StoryPlace.'),
           ('All listed scene outputs must be VIDEO clips. Use '+config['animate_model']+'.' if all(r['kind']=='video' for r in records)
            else 'For images use Nano Banana. For videos use '+config['animate_model']+'.'),
           'Videos: silent characters, no dialogue, narration, music or captions. Add subtle natural character action and camera movement. Duration exactly '+str(clip_seconds(config))+' seconds. '+'Each VIDEO output is one edited clip containing TWO distinct shots by default, THREE only when the narration genuinely needs a third visual beat, never four, with visible hard cuts timed to its narration. Follow its edit decision list below. Do not create separate outputs per shot or a simultaneous collage/storyboard.',
           'IMPORTANT: Begin each individual media generation prompt with its exact AS_SCENE tracking reference, verbatim as plain prompt text. Keep it in the saved generation prompt, not only in your chat reply or tool metadata. It is a tracking label; do not display or speak it in the media. Never omit, shorten or replace the tracking reference.',
           'Generate only this batch. Do not regenerate earlier scenes.']
    if any(r['kind']=='video' for r in records):
        from ai_studio_animate_options import video_settings
        quality,ratio=video_settings(config)
        lines.append(f'VIDEO SETTINGS - mandatory for every video output: use ONLY {config["animate_model"]}, resolution {quality}, aspect ratio {ratio}. Apply these settings in the video generation tool. Do not substitute another video model or resolution. If unavailable, report it instead of silently switching. These settings override other video resolution/ratio defaults; image settings remain unchanged.')
    if config.get('image_agent'):
        from ai_studio_image_models import batch_instructions
        lines[1]='Exactly ONE image per requested identity/scene: x1, number_of_images=1. Never generate alternate variations. Use the attached named reference image pixels whenever their corresponding character or location occurs. Preserve identity and visual style across every batch.'
        lines[2]='Attach only the references assigned to each scene. Never force the entire batch cast into one image.'
        lines[5]='ALL outputs must be still IMAGES using '+preferred(config)+'. Never create video clips, animation, music or audio.\n'+batch_instructions(config)
        lines[6]='Preserve reference identity only where that character or place occurs in the scene. Never force every attached character into every image. Preserve faces, age, hair, clothing, architecture and period details; do not substitute a similar-looking person.'
    if records and all(r['kind']=='image' for r in records):
        lines.append('IMAGE BATCH EXECUTION: this is ONE batch containing '+str(len(records))+' independent scene images, not '+str(len(records))+' separate conversational turns. '
            'Perform ONE preflight reconciliation for the exact identity table, partitioning existing, in-flight and confirmed missing outputs. '
            'Then enqueue ALL confirmed missing scene requests together in the same Agent turn, using batch/parallel image tool calls where supported. '
            'Each request remains x1 with its own exact tracking label and assigned references. Do NOT wait for one image to finish, inspect its quality, download it or ask for approval before enqueueing the next independent scene. '
            'If the platform imposes a concurrency cap, enqueue up to that cap and keep filling available slots; do not bypass limits. '
            'Wait/collect after requests have been queued. Do not repeat the gallery audit between individual submissions, create extra variants, or regenerate existing/in-flight identities. '
            'If the provider requires strictly serial execution, state that limitation explicitly; do not claim all requests are queued when only one has been started. '
            'At completion report each requested OUTPUT/token as existing, generated, processing, failed or not submitted, and state the reason for any incomplete output.')
    lines.append(RETRY_SAFE_BATCH_INSTRUCTIONS)
    if config.get('cinematic_previous_frame'):
        lines.append('CONTINUATION FRAME @'+config['cinematic_previous_frame']+': this is the actual final frame of the previous clip. Start from its pose, camera geography, lighting, clothing and props, then progress the narrated action. Do not hold this image for the entire clip. Character references define identity; this frame defines the starting composition.')
    lines.append('Full video context, for interpreting the visuals only; DO NOT speak it: '+json.dumps(
        {'title':config.get('title',''),'script':config.get('script','')},ensure_ascii=False))
    lines.append(TOPIC_DIRECTION+' '+MEANING_DIRECTION)
    lines.append('Raw video clip audio is not the final soundtrack. Generate silent visuals; local narration replaces all generated audio during final assembly.')
    if is_narration_story(config):lines.append(narration_direction(config))
    for r in records:
        scene_narration=r.get('narration','')
        lines += [f"OUTPUT {r['index']+1:04d} — {r['kind'].upper()} — {r['token']}",
                  'Meaning of this scene (local narration; do not speak): '+scene_narration,r['prompt'],
                  'Generation prompt tracking reference: '+r['token']]
        if r['kind']=='video':
            from ai_studio_multishot import shot_instructions
            lines.append(shot_instructions(r,clip_seconds(config)))
        if 'reference_names' in r:
            lines.append('References for THIS scene only: '+(', '.join(r['reference_names']) or 'NONE; do not introduce recurring characters or places.'))
            lines.append('Do not show other recurring characters or locations from the full story in this scene. Background extras only when required by this scene action.')
    from ai_studio_continuity_ledger import prompt_context
    lines.append(prompt_context(records,config))
    lines.insert(0,'CURRENT REQUEST ONLY: reconcile these OUTPUT numbers, reusing those already generated and generating ONLY confirmed missing identities: '+', '.join(str(r['index']+1).zfill(4) for r in records)+'. Ignore previous batches and earlier scene numbers in this conversation. Copy each exact AS_SCENE tracking label to its corresponding asset. Do not reuse an earlier batch as this response.\nEXACT IDENTITY TABLE (authoritative; verify every existing asset against this table):\n'+'\n'.join(f"OUTPUT {r['index']+1:04d} = {r['token']}" for r in records)+'\nA matching OUTPUT number alone is NOT a match. The saved asset prompt must contain the exact corresponding label AND depict this scene. Never recycle earlier labels or append _1/_2 suffixes, invent labels, or relabel unrelated images. Reference-image IDs and reference filenames are NOT scene tracking labels; never derive AS_SCENE labels from attached character/location asset IDs. If the exact identity does not exist, report it as missing or uncertain; never claim it already exists using a different label.')
    return '\n\n'.join(lines)


def reference_groups(records,size):
    """Honor the requested scene count; prompts map the shared attachments per scene."""
    return [(records[start]['index'],records[start:start+size]) for start in range(0,len(records),size)]


def cast_groups(records,size=6,video_size=1):
    groups=[];batch=[];names=set()
    for record in records:
        used=set(record.get('reference_names',[]))
        if len(used)>40:raise ValueError('A grouped clip exceeds the forty-identity reference library.')
        if batch and (record['kind']!=batch[0]['kind'] or len(batch)>=(video_size if record['kind']=='video' else size)):
            groups.append((batch[0]['index'],batch));batch=[];names=set()
        batch.append(record);names.update(used)
    if batch:groups.append((batch[0]['index'],batch))
    return groups


class AgentMedia(ZBotImageGenerator):
    @staticmethod
    def _scene_grid_position(page,top=None):
        """Use the real Flow scroll container, preserving the scan anchor."""
        return page.evaluate('''top => {
            let e=document.querySelector('.page-container.cdk-virtual-scrollable');
            if(!e){const votes=new Map();for(const tile of document.querySelectorAll('flow-image-tile,flow-video-tile')){
                for(let parent=tile.parentElement;parent&&parent!==document.body;parent=parent.parentElement){
                    if(parent.clientHeight>100&&parent.scrollHeight>parent.clientHeight+2&&/(auto|scroll|overlay)/.test(getComputedStyle(parent).overflowY)){
                        votes.set(parent,(votes.get(parent)||0)+1);break;
                    }
                }
            }e=[...votes].sort((a,b)=>b[1]-a[1])[0]?.[0];}
            if(top!==null){if(e)e.scrollTop=top;else window.scrollTo(0,top);}
            return {top:e?e.scrollTop:window.scrollY,height:e?e.scrollHeight:document.documentElement.scrollHeight,
                client:e?e.clientHeight:innerHeight};
        }''',top)

    @staticmethod
    def _agent_batch_reply(page,records):
        text=page.evaluate("""tokens => {
            const rows=[...document.querySelectorAll('.messages-list > .message-row')];
            let start=-1;
            for(let i=rows.length-1;i>=0;i--){
                if(rows[i].classList.contains('user-row')){
                    if(tokens.some(t=>(rows[i].innerText||'').includes(t))) start=i;
                    break;
                }
            }
            if(start<0)return '';
            return rows.slice(start+1).filter(r=>r.classList.contains('agent-row'))
                .map(r=>r.innerText||'').join('\\n');
        }""",[r['token'] for r in records])
        return text if isinstance(text,str) else ''

    @staticmethod
    def _agent_refusal(page,records):
        # Inspect the latest real Agent error card, not quoted policy text in a
        # user message or an older rejected conversation turn.
        result=page.evaluate('''tokens => {
            const rows=[...document.querySelectorAll('.messages-list > .message-row')];
            const last=rows.at(-1);
            if(!last?.classList.contains('agent-row'))return '';
            const card=last.querySelector('flow-chat-error-card');
            const text=(card?.innerText||'').trim();
            if(!/might violate our policies|cannot generate.*policy|blocked.*policy/i.test(text))return '';
            const user=rows.slice(0,-1).reverse().find(row=>row.classList.contains('user-row'));
            if(!user || !tokens.some(token=>(user.innerText||'').includes(token)))return '';
            return text.replace(/\\s*Send feedback\\s*$/i,'').replace(/^error\\s*/i,'').trim();
        }''',[r['token'] for r in records if r['status']!='complete'])
        return result if isinstance(result,str) else ''

    @staticmethod
    def _reference_filenames(records):
        root=Path(records[0]['output']).parent.parent
        names=set()
        for file,key in ((root/'references/reference_plan.json','references'),(root/'cast_analysis.json','assets')):
            try:
                data=json.loads(file.read_text('utf-8'))
                for row in data.get(key,[]):
                    if row.get('name'):names.add(row['name'])
            except (OSError,ValueError,TypeError):pass
        return {(name+suffix).casefold() for name in names for suffix in ('.png','.jpg','.jpeg','.webp')}

    @staticmethod
    def _reference_asset_ids(records):
        """Reference images cannot satisfy scene requests or block an idle scan."""
        root=Path(records[0]['output']).parent.parent
        ids=set()
        try:
            data=json.loads((root/'references/image_batches.json').read_text('utf-8'))
            ids.update(r['asset_id'] for r in data.get('requests',{}).values() if r.get('asset_id'))
        except (OSError,ValueError,KeyError):pass
        try:
            import hashlib
            verified=json.loads((root/'references/verified_flow_assets.json').read_text('utf-8'))
            project=json.loads((root/'project.json').read_text('utf-8'))
            names=AgentMedia._reference_filenames(records)
            if verified.get('flow_url')==project.get('options',{}).get('flow_url'):
                for row in verified.get('assets',[]):
                    name=row.get('filename','')
                    if name.casefold() not in names:continue
                    file=root/'references'/name
                    if file.is_file() and hashlib.sha256(file.read_bytes()).hexdigest()==row.get('sha256'):
                        ids.add(row['asset_id'])
        except (OSError,ValueError,KeyError,TypeError):pass
        return ids

    def _agent_assets(self,page):
        return page.evaluate('''() => [...document.querySelectorAll('flow-image-tile,flow-video-tile')].map(tile=>{
            const video=tile.tagName.toLowerCase()==='flow-video-tile';
            const el=tile.querySelector('video') || tile.querySelector('img[data-media-id]') || tile.querySelector('img');
            const src=video ? (tile.querySelector('video')?.currentSrc || tile.querySelector('video')?.getAttribute('src') || tile.querySelector('video source')?.getAttribute('src') || '') : (el?.currentSrc || el?.getAttribute('src') || '');
            const text=tile.innerText||'';
            // Playback URLs can contain encoded Google resource handles with
            // '=mm,...' or '=s512' suffixes. They are not stable media IDs.
            // Prefer Flow's own identity; use a DOM marker only for locating
            // anonymous tiles. A scene still requires its exact prompt token.
            const candidates=[tile.getAttribute('data-media-id'),el?.getAttribute('data-media-id'),tile.querySelector('[data-media-id]')?.getAttribute('data-media-id'),(src.match(/\\/(?:video|image|asb)\\/([^/?#]+)/)||[])[1]];
            const stable=candidates.find(value=>value && /^[A-Za-z0-9_-]+$/.test(value));
            const previous=tile.getAttribute('data-ai-studio-media');
            const id=stable || (previous && /^[A-Za-z0-9_-]+$/.test(previous)?previous:'') || ('dom_'+crypto.randomUUID());
            if(id)tile.setAttribute('data-ai-studio-media',id);
            const rect=tile.getBoundingClientRect();
            return {asset_id:id,src,kind:video?'video':'image',visible:rect.width>0&&rect.height>0&&rect.bottom>160&&rect.top<innerHeight-80,busy:/generating|queued|processing|creating/i.test(text) || !!tile.querySelector('[role="progressbar"],mat-progress-spinner'),failed:/generation failed|failed to generate|something went wrong|usage limit|not been charged/i.test(text)};
        }).filter(a=>a.asset_id)''')

    def _asset_prompt(self,page,asset):
        asset_id=asset['asset_id']
        if asset_id in self._flow_asset_prompts:return self._flow_asset_prompts[asset_id]
        if not __import__('re').fullmatch(r'[A-Za-z0-9_-]+',asset_id):return ''
        tile=page.locator(f'[data-ai-studio-media="{asset_id}"]').first
        try:
            page.keyboard.press('Escape')
            tile.scroll_into_view_if_needed(timeout=5000)
            tile.hover(force=True,timeout=5000)
            # Uploads have their own new Flow IDs, different from the original
            # reference-generation IDs. Their exact approved filenames identify
            # references; they have no generation-prompt popup to read.
            footer=tile.locator('.footer-left').first
            # Flow hides hover-footer text while the video is playing. Read
            # exact filename from DOM; hidden visibility is not a missing asset.
            label=footer.evaluate("el => el.getAttribute('aria-label') || el.textContent || ''")
            reference=next((line.strip() for line in label.splitlines()
                            if line.strip().casefold() in getattr(self,'_flow_reference_filenames',set())),None)
            if reference:
                text='FLOW_REFERENCE:'+reference
                self._flow_asset_prompts[asset_id]=text
                return text
            # Ensure the preceding popup is gone, then open THIS exact footer.
            try:page.locator('.cdk-overlay-popover .prompt-text:visible').last.wait_for(state='hidden',timeout=1500)
            except Exception:
                page.keyboard.press('Escape')
                page.locator('.cdk-overlay-popover .prompt-text:visible').last.wait_for(state='hidden',timeout=2500)
            footer.click(force=True,timeout=4000)
            content=page.locator('.cdk-overlay-popover .prompt-text:visible').last
            content.wait_for(state='visible',timeout=5000)
            text=content.inner_text()
            if text.strip():self._flow_asset_prompts[asset_id]=text
            page.keyboard.press('Escape')
            return text
        except Exception:
            page.keyboard.press('Escape')
            return ''

    def _download_video(self,page,src,path,asset_id=None):
        from ai_studio_upscaled_download import download
        if not asset_id:raise RuntimeError('Upscaled download requires the exact matched video tile identity.')
        return download(page,asset_id,path,self.cancel,self._log)

    def _load_video_source(self,page,asset):
        """Mount existing playback; never click a generation retry."""
        tile=page.locator(f'[data-ai-studio-media="{asset["asset_id"]}"]').first
        try:
            tile.hover(timeout=2500)
            return tile.evaluate('''tile => {
                const v=tile.querySelector('video');
                if(!v)return '';
                if(!v.currentSrc)v.load();
                return v.currentSrc || v.getAttribute('src') || v.querySelector('source')?.getAttribute('src') || '';
            }''')
        except Exception:return ''

    def collect(self,records,save,on_media,timeout=1200):
        self.completed_reported_quotas=()
        reference_ids=set() if getattr(self,'reference_collection',False) else self._reference_asset_ids(records)
        completed_ids=getattr(self,'completed_scene_asset_ids',set())
        self._flow_reference_filenames=set() if getattr(self,'reference_collection',False) else self._reference_filenames(records)
        with self._session(headless=False) as ctx:
            page=self._batch_page(ctx);page.set_default_timeout(4000)
            indexed=[]
            fresh_submission=getattr(self,'fresh_submission',False)
            self.fresh_submission=False
            if fresh_submission:
                self._log('New batch just submitted; watching its outputs directly without reloading the old media index.')
            if not fresh_submission and any(r['kind']=='image' and r['status']!='complete' for r in records):
                from ai_studio_flow_inventory import read_project_images
                indexed=read_project_images(page,self.cancel,self._log)
                for asset in indexed:self._flow_asset_prompts[asset['asset_id']]=asset['prompt']
            indexed_tokens={token for asset in indexed for token in scene_tracking_tokens(asset['prompt'])}
            self._scene_grid_position(page,0)
            started=time.monotonic();deadline=started+timeout;last_log=0;observed={};unread_attempts={}
            stable_since=started;last_signature=None;sweeps=0;download_passes=0;idle_grid_passes=0;settled=False;ambiguous_idle=False;download_notice_logged=False
            while any(r['status']!='complete' for r in records):
                check_cancel(self.cancel)
                anchor=self._scene_grid_position(page)
                pending_records=[r for r in records if r['status']!='complete']
                index_covers_pending=bool(indexed) and all(r['kind']=='image' and r['token'] in indexed_tokens for r in pending_records)
                # Download verified index hits immediately; opening reference
                # popups first adds delay without contributing scene matches.
                grid=[] if index_covers_pending else self._agent_assets(page)
                assets=[a for a in {a['asset_id']:a for a in [*grid,*indexed]}.values() if a['asset_id'] not in completed_ids]
                for a in assets:
                    observed.setdefault(a['asset_id'],{}).update({k:a.get(k) for k in ('asset_id','kind','busy','failed')})
                signature=tuple(sorted((a['asset_id'],a['busy'],a['failed']) for a in observed.values()))
                if signature!=last_signature:
                    stable_since=time.monotonic();last_signature=signature;sweeps=0
                hits={};alternatives={}
                for a in assets:
                    check_cancel(self.cancel)
                    if a['busy'] or a['failed'] or a['asset_id'] in reference_ids:continue
                    pending=[r for r in records if r['status']!='complete' and r['kind']==a['kind']]
                    if not pending:continue
                    exact=[r for r in pending if r.get('asset_id')==a['asset_id']]
                    if not exact:
                        if a.get('visible') is False and a['asset_id'] not in self._flow_asset_prompts:continue
                        if unread_attempts.get(a['asset_id'],0)>=2:continue
                        text=self._asset_prompt(page,a)
                        if anchor:self._scene_grid_position(page,anchor['top'])
                        if not text.strip():unread_attempts[a['asset_id']]=unread_attempts.get(a['asset_id'],0)+1
                        if text.startswith('FLOW_REFERENCE:') and text.removeprefix('FLOW_REFERENCE:').casefold() in self._flow_reference_filenames:
                            reference_ids.add(a['asset_id']);observed[a['asset_id']]['reference']=True
                            continue
                        observed[a['asset_id']]['tracking_tokens']=sorted(scene_tracking_tokens(text))
                        if len(set(observed[a['asset_id']]['tracking_tokens']))!=1:
                            continue # a copied whole-batch prompt cannot identify one scene
                        exact=[r for r in pending if r['token'] in scene_tracking_tokens(text)]
                    if len(exact)!=1:continue
                    r=exact[0]
                    if r['token'] in hits and hits[r['token']]['asset_id']!=a['asset_id']:
                        previous=hits[r['token']]
                        ids=alternatives.setdefault(r['token'],set())
                        ids.update((previous['asset_id'],a['asset_id']))
                        # Both outputs have the exact SAME scene identity. Keep
                        # an existing selection; otherwise use stable asset ID
                        # order, never the grid's scene/display order.
                        hits[r['token']]=min((previous,a),key=lambda item:(
                            item['asset_id']!=r.get('asset_id'),not bool(item.get('src')),item['asset_id']))
                        continue
                    hits[r['token']]=a
                for r in records:
                    a=hits.get(r['token'])
                    if not a:continue
                    if r['token'] in alternatives:
                        r['alternate_asset_ids']=sorted((set(r.get('alternate_asset_ids',[]))|alternatives[r['token']])-{a['asset_id']})
                        r['asset_selection']='saved identity, otherwise stable asset ID order'
                        self._log(f"Scene {r['index']+1}: multiple outputs share its exact tracking label. Saving one {r['kind']}; alternate asset identities retained in the checkpoint.")
                    r['asset_id']=a['asset_id'];r['status']='matched';save()
                    if not a['src'] and r['kind']!='video':continue # video downloads use the exact tile menu, not playback URLs
                    if r['kind']=='video':
                        receipt=self._download_video(page,a['src'],r['output'],asset_id=a['asset_id'])
                        if isinstance(receipt,dict):r.update(receipt)
                    elif not self._download_image(page,a['src'],r['output']):raise RuntimeError('Matched image download failed; saved identity retained.')
                    r['status']='complete';save();on_media(r)
                    deadline=time.monotonic()+timeout # real progress extends the idle budget
                if all(r['status']=='complete' for r in records):
                    if getattr(self,'agent_image_fallback',False) and not getattr(self,'available_only',False):
                        self.completed_reported_quotas=quota_models(self._agent_batch_reply(page,records))
                    break
                if getattr(self,'available_only',False) and ((download_passes if anchor else sweeps)>=2 or (not assets and time.monotonic()-started>=6)):
                    conflicts=agent_label_conflicts(self._agent_batch_reply(page,records),records)
                    self.collection_label_conflicts=conflicts
                    if conflicts:self._log('Flow Agent reported different tracking labels for requested scenes: '+', '.join(map(str,conflicts))+'. These are not verified matches; unrelated outputs were not renamed or counted as downloaded.','warning')
                    report=Path(records[0]['output']).parent.parent/'scene_download_diagnostics.json'
                    atomic_json(report,{'missing_scenes':[r['index']+1 for r in records if r['status']!='complete'],
                        'observed_assets':list(observed.values()),'completed_passes':download_passes if anchor else sweeps,'agent_label_conflicts':conflicts})
                    self._log('Available scene image scan complete. Unmatched scenes remain pending; this does not prove they were never generated. Diagnostics: '+str(report))
                    break
                if settled or ambiguous_idle or time.monotonic()>=deadline or time.monotonic()-started>=3600:
                    missing=', '.join(str(r['index']+1) for r in records if r['status']!='complete')
                    report=Path(records[0]['output']).parent.parent/'agent_collection_diagnostics.json'
                    atomic_json(report,{'missing_scenes':[r['index']+1 for r in records if r['status']!='complete'],
                        'records':[{k:r.get(k) for k in ('index','token','status','asset_id')} for r in records],
                        'observed_assets':list(observed.values()),'agent_label_conflicts':agent_label_conflicts(self._agent_batch_reply(page,records),records)})
                    unlabelled=sum(a['asset_id'] not in reference_ids and not a.get('tracking_tokens') and not a.get('busy') and not a.get('failed') for a in observed.values())
                    retry_unmatched=(ambiguous_idle and getattr(self,'retry_unmatched_images',False)
                        and all(r['kind']=='image' for r in records))
                    error=MissingAgentOutputs if settled or retry_unmatched else RuntimeError
                    hint=' Flow is idle and the grid scan found no matching outputs. Use Generate Missing to request these scenes only.' if settled else ' Retry collects existing outputs only; no batch resubmitted.'
                    raise error(f'Agent batch paused. Unresolved scenes: {missing}; {len(observed)} assets observed, {unlabelled} media assets without readable tracking labels. Saved outputs retained.'+hint+f' Diagnostics: {report}')
                refusal='' if getattr(self,'available_only',False) else self._agent_refusal(page,records)
                if not getattr(self,'available_only',False):
                    conflicts=agent_label_conflicts(self._agent_batch_reply(page,records),records)
                    if conflicts and not any(a.get('busy') for a in assets):
                        # A foreign label is not missing-media evidence. Do not
                        # spend more quota automatically recreating the batch.
                        raise RuntimeError(label_conflict_message(conflicts))
                if refusal:
                    missing=', '.join(str(r['index']+1) for r in records if r['status']!='complete')
                    for r in records:
                        if r['status']!='complete':r.update(pause_reason='provider_refusal',last_error=refusal)
                    save()
                    raise RuntimeError(f'Flow rejected scene(s) {missing}: {refusal} No matching image was generated. Completed images are retained. Review the scene content or supply a replacement image; this refusal will not trigger model fallback or automatic resubmission.')
                error=self._queued_error(page)
                if getattr(self,'available_only',False) and error.startswith(('Account limit reached:','Flow unusual-activity check:')):
                    # Generation notices can persist beside accessible existing
                    # assets. This collector never submits anything. Actual page,
                    # authentication and download failures still propagate.
                    if not download_notice_logged:
                        self._log('Flow shows a generation warning. Download-only scan continues for accessible existing scene images; no generation, model switch or account switch will be attempted.')
                        download_notice_logged=True
                    error=''
                model_quota=None;reported_quotas=()
                if getattr(self,'agent_image_fallback',False) and not getattr(self,'available_only',False):
                    # Batch instructions and old user messages can mention the
                    # quota policy. Only the Agent response is quota evidence.
                    response_text=self._agent_batch_reply(page,records)
                    reported_quotas=quota_models(response_text)
                    model_quota=reported_quotas[-1] if reported_quotas else None
                    if error.startswith('Account limit reached:'):
                        if model_quota or not response_text:
                            if not model_quota and not download_notice_logged:
                                self._log('Ignoring an unscoped quota notice from the page history; collecting this batch and checking its own Agent replies for model fallback.')
                                download_notice_logged=True
                            error=''
                        else:
                            # Only current-batch quota/credit evidence may stop it.
                            import re
                            if not re.search(r"quota exceeded|limit reached|daily (?:quota|limit)|usage limit|not enough credits|insufficient credits|too many requests",response_text,re.I):
                                error=''
                            else:
                                error='Current Flow batch reports a quota/credit limit without a confirmed model: '+response_text[-700:]+'. Saved outputs retained; model exhaustion was not assumed.'
                if error:raise RuntimeError(error)
                if time.monotonic()-last_log>=15:
                    self._log(f"Agent batch: {sum(r['status']=='complete' for r in records)}/{len(records)} saved; {len(assets)} visible assets ({sum(bool(a['busy']) for a in assets)} generating, {sum(bool(a['failed']) for a in assets)} failed). Collecting remaining scene IDs…")
                    last_log=time.monotonic()
                # Newest batch may span more than one viewport; walk the grid a
                # page at a time, then return to top when the bottom is reached.
                point=page.evaluate('''() => {
                    const tiles=[...document.querySelectorAll('flow-image-tile,flow-video-tile')];
                    const votes=new Map();
                    for(const tile of tiles)for(let e=tile.parentElement;e && e!==document.body;e=e.parentElement){
                        if(e.clientHeight>80 && e.scrollHeight>e.clientHeight+2 && /(auto|scroll|overlay)/.test(getComputedStyle(e).overflowY)){
                            votes.set(e,(votes.get(e)||0)+1);break;
                        }
                    }
                    const e=[...votes].sort((a,b)=>b[1]-a[1])[0]?.[0];
                    const tile=tiles.find(t=>{const r=t.getBoundingClientRect();return r.bottom>160 && r.top<innerHeight-80;});
                    const r=tile?.getBoundingClientRect() || e?.getBoundingClientRect();
                    const top=e?e.scrollTop:window.scrollY, height=e?e.scrollHeight:document.documentElement.scrollHeight, client=e?e.clientHeight:innerHeight;
                    if(!r)return null;
                    const busy=[...document.querySelectorAll('button')].some(b=>!b.disabled && /^stop(?: generation| generating)?$/i.test(b.getAttribute('aria-label')||b.innerText||''));
                    const failed=[...document.querySelectorAll('flow-image-tile,flow-video-tile')].some(t=>/generation failed|failed to generate|usage limit|not been charged/i.test(t.innerText||''));
                    const unidentified=[...document.querySelectorAll('flow-video-tile,flow-image-tile')].some(t=>!t.hasAttribute('data-ai-studio-media'));
                    return {x:Math.max(10,Math.min(innerWidth-10,r.x+r.width/2)),y:Math.max(180,Math.min(innerHeight-100,r.y+r.height/2)),delta:top+client>=height-5?-height:client*.7,at_end:top+client>=height-5,agent_busy:busy,failed,unidentified};
                }''')
                if point:
                    if point.get('at_end'):
                        sweeps+=1;idle_grid_passes+=1
                    settled=(sweeps>=2 and time.monotonic()-stable_since>=90
                        and not point.get('agent_busy') and not point.get('failed') and not point.get('unidentified')
                        and all(not a.get('busy') and not a.get('failed')
                            and (a['asset_id'] in reference_ids
                                 or (a['kind']=='image' and all(r['kind']=='video' for r in records))
                                 or a.get('tracking_tokens') or any(r.get('asset_id')==a['asset_id'] for r in records))
                            for a in observed.values())
                        and not any(r['status']=='matched' for r in records))
                    ambiguous_idle=(sweeps>=2 and time.monotonic()-stable_since>=90
                        and not point.get('agent_busy') and not point.get('failed')
                        and not any(a.get('busy') or a.get('failed') for a in observed.values())
                        and not any(r['status']=='matched' for r in records) and not settled)
                    if (model_quota and getattr(self,'agent_image_model',None) in reported_quotas and sweeps>=2
                        and time.monotonic()-stable_since>=90 and not point.get('agent_busy')
                        and not point.get('unidentified') and not any(a.get('busy') for a in observed.values())
                        and not any(r['status']=='matched' for r in records)
                        and all(a.get('failed') or a['asset_id'] in reference_ids or a.get('tracking_tokens')
                                or any(r.get('asset_id')==a['asset_id'] for r in records) for a in observed.values())):
                        raise ModelQuotaExhausted(model_quota,reported_quotas)
                    completed_passes=download_passes if anchor else idle_grid_passes
                    if (completed_passes>=2 and time.monotonic()-started>=90
                        and not point.get('agent_busy') and not any(a.get('busy') for a in assets)
                        and not any(r['status']=='matched' for r in records)):
                        # Virtualized tiles may remount with new DOM IDs forever.
                        # They cannot extend a completed idle scan indefinitely.
                        reply=self._agent_batch_reply(page,records)
                        if not any(r['status']=='complete' for r in records) and wrong_batch_reply(reply,records):
                            raise MissingAgentOutputs('Flow Agent answered with earlier OUTPUT numbers instead of the current batch. Existing media retained; only the unresolved current scenes may be retried.')
                        if not point.get('failed') and not settled:
                            ambiguous_idle=True
                    if anchor:
                        # Opening prompt popovers can scroll the grid. Advance
                        # from the PRE-READ position, not the shifted viewport.
                        # Half-screen overlap catches virtualized boundary rows.
                        position=self._scene_grid_position(page,anchor['top'])
                        at_end=position['top']+position['client']>=position['height']-5
                        if bool(point.get('at_end'))!=at_end:
                            sweeps=max(0,sweeps-(1 if point.get('at_end') else 0))+(1 if at_end else 0)
                        if at_end:
                            download_passes+=1
                            self._log(f'Completed scene grid pass {download_passes}; {len(observed)} asset identities inspected.')
                        self._scene_grid_position(page,0 if at_end else position['top']+position['client']*.5)
                    else:
                        page.mouse.move(point['x'],point['y'])
                        page.mouse.wheel(0,point['delta'])
                time.sleep(2)


def prepare_batch_prompt(config,prompt_file,cancel,log):
    """Upload a newly extracted continuation frame before reuse-only attachment."""
    references=config.get('references',[])
    previous=config.get('cinematic_previous_frame')
    if previous:
        frames=[p for p in references if Path(p).stem==previous]
        if len(frames)!=1 or not valid_image(frames[0]):
            raise RuntimeError('Continuation frame is missing or invalid. No generation submitted.')
        log(f'Preparing continuity frame {Path(frames[0]).name} in Flow; existing cast references remain reused.')
        prepare_agent_prompt({**config,'_upload_references_only':True},prompt_file,frames,cancel,log)
    prepare_agent_prompt({**config,'_upload_references_only':False},prompt_file,references,cancel,log)


def prepare_agent_prompt(config,prompt_file,references,cancel,log):
    for attempt in range(2):
        check_cancel(cancel)
        try:return _prepare_agent_prompt_once(config,prompt_file,references,cancel,log)
        except RuntimeError:
            if attempt:raise
            log('Agent preparation stopped before submission. Rebuilding the prompt and exact reference attachments once; no generation has been sent.')


def _prepare_agent_prompt_once(config,prompt_file,references,cancel,log):
    """Reuse the existing Agent driver's model/reference picker; never submit here."""
    tool=Path(config['agent_tool_dir']);driver=tool/'agent_mode.js'
    if not driver.is_file():raise RuntimeError('Choose the Veo3_New Agent tool folder in Animate settings.')
    node=shutil.which('node') or str(Path(__file__).parent/'.venv/Lib/site-packages/playwright/driver/node.exe')
    from desktop.browser_accounts import browser_options
    port=config.get('_agent_cdp_port') or browser_options({**config,'provider':'flow','share_google_profile':config.get('share_google_profile',True)}).get('cdp_port',9232 if config.get('share_google_profile',True) else 9234)
    args=[node,str(driver),'--cdp',str(port),'--project-url',config['flow_url'],'--file',str(prompt_file),
          '--no-submit','--paste','--aspect',config['aspect']]
    if config.get('_upload_references_only'):args+=['--upload-references-only']
    else:args+=['--no-upload-refs'] # library upload is a separate verified step; batches only attach
    if config.get('image_agent'):args+=['--image-only','--image-model',preferred(config)]
    else:
        from ai_studio_animate_options import video_settings
        quality,ratio=video_settings(config)
        log(f'Video request settings: {config["animate_model"]}; {quality} (Agent instruction); ratio {ratio}.')
        args[args.index('--aspect')+1]=ratio
        args+=['--scene-seconds',str(clip_seconds(config)),'--video-model',config['animate_model'],'--video-resolution',quality]
    if references:
        if config.get('image_agent') or config.get('character_consistency') or config.get('animate_narration_mode')=='cinematic':args+=['--reference-files-json',json.dumps(references)]
        else:args+=['--refs',','.join(references)]
        args+=['--mention',','.join(Path(p).stem for p in references)]
    process=subprocess.Popen(args,cwd=tool,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    events=queue.Queue()
    def read():
        for line in process.stdout:events.put(line.rstrip())
    thread=threading.Thread(target=read,daemon=True);thread.start();deadline=time.monotonic()+(max(180,90*len(references)) if config.get('_upload_references_only') else 180)
    try:
        while process.poll() is None or not events.empty():
            check_cancel(cancel)
            if time.monotonic()>deadline:raise RuntimeError('Agent settings/reference preparation timed out before submission.')
            try:log(events.get(timeout=.2))
            except queue.Empty:pass
        if process.returncode:raise RuntimeError('Agent preparation failed before submission. Check the reported model/reference controls.')
    finally:
        if process.poll() is None:
            # taskkill /T is scoped to the child driver we launched, never Chrome.
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            else:process.terminate()
        process.wait(timeout=10)
        process.stdout.close()


def generate_agent_media(scenes,config,cancel,log,on_media,reference_records=None):
    plan=reference_records if reference_records is not None else media_plan(scenes,config)
    file=Path(config['project'])/config.get('_manifest_name',('studio_agent_images.json' if config.get('image_agent') else 'animate_media.json'))
    identity=fingerprint([(r['key'],r['index']) for r in plan],config['flow_url'])
    if file.is_file():
        state=json.loads(file.read_text(encoding='utf-8'))
        from ai_studio_animate_cast import adopt_existing_media
        plan,state=adopt_existing_media(plan,state,scenes,config)
        identity=fingerprint([(r['key'],r['index']) for r in plan],config['flow_url'])
        if config.get('image_agent') and state.get('identity')!=identity:
            old=state.get('records',[])
            same_story=(len(old)==len(plan) and state.get('identity')==fingerprint([(r['key'],r['index']) for r in old],config['flow_url'])
                and all(a.get('index')==b['index'] and a.get('kind')==b['kind']=='image'
                    and a.get('prompt')==b['prompt'] and a.get('reference_names')==b.get('reference_names') for a,b in zip(old,plan)))
            style_variant=False
            if config.get('_dsp_previous_style') and len(old)==len(plan):
                original=media_plan(scenes,{**config,'style':config['_dsp_previous_style']})
                style_variant=(state.get('identity')==fingerprint([(r['key'],r['index']) for r in old],config['flow_url'])
                    and all(a.get('index')==b['index'] and a.get('kind')==b['kind']=='image'
                        and a.get('prompt')==b['prompt'] and a.get('reference_names')==b.get('reference_names')
                        for a,b in zip(old,original)))
            if same_story or style_variant:
                # A reference correction does not invalidate already produced media.
                # Preserve every issued tracking identity so manual/submitted outputs
                # can still be recovered before any further generation.
                atomic_json(file.parent/'animate_plan_history'/f'{state["identity"]}.json',state)
                reconciled=[];changed_count=0
                for previous,current in zip(old,plan):
                    row=dict(previous,output=current['output'])
                    if style_variant and previous.get('status')=='pending':
                        row['prompt']=current['prompt'] # keep issued token for retry matching
                    if previous['key']!=current['key']:
                        changed_count+=1
                        row.setdefault('source_generation_key',previous['key'])
                        row['key']=current['key']
                        row['reference_revision_adopted']=True
                    reconciled.append(row)
                state={**state,'identity':identity,'records':reconciled}
                atomic_json(file,state)
                log(f'Reference correction adopted for {changed_count} scene plans. Completed images kept; issued tracking labels and submitted requests retained. Future requests use current reference files. Previous checkpoint archived.')
        if state.get('identity')!=identity and config.get('cinematic_media_kind')=='image':
            # Image-only continuation may follow a video-model selection change.
            # Prove the complete previous plan, including Flow binding, before
            # retaining old video identities; never loosen image/ref validation.
            from ai_studio_animate_options import VIDEO_MODELS
            old=state.get('records',[])
            for model in VIDEO_MODELS:
                original=media_plan(scenes,{**config,'animate_model':model})
                if (len(old)==len(plan) and [r.get('key') for r in old]==[r['key'] for r in original]
                    and state.get('identity')==fingerprint([(r['key'],r['index']) for r in original],config['flow_url'])
                    and all(a['kind']==b['kind'] and (b['kind']=='video' or a['key']==b['key']) for a,b in zip(old,plan))):
                    plan=[{**b,'key':a['key'],'token':a['token']} if b['kind']=='video' else b for a,b in zip(old,plan)]
                    identity=fingerprint([(r['key'],r['index']) for r in plan],config['flow_url'])
                    log('Image-only continuation: previous video-model identities preserved; unchanged image plan verified. No clips regenerated.')
                    break
        from ai_studio_story import can_replan_pending
        if state.get('identity')!=identity and can_replan_pending(config,scenes):
            atomic_json(file.parent/'animate_plan_history'/f'{state["identity"]}.json',state)
            state={'version':1,'identity':identity,'records':[dict(r,status='pending') for r in plan]}
            log('Unsent scene plan updated. Previous pending checkpoint archived; existing reference files preserved.')
        if state.get('identity')!=identity:
            # Only a mode/count change is compatible. Recompute alternate plans
            # with the SAME script, model, references and Flow URL to prove it.
            candidates = [dict(config, animation_mode='full')] + [dict(config, animation_mode='partial', animate_count=n) for n in range(4)]
            old = state.get('records', [])
            compatible = False
            for candidate in candidates:
                previous = media_plan(scenes, candidate)
                if (state.get('identity') == fingerprint([(r['key'],r['index']) for r in previous], config['flow_url'])
                    and [r.get('key') for r in old] == [r['key'] for r in previous]):
                    compatible = True
                    break
            if not compatible or len(old)!=len(plan):
                raise RuntimeError('Animate scene plan, model, references or Flow project changed. Use a new Animate project folder before generating; existing checkpoints are preserved.')
            changed = [(a,b) for a,b in zip(old,plan) if a.get('key')!=b['key']]
            if any(a.get('status') in ('submitting','submitted','matched') for a,b in changed):
                raise RuntimeError('Finish or recover the submitted Agent batch in its previous animation mode before switching modes. No new generation was submitted.')
            for a,b in changed:
                scene=scenes[b['index']]
                if b['kind']=='video' and valid_video(b['output']) and scene.get('video_key')!=b['key']:
                    raise RuntimeError('An existing clip has a different generation identity. Use a new Animate project folder; the old clip is preserved.')
            atomic_json(file.parent/'animate_plan_history'/f'{state["identity"]}.json',state)
            state={'version':1,'identity':identity,'records':[dict(a,output=b['output']) if a.get('key')==b['key'] else dict(b,status='pending') for a,b in zip(old,plan)]}
            log('Animation mode updated. Matching clips retained; changed scene outputs will be generated through Agent mode.')
        records=state['records']
        if len(records)!=len(plan) or [r.get('key') for r in records]!=[r['key'] for r in plan]:raise RuntimeError('Animate media manifest is inconsistent. Restore it before continuing.')
        for old,new in zip(records,plan):old['output']=new['output']
    else:state={'version':1,'identity':identity,'records':[dict(r,status='pending') for r in plan]};records=state['records']
    for record in records:
        record['narration']=scenes[record['index']]['narration']
        if 'continuity_source_key' in plan[record['index']]:record['continuity_source_key']=plan[record['index']]['continuity_source_key']
    def save():
        update_batch_progress(state)
        atomic_json(file,state)
    if config.get('_export_batches'):
        from ai_studio_manual_batches import export_files
        save()
        export_files(state,config,log)
        return records
    from desktop.browser_accounts import browser_options
    generator=AgentMedia('flow',mode='cdp',flow_project_url=config['flow_url'],share_google_profile=config.get('share_google_profile',True),cancel=cancel,log=lambda m,level='info':log(m),**browser_options({**config,'provider':'flow'}))
    # Recover/Download Generated Batch is strictly a download action. Old quota
    # notices must not abort collection of assets that already exist.
    generator.reference_collection=reference_records is not None
    generator.available_only=bool(config.get('_recover_only'))
    # An explicit Generate Images action authorizes one bounded request for
    # unmatched images after the idle scan, even if unrelated tiles lack labels.
    generator.retry_unmatched_images=(config.get('action')=='images' and not generator.available_only)
    # These asset IDs were positively matched and persisted previously. Reuse
    # their labels instead of reopening every old scene's prompt on each retry.
    for record in records:
        if record.get('asset_id') and record.get('token'):
            generator._flow_asset_prompts[record['asset_id']]=record['token']
    has_images=any(r['kind']=='image' for r in records)
    if has_images:
        requested=preferred(config)
        if state.get('preferred_image_model')!=requested:
            state.update(preferred_image_model=requested,active_image_model=requested)
        exhausted=state.setdefault('exhausted_image_models',[])
        if state.get('active_image_model',requested) in exhausted:
            state['active_image_model']=next((m for m in IMAGE_MODELS if m not in exhausted),requested)
        generator.agent_image_model=state.get('active_image_model',requested)
        generator.agent_image_fallback=True # reconcile quota failures even when automatic switching is disabled
    recovered=set(config.get('_recovered_batches',[]))
    # A manually submitted prompt may never have reached our submit click, so
    # local status alone cannot prove it was unsent. Older versions saved the
    # prompt file before preparation; retain that evidence on migration too.
    prepared_text='\n'.join(p.read_text('utf-8') for p in Path(config['project']).glob('reference_agent_batch_*.txt' if reference_records is not None else 'agent_batch_*.txt'))
    export_file=Path(config['project'])/'manual_batch_export.json'
    if export_file.exists():
        exported_plan=json.loads(export_file.read_text('utf-8'))
        if exported_plan.get('identity')==identity and exported_plan.get('flow_url')==config['flow_url']:
            prepared_text+='\n'+'\n'.join(exported_plan.get('tokens',[]))
    def possibly_sent(record):
        if record.get('handover_unsubmitted') and record['status']=='pending' and not record.get('preparation_started'):return False
        return bool(record.get('preparation_started') or record['status']!='pending' or record['token'] in prepared_text)
    def collect_or_recover(target,start,verify_existing=False):
        previous_download_only=generator.available_only
        try:
            if verify_existing:generator.available_only=True
            generator.collect(target,save,on_media)
            reports=getattr(generator,'completed_reported_quotas',())
            if has_images and config.get('agent_image_fallback',True) and isinstance(reports,(tuple,list)) and reports:
                exhausted=state.setdefault('exhausted_image_models',[])
                for model in reports:
                    if model in IMAGE_MODELS and model not in exhausted:exhausted.append(model)
                order=IMAGE_MODELS[IMAGE_MODELS.index(state['preferred_image_model']):]
                next_model=next((m for m in order if m not in exhausted),None)
                if next_model:
                    state['active_image_model']=next_model;generator.agent_image_model=next_model
                    log('Model memory saved: skip '+', '.join(exhausted)+'; next batches start with '+next_model+'.')
                save()
            if verify_existing and any(r['status']!='complete' for r in target):
                raise MissingAgentOutputs('Existing-output verification finished; unresolved scene outputs were not matched.')
        except ModelQuotaExhausted as error:
            if not any(r['kind']=='image' for r in target) or not config.get('agent_image_fallback',True):raise
            exhausted=state.setdefault('exhausted_image_models',[])
            for model in error.reported_models:
                if model not in exhausted:exhausted.append(model)
            order=IMAGE_MODELS[IMAGE_MODELS.index(state['preferred_image_model']):]
            next_model=next((model for model in order if model not in exhausted),None)
            save()
            if not next_model:
                state['quota_verified_missing']=[r['index'] for r in target if r['status']!='complete']
                save()
                raise ImageModelsExhausted('All configured Nano Banana models reached quota. Progress saved; account fallback may continue only the verified missing requests.') from error
            state['active_image_model']=next_model
            for record in target:
                if record['status']!='complete':
                    record['status']='pending';record.pop('asset_id',None)
            recovered.add(start);save()
            log(f'Model fallback: {error.model} → {next_model}. Same account, project and references; only unresolved scenes will be submitted.')
            return True
        except MissingAgentOutputs as error:
            # A gallery miss is not proof of non-generation. Ordinary Retry
            # must retain the uncertain submission, never spend another request.
            if start in recovered:raise
            missing=[r for r in target if r['status']!='complete']
            if not explicit_missing_recovery(config):
                confirmed=audit_missing_outputs(generator,missing,batch_config,cancel,log)
                if len(confirmed)!=len(missing):
                    raise RuntimeError('Flow audit did not confirm every unresolved identity as absent and ready. Existing/processing/blocked/uncertain outputs retained; no duplicate batch submitted. Download existing outputs or review agent_missing_audit.json.') from error
                log('Flow confirmed these exact scene identities are missing: '+', '.join(str(r['index']+1) for r in confirmed)+'. Only these scenes will be requested; saved images skipped.')
            log(str(error))
            recovered.add(start)
            for r in missing:r['status']='pending'
            save()
            log('Scene outputs not matched after the completed scan: '+', '.join(str(r['index']+1) for r in missing)+
                '. Resuming these scenes only; completed clips retained. One recovery attempt for this batch.')
            return True
        finally:
            generator.available_only=previous_download_only
        return False
    reused=0
    for r in records:
        validator=valid_video if r['kind']=='video' else valid_image
        if validator(r['output']):
            r['status']='complete';reused+=1
            r['_reused']=True
            try:on_media(r)
            finally:r.pop('_reused',None)
        elif r['status']=='complete':r['status']='submitted'
    if reused:log(f'Reused {reused} verified local scene outputs; no new download or generation for those scenes.')
    save()
    generator.completed_scene_asset_ids={asset_id for r in records if r['status']=='complete'
        for asset_id in [r.get('asset_id'),*r.get('alternate_asset_ids',[])] if asset_id}
    # Exclude completed IDs before every subsequent batch, not just on restart.
    original_on_media=on_media
    def on_media(record):
        if record.get('asset_id'):generator.completed_scene_asset_ids.add(record['asset_id'])
        generator.completed_scene_asset_ids.update(record.get('alternate_asset_ids',[]))
        original_on_media(record)
    if generator.completed_scene_asset_ids:
        marks=state.get('scene_progress',{})
        log('Download checkpoint: '+', '.join(f"{kind} scenes downloaded through {value['downloaded_through']}" for kind,value in marks.items() if value['downloaded_through'])+'. Completed scene assets and their saved variants will not have their prompts reopened.')
    from ai_studio_cinematic import enabled as cinematic_enabled
    video_size=max(1,int(config.get('animate_video_batch_size',5)))
    size=max(1,int(config.get("image_batch_size",6)))
    from ai_studio_parts import scene_range
    first,last=scene_range(config,len(records))
    groups=reference_groups([r for r in records if first<=r['index']<last],size)
    if cinematic_enabled(config):
        selected=[r for r in records if first<=r['index']<last]
        if config.get('cinematic_media_kind') in ('video','image'):selected=[r for r in selected if r['kind']==config['cinematic_media_kind']]
        groups=reference_groups([r for r in selected if r['kind']=='video'],video_size)+reference_groups([r for r in selected if r['kind']=='image'],size)
    if config.get('character_consistency'):
        groups=cast_groups(selected if cinematic_enabled(config) else [r for r in records if first<=r['index']<last],size=size,video_size=video_size)
    if not cinematic_enabled(config) and not config.get('character_consistency') and not config.get('image_agent'):
        groups=reference_groups([r for r in records if first<=r['index']<last and r['kind']=='video'],video_size)+reference_groups([r for r in records if first<=r['index']<last and r['kind']=='image'],size)
    if not groups and config.get('cinematic_media_kind') in ('video','image'):
        kind=config['cinematic_media_kind']
        available=[r['index']+1 for r in records if r['kind']==kind]
        bounds=f'{min(available)}-{max(available)}' if available else 'none in this plan'
        raise ValueError(f'No {kind} scenes in selected range {first+1}-{last}. Available {kind} scene numbers: {bounds}. Change Part start/end scene fields before generating. No media was submitted.')
    if config.get('_recover_only') and '_exported_groups' in config:
        by_token={r['token']:r for r in records}
        groups=[]
        for tokens in config['_exported_groups']:
            if any(token not in by_token for token in tokens):
                raise ValueError('Exported batch no longer matches this scene plan. Export again; saved images retained.')
            group=[by_token[token] for token in tokens]
            if group:groups.append((group[0]['index'],group))
    log(f'Agent batch sizes: images {size}; video clips {video_size}. Per-scene reference assignments are preserved.')
    progress=state.setdefault('batch_progress',{})
    for _,group in groups:
        batch_id=fingerprint([r['token'] for r in group])
        progress[batch_id]={'tokens':[r['token'] for r in group],
            'first_scene':group[0]['index']+1,'last_scene':group[-1]['index']+1}
    save() # migrate existing validated outputs without browser inspection
    for batch_number,(start,group) in enumerate(groups,1):
        check_cancel(cancel)
        missing=[r for r in group if r['status']!='complete']
        batch_marks=state['batch_progress'][fingerprint([r['token'] for r in group])]
        if batch_marks['generated_successfully'] and batch_marks['downloaded_successfully']:
            log(f'Batch {batch_number}: Generated ✓ / Downloaded ✓; skipping browser scan.')
            continue
        image_batch=all(r['kind']=='image' for r in group)
        generator.agent_image_fallback=image_batch
        if image_batch and config.get('agent_image_fallback',True):
            order=IMAGE_MODELS[IMAGE_MODELS.index(state['preferred_image_model']):]
            if all(m in state.get('exhausted_image_models',[]) for m in order):
                state['quota_verified_missing']=[r['index'] for r in missing];save()
                raise ImageModelsExhausted('All configured Nano Banana models reached quota. Completed batches retained; account fallback may continue the next batch.')
        log(f'Agent batch {batch_number}/{len(groups)}: {len(missing)} remaining scene outputs.')
        batch_config={**config,'image_agent':True,'agent_image_model':generator.agent_image_model,'exhausted_image_models':state.get('exhausted_image_models',[])} if image_batch else config
        if 'reference_names' in group[0]:
            names={name for r in missing for name in r.get('reference_names',[])}
            batch_config={**batch_config,'references':[p for p in config.get('references',[]) if Path(p).stem in names],
                          'reference_descriptions':{k:v for k,v in config.get('reference_descriptions',{}).items() if k in names}}
            log('Batch reference library: '+(', '.join(sorted(names)) or 'none')+'. Each scene uses only its explicitly assigned references.')
        pending=[r for r in missing if r['status']=='pending']
        if config.get('_recover_only'):
            exported=set(config.get('_exported_tokens',[]))
            submitted=[r for r in missing if possibly_sent(r) or r['token'] in exported]
            if submitted:generator.collect(submitted,save,on_media)
            if any(not possibly_sent(r) and r['token'] not in exported for r in missing):log('Unsubmitted scenes retained. Generate Images will submit them; Recover never spends new requests.')
            if submitted and config.get('_download_one_batch'):
                log('Downloaded the next batch in scene order. Generate the next text file, then click Download Generated Batch again. Build All reuses saved images.')
                return records
            continue
        if start not in recovered and any(possibly_sent(r) and (image_batch or r['status']=='pending') for r in missing):
            log('Retry verification: this image batch was prepared or submitted previously. Downloading verified existing outputs before any new submission; only unresolved scenes can be requested again.')
            if collect_or_recover(missing,start,verify_existing=True):
                return generate_agent_media(scenes,{**config,'_recovered_batches':list(recovered)},cancel,log,on_media,reference_records=reference_records)
            log('Previously generated batch recovered and saved; no prompts resubmitted.')
            continue
        if pending:
            if any(r['status']!='pending' for r in missing):
                if collect_or_recover([r for r in missing if r['status']!='pending'],start):
                    return generate_agent_media(scenes,{**config,'_recovered_batches':list(recovered)},cancel,log,on_media,reference_records=reference_records)
            if cinematic_enabled(config):
                from ai_studio_cinematic import handoff
                batch_config=handoff(scenes,records,pending[0],batch_config,cancel,log)
            prompt=batch_prompt(pending,batch_config)
            prompt_file=Path(config['project'])/f'{"reference_agent_batch" if reference_records is not None else "agent_batch"}_{batch_number:03d}.txt'
            prompt_file.write_text(prompt,encoding='utf-8')
            for r in pending:
                r['preparation_started']=True;r.pop('handover_unsubmitted',None)
            save() # persisted before any browser preparation/manual submit
            # Open the shared profile before letting the reference driver's
            # Puppeteer connection attach to the same existing project.
            with generator._session(headless=False) as ctx:
                page=generator._batch_page(ctx)
                # The session resolves the actual browser/account CDP port.
                # Keep it alive while Puppeteer attaches; config defaults may
                # still point at the legacy shared-profile port.
                prepare_batch_prompt({**batch_config,'_agent_cdp_port':generator.cdp_port},
                                     prompt_file,cancel,log)
                page.set_default_timeout(5000)
                composer=page.locator('div.ProseMirror[contenteditable=true]').first
                text=composer.inner_text()
                if not all(r['token'] in text for r in pending):raise RuntimeError('Prepared Agent prompt is incomplete. No generation submitted.')
                if batch_config.get('references') or 'reference_names' in group[0]:
                    labels=page.locator('div.ProseMirror[contenteditable=true] .mention-chip').all_text_contents()
                    names=[Path(p).stem.casefold() for p in batch_config['references']]
                    import re
                    if len(labels)!=len(names) or not all(any(re.search(r'(?<![a-z0-9_-])'+re.escape(name)+r'(?![a-z0-9_-])',label.casefold()) for label in labels) for name in names):
                        raise RuntimeError('Prepared Agent prompt is missing required character/location attachments. No generation submitted. Retry this batch; completed clips are retained.')
                # Read-only readiness polling: reconnecting can briefly hide the
                # Agent chip while Flow restores the composer and uploads.
                wait_agent_ready(page,cancel,log)
                submit=page.locator('button[aria-label="Start generation"]').first
                for r in pending:
                    r['status']='submitting'
                    if image_batch:r['generation_model']=preferred(batch_config)
                save() # uncertain submission is never automatically replayed
                submit.click(timeout=5000)
                page.wait_for_function("() => !(document.querySelector('div.ProseMirror[contenteditable=true]')?.innerText||'').trim()",timeout=15000)
                for r in pending:r['status']='submitted'
                save();generator.fresh_submission=True
                log('Agent batch submitted. Waiting for positively matched outputs…')
        if collect_or_recover([r for r in group if r['status']!='complete'],start):
            return generate_agent_media(scenes,{**config,'_recovered_batches':list(recovered)},cancel,log,on_media,reference_records=reference_records)
        log(f'Agent batch {batch_number} complete. All outputs matched and saved.')
    return records
