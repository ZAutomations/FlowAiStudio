"""Shared media selection for the Animate generator and renderer."""
VIDEO_MODELS = ('Omni 1.1 Flash', 'Veo 3.1 - Fast', 'Veo 3.1 - Lite')

def reference_mode(options):
    mode=options.get('reference_mode','auto')
    if mode not in ('auto','characters','none'):
        raise ValueError('Choose Auto, Character references or No references')
    if mode=='auto':
        # Documentary Auto must ignore reference paths inherited from another
        # preset. Using a cast here requires the explicit characters mode.
        from ai_studio_story import DOCUMENTARY_STYLES
        return 'none' if options.get('style_name') in ('Documentary',*DOCUMENTARY_STYLES) else 'characters'
    return mode

def partial_options(options):
    import math
    unit=options.get('partial_animation_unit','scenes')
    if unit not in ('scenes','seconds'):raise ValueError('Choose opening scenes or opening narration seconds')
    value=options.get('animate_count',3) if unit=='scenes' else options.get('animate_seconds',80)
    try:
        number=float(value)
        valid=not isinstance(value,bool) and math.isfinite(number) and number>=0
        if unit=='scenes':valid=valid and number==int(number)
    except (TypeError,ValueError,OverflowError):valid=False
    if not valid:raise ValueError('Opening animation must be a non-negative whole scene count or a valid seconds value')
    return unit,int(number) if unit=='scenes' else number

def scene_duration(scene):
    from ai_studio_pipeline import probe
    from pathlib import Path
    path=scene.get('audio_path','')
    if path and Path(path).is_file():
        try:
            duration,streams=probe(path)
            if duration>0 and any(s.get('codec_type')=='audio' for s in streams):return duration
        except (ValueError,RuntimeError,OSError):pass
    return max(1,len(scene.get('narration','').split())/2.5)

def animation_count(options, scene_count, scenes=None):
    reference_mode(options)
    clip_seconds(options)
    mode=options.get('animation_mode','partial')
    if mode not in ('partial','full'):raise ValueError('Choose Partial animation or Full animation')
    if options.get('animate_model',VIDEO_MODELS[0]) not in VIDEO_MODELS:raise ValueError('Choose a supported Animate video model')
    if mode=='full':return scene_count
    unit,value=partial_options(options)
    if unit=='scenes':return min(value,scene_count)
    if value==0:return 0
    if scenes is None:
        import math
        return min(scene_count,math.ceil(value/clip_seconds(options)))
    elapsed=0;count=0
    for scene in scenes[:scene_count]:
        if elapsed>=value-1e-7:break
        count+=1;elapsed+=scene_duration(scene)
    return count

def active_video_seconds(options,shot):
    if options.get('animation_mode','partial')=='partial':
        unit,value=partial_options(options)
        if unit=='seconds':return max(0,min(shot['duration'],value-shot['start']))
    return shot['duration']

def clip_seconds(options):
    value=options.get('animate_clip_seconds',6)
    try:number=float(value)
    except (TypeError,ValueError):number=0
    if isinstance(value,bool) or number not in (6,8):raise ValueError('Animate clip duration must be 6 or 8 seconds')
    return int(number)
