"""Bounded, deterministic camera movement for still-image Studio scenes."""
import math

STYLES = {'classic': 'Classic alternating zoom', 'balanced': 'Balanced cinematic mix',
          'push_in': 'Slow push in', 'pull_out': 'Slow pull out',
          'pan_left': 'Pan left', 'pan_right': 'Pan right',
          'pan_up': 'Pan up', 'pan_down': 'Pan down',
          'diagonal': 'Diagonal drift', 'pan_zoom': 'Pan + zoom'}

def validate_motion(options):
    if options.get('motion_style','classic') not in STYLES:
        raise ValueError('Choose a supported camera motion style')
    if options.get('motion_easing','linear') not in ('linear','smooth'):
        raise ValueError('Choose linear or smooth camera movement')
    for key, low, high, default in [('motion_strength',2,25,10),('motion_speed',.5,2,1)]:
        try:
            value=float(options.get(key,default))
            valid=not isinstance(options.get(key),bool) and math.isfinite(value) and low<=value<=high
        except (TypeError,ValueError):valid=False
        if not valid:raise ValueError(f'{key.replace("_"," ").title()} must be {low}–{high}')

def motion_filter(width, height, frames, index, options, fps=25):
    validate_motion(options)
    style=options.get('motion_style','classic')
    amount=float(options.get('motion_strength',10))/100
    speed=float(options.get('motion_speed',1))
    smooth=options.get('motion_easing','linear')=='smooth'
    # Keep the original default filter unchanged for older saved projects.
    if style=='classic' and amount==.1 and speed==1 and not smooth:
        z=f'min(1+0.10*on/{frames},1.10)' if index%2==0 else f'max(1.10-0.10*on/{frames},1)'
        x,y='iw/2-iw/zoom/2','ih/2-ih/zoom/2'
    else:
        if style=='balanced':
            style=('push_in','pan_right','pull_out','pan_up','diagonal','pan_left','pan_zoom','pan_down')[index%8]
        elif style=='classic':style='push_in' if index%2==0 else 'pull_out'
        t=f'min(1,on*{speed:.6f}/{max(1,frames-1)})'
        p=f'(({t})*({t})*(3-2*({t})))' if smooth else f'({t})'
        z=f'1+{amount:.6f}*{p}' if style=='push_in' else f'1+{amount:.6f}*(1-{p})' if style=='pull_out' else f'{1+amount:.6f}'
        x,y='(iw-iw/zoom)/2','(ih-ih/zoom)/2'
        if style in ('pan_left','pan_right','diagonal','pan_zoom'):
            direction=p if style=='pan_right' or (style in ('diagonal','pan_zoom') and index%2==0) else f'(1-{p})'
            x=f'(iw-iw/zoom)*{direction}'
        if style in ('pan_up','pan_down','diagonal'):
            direction=p if style=='pan_down' or (style=='diagonal' and index%2==0) else f'(1-{p})'
            y=f'(ih-ih/zoom)*{direction}'
        if style=='pan_zoom':
            # Never reach 1x during a pan; reserve cropping margin for travel.
            z=f'1+{amount:.6f}*(0.5+0.5*{p})'
    return (f'scale={width*2}:{height*2}:force_original_aspect_ratio=increase,'
            f"crop={width*2}:{height*2},zoompan=z='{z}':x='{x}':y='{y}'"
            f':d={frames}:s={width}x{height}:fps={fps},setsar=1')
