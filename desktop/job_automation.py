"""Opt-in retry policy and file-verified part compilation."""
import math,time

PROCESSING_ACTIONS={'images','generate-missing','cinematic-images','cinematic-videos','voice','render','build','compile-part','recover','download-batches','download-all-images','references','download-reference-images','thumbnails','retry-thumbnails','prompts','write-story','continuity-ledger'}

def schedule_retry(job,closed=False,now=None):
    if closed or job.get('state')!='failed' or job.get('retry_disabled'):return False
    payload=job.get('payload',{})
    if job.get('kind') not in ('studio','animate') or payload.get('auto_retry') is not True:return False
    if payload.get('action','build') not in PROCESSING_ACTIONS:return False
    delay=payload.get('auto_retry_seconds',10)
    try:delay=float(delay)
    except (ValueError,TypeError):delay=10
    if not math.isfinite(delay):delay=10
    delay=max(5,min(10,delay));attempt=int(job.get('auto_retry_count',0))+1
    job.update(state='queued',auto_retry_count=attempt,retry_at=(time.time() if now is None else now)+delay,progress=0,result=None,
        message=f'Auto retry {attempt} in {delay:g}s · unlimited attempts · Stop cancels retries')
    return True

def should_compile(payload,review_required=False):
    return not review_required and payload.get('auto_compile_part') is True and payload.get('action') in ('images','generate-missing','cinematic-images','recover','download-batches','download-all-images')

def verify_part_media(scenes,config,animated=False):
    from pathlib import Path
    from ai_studio_parts import scene_range
    from ai_studio_pipeline import valid_image
    start,end=scene_range(config,len(scenes))
    if start>=end:raise ValueError('Auto compile: no story scenes are available.')
    count=0
    if animated:
        from ai_studio_animate_options import animation_count
        count=animation_count(config,len(scenes),scenes)
    missing=[]
    for i in range(start,end):
        row=scenes[i]
        if animated and i<count:
            from ai_studio_animate_media import valid_video
            ok=valid_video(row.get('video_path',''))
        else:ok=valid_image(row.get('image_path',''))
        if not ok:missing.append(i+1)
    if missing:raise ValueError('Auto compile waiting: selected scene files are missing/invalid: '+', '.join(map(str,missing))+'. No incomplete video was rendered.')
    return start+1,end
