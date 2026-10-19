"""Original camera-style transitions and synthesized swooshes on a fixed narration clock.
No CapCut assets or code are used. Only one short boundary window is buffered.
"""
import json, math, os, random, subprocess, tempfile, time, wave
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter, ImageChops

STYLES = {'swipe_left':'Swipe Left','zoom_snap':'Zoom Snap','echo_shift':'Echo Shift',
          'blur_zoom_out':'Blur Zoom Out','pull_in_ii':'Pull In II','zoom_quake':'Zoom Quake','hexa_fade':'Hexa Fade'}
FLAGS = getattr(subprocess,'CREATE_NO_WINDOW',0)

def settings(options):
    duration=float(options.get('camera_transition_duration',.45))
    volume=float(options.get('camera_transition_volume',35))
    every=int(options.get('camera_transition_every',1))
    if not math.isfinite(duration) or not .15<=duration<=1.2:raise ValueError('Camera transition duration must be 0.15–1.2 seconds.')
    if not math.isfinite(volume) or not 0<=volume<=100:raise ValueError('Swoosh volume must be 0–100%.')
    if not 1<=every<=100:raise ValueError('Transition interval must be 1–100 cuts.')
    mode=options.get('camera_transition_style','sequential')
    if mode not in (*STYLES,'random','sequential'):raise ValueError('Choose a camera transition style.')
    pool=[key for key in STYLES if options.get('camera_transition_'+key,True)]
    if not pool and mode in ('random','sequential'):raise ValueError('Select at least one camera transition for the mix.')
    return duration,volume,every,mode,pool

def plan(timeline,options,fps=25):
    if not options.get('camera_transitions_enabled'):return []
    duration,volume,every,mode,pool=settings(options);rng=random.Random(1729);out=[]
    for i in range(1,len(timeline)):
        if i%every:continue
        boundary=math.ceil(timeline[i]['start']*fps-1e-7)
        left=boundary-math.ceil(timeline[i-1]['start']*fps-1e-7)
        right=math.ceil(timeline[i]['end']*fps-1e-7)-boundary
        half=min(max(2,round(duration*fps/2)),left//3,right//3)
        if half<2:continue
        key=rng.choice(pool) if mode=='random' else pool[len(out)%len(pool)] if mode=='sequential' else mode
        out.append({'scene':i+1,'cut':boundary/fps,'start_frame':boundary-half,'frames':2*half,'style':key,'duration':2*half/fps})
    return out

def zoom(image,scale=1,x=0,y=0):
    w,h=image.size;scale=max(1,float(scale));iw,ih=w/scale,h/scale
    cx=w/2+max(-1,min(1,x))*(w-iw)/2;cy=h/2+max(-1,min(1,y))*(h-ih)/2
    return image.transform((w,h),Image.Transform.AFFINE,(1/scale,0,cx-iw/2,0,1/scale,cy-ih/2),Image.Resampling.BILINEAR)

def frame(a,b,t,key):
    if t<=0:return a.copy()
    if t>=1:return b.copy()
    u=t*t*(3-2*t);peak=math.sin(math.pi*t)**2;w,h=a.size
    if key=='swipe_left':
        out=Image.new('RGB',a.size);shift=round(w*u)
        out.paste(a,(-shift,0));out.paste(b,(w-shift,0))
        # Directional trails hide the seam at peak camera speed.
        radius=round(w*.025*peak);acc=np.asarray(out,dtype=np.float32)
        for offset in (-radius,-radius//2,radius//2,radius):acc+=np.asarray(ImageChops.offset(out,offset,0),dtype=np.float32)
        return Image.fromarray(np.uint8(acc/5))
    if key=='zoom_snap':
        out=zoom(a if t<.5 else b,1+.9*peak)
        acc=np.asarray(out,dtype=np.float32)
        for n in range(1,6):acc+=np.asarray(zoom(out,1+peak*.025*n),dtype=np.float32)
        return Image.fromarray(np.uint8(acc/6)).filter(ImageFilter.GaussianBlur(peak*w*.002))
    if key=='blur_zoom_out':
        out=zoom(a if t<.5 else b,1+.65*(t*2 if t<.5 else (1-t)*2))
        return out.filter(ImageFilter.GaussianBlur(peak*w*.012))
    if key=='zoom_quake':
        out=zoom(a if t<.5 else b,1+.38*peak,math.sin(t*math.pi*15)*.55,math.cos(t*math.pi*19)*.5)
        return out.filter(ImageFilter.GaussianBlur(peak*w*.002))
    if key=='pull_in_ii':
        out=zoom(a if t<.5 else b,1+1.2*peak)
        # A continuous mesh approximates a lens pull without strip seams.
        mesh=[]
        def inset(y):return w*.075*peak*((y/h-.5)*2)**2
        for j in range(32):
            y0=round(j*h/32);y1=round((j+1)*h/32)
            mesh.append(((0,y0,w,y1),(inset(y0),y0,inset(y1),y1,w-inset(y1),y1,w-inset(y0),y0)))
        out=out.transform((w,h),Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
        return out.filter(ImageFilter.GaussianBlur(peak*w*.003))
    base=Image.blend(a,b,u)
    if key=='echo_shift':
        for n in (1,2,3):
            ghost=zoom(a if t<.5 else b,1+peak*n*.13,math.sin(n)*.4,0)
            base=Image.blend(base,ghost,peak*.16)
        return base
    if key=='hexa_fade':
        # Six translucent scale/offset layers, rather than a plain dissolve.
        for n in range(6):
            angle=n*math.pi/3
            ghost=zoom(a if n%2==0 else b,1+peak*(.12+.045*n),math.cos(angle)*.7,math.sin(angle)*.7)
            base=Image.blend(base,ghost,peak*.13)
        return base
    raise ValueError('Unknown camera transition: '+key)

def sound(key,rate=48000):
    n=int(rate*.48);t=np.arange(n)/rate;u=t/.48
    rng=np.random.default_rng(list(STYLES).index(key)+432)
    noise=rng.normal(0,1,n);low=np.convolve(noise,np.ones(9)/9,mode='same')
    env=np.sin(np.pi*u)**2
    chirp=np.sin(2*np.pi*(180*t+1900*t*t))
    x=(.6*low+.12*chirp)*env
    if key in ('zoom_snap','zoom_quake','pull_in_ii'):x+=.12*np.sin(2*np.pi*70*t)*np.exp(-((u-.53)/.075)**2)
    return np.asarray(x*.6,dtype=np.float32)

def bundle_sounds(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    for key in STYLES:
        with wave.open(str(folder/(key+'.wav')),'wb') as wav:
            wav.setparams((1,2,48000,0,'NONE','not compressed'));wav.writeframes((np.clip(sound(key),-1,1)*32767).astype('<i2').tobytes())

def _read(stream,size):
    data=bytearray()
    while len(data)<size:
        block=stream.read(size-len(data))
        if not block:break
        data.extend(block)
    if data and len(data)!=size:raise RuntimeError('Incomplete decoded transition frame.')
    return bytes(data)

def _stop(process):
    if process and process.poll() is None:process.kill();process.wait()

def apply(source,timeline,options,cancel=None,log=None,existing_sfx=None):
    from ai_studio_pipeline import check_cancel,probe,run_ffmpeg
    log=log or (lambda message:None);fps=25;events=plan(timeline,options,fps)
    if not events:return source,existing_sfx
    check_cancel(cancel);folder=Path(source).parent;target=folder/'camera_transitions.mp4';partial=folder/'camera_transitions.rendering.mp4'
    _,streams=probe(source);video=next(s for s in streams if s.get('codec_type')=='video');w,h=video['width'],video['height'];size=w*h*3
    dec=enc=None
    log(f'Camera transitions: {len(events)} cuts; narration and caption timing unchanged.')
    with tempfile.TemporaryFile() as error:
        try:
            dec=subprocess.Popen(['ffmpeg','-v','error','-nostdin','-i',str(source),'-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE,stderr=error,creationflags=FLAGS)
            enc=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r',str(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-threads','2',str(partial)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=error,creationflags=FLAGS)
            index=0;event_index=0;last_log=time.monotonic()
            while True:
                check_cancel(cancel)
                raw=_read(dec.stdout,size)
                if not raw:break
                event=events[event_index] if event_index<len(events) else None
                if event and index==event['start_frame']:
                    frames=[raw]
                    for _ in range(event['frames']-1):
                        check_cancel(cancel);chunk=_read(dec.stdout,size)
                        if not chunk:raise RuntimeError('Source video ended inside a transition window.')
                        frames.append(chunk)
                    half=len(frames)//2
                    for j in range(len(frames)):
                        check_cancel(cancel);t=j/(len(frames)-1);k=min(half-1,round(t*(half-1)))
                        a=Image.frombytes('RGB',(w,h),frames[k]);b=Image.frombytes('RGB',(w,h),frames[half+k])
                        enc.stdin.write(frame(a,b,t,event['style']).tobytes())
                    index+=len(frames);event_index+=1
                    log(f'Camera transition {event_index}/{len(events)}: {STYLES[event["style"]]} at {event["cut"]:.2f}s.')
                else:enc.stdin.write(raw);index+=1
                if time.monotonic()-last_log>15:log(f'Camera transitions render: {index/fps:.1f}s processed.');last_log=time.monotonic()
            dec.stdout.close();enc.stdin.close()
            if dec.wait()!=0 or enc.wait()!=0:
                error.seek(0);raise RuntimeError('Camera transition encoding failed: '+error.read().decode(errors='replace')[-2000:])
            check_cancel(cancel);os.replace(partial,target)
        finally:
            _stop(dec);_stop(enc)
            if dec and dec.stdout:dec.stdout.close()
            if enc and enc.stdin and not enc.stdin.closed:enc.stdin.close()
    sfx=existing_sfx
    if options.get('camera_transition_sfx',True) and float(options.get('camera_transition_volume',35))>0:
        sfx=render_sound(events,timeline[-1]['end'],folder,options,cancel)
        if existing_sfx:
            mixed=folder/'camera_and_existing_sfx.mp3'
            run_ffmpeg(['-i',existing_sfx,'-i',sfx,'-filter_complex','amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.9','-c:a','libmp3lame','-b:a','128k',mixed],cancel);sfx=mixed
    (folder/'camera_transitions.json').write_text(json.dumps({'events':events,'frames':index,'fps':fps,'sfx':bool(sfx),'volume':options.get('camera_transition_volume',35)},indent=2),encoding='utf-8')
    return target,sfx

def render_sound(events,duration,folder,options,cancel=None):
    from ai_studio_pipeline import check_cancel
    rate=48000;target=folder/'camera_swooshes.mp3';volume=float(options.get('camera_transition_volume',35))/100
    # One second chunks; memory stays constant for long stories.
    sounds={}
    for key in {e['style'] for e in events}:
        asset=Path(__file__).parent/'assets/sfx/camera'/(key+'.wav')
        if asset.is_file():
            with wave.open(str(asset),'rb') as wav:
                if wav.getparams()[:3]!=(1,2,rate):raise RuntimeError('Invalid bundled swoosh asset: '+key)
                samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32767
        else:samples=sound(key)
        sounds[key]=samples*volume
    tracks=[(max(0,round((e['cut']-.24)*rate)),sounds[e['style']]) for e in events]
    with tempfile.TemporaryFile() as error:
        p=subprocess.Popen(['ffmpeg','-v','error','-y','-f','f32le','-ar',str(rate),'-ac','1','-i','pipe:0','-c:a','libmp3lame','-b:a','128k',str(target)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=error,creationflags=FLAGS)
        try:
            total=math.ceil(duration*rate)
            for start in range(0,total,rate):
                check_cancel(cancel);end=min(total,start+rate);chunk=np.zeros(end-start,dtype='<f4')
                for offset,data in tracks:
                    lo=max(start,offset);hi=min(end,offset+len(data))
                    if lo<hi:chunk[lo-start:hi-start]+=data[lo-offset:hi-offset]
                p.stdin.write(np.clip(chunk,-.9,.9).tobytes())
            p.stdin.close()
            if p.wait()!=0:error.seek(0);raise RuntimeError(error.read().decode(errors='replace'))
        finally:
            _stop(p)
            if not p.stdin.closed:p.stdin.close()
    return target
