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

def animation_count(options, scene_count):
    reference_mode(options)
    mode = options.get('animation_mode', 'partial')
    if mode not in ('partial', 'full'):
        raise ValueError('Choose Partial animation or Full animation')
    if options.get('animate_model', VIDEO_MODELS[0]) not in VIDEO_MODELS:
        raise ValueError('Choose a supported Animate video model')
    if mode == 'full':
        return scene_count
    try:
        value = options.get('animate_count', 3)
        count = int(value)
        valid = not isinstance(value, bool) and float(value) == count and 0 <= count <= 3
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError('Partial animation opening count must be a whole number from 0 to 3')
    return min(count, scene_count)
