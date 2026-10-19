"""End-of-video thumbnail generation, separate from scene/request checkpoints."""
import copy,json,re,wave,time
from pathlib import Path
from ai_studio_pipeline import atomic_json,check_cancel,fingerprint,valid_image,probe

def validate(options):
    value=options.get('thumbnail_count',1)
    try:n=int(value)
    except (ValueError,TypeError,OverflowError):raise ValueError('Thumbnail count must be a whole number from 1 to 10')
    if isinstance(value,bool) or float(value)!=n or not 1<=n<=10:raise ValueError('Thumbnail count must be a whole number from 1 to 10')
    return n

THUMBNAIL_VERSION='end-thumbnail-v4'
SUBJECT_DIRECTION=(
    'Read the complete script and identify WHO or WHAT the video is actually about and its central situation. '
    'Choose a main subject that communicates that meaning, not an isolated keyword or generic medical symbol. '
    'For a person-centered topic, show a relevant adult person prominently, with a purposeful pose, clear facial expression '
    'and one concrete action or prop that pitches the story. Do not replace that person with a giant diagram. '
    'For example, a woman trying to conceive should be the dominant adult woman, thoughtfully or hopefully considering '
    'her cycle/calendar, with a small ovulation/fertility cue that explains timing. Her expression or body is not proof '
    'of fertility; do not invent visible symptoms, pregnancy, guaranteed conception or facts absent from the narration. '
    'For relationship or emotional topics, show the relevant adult people and their topic-specific body language. '
    'For a product comparison use the actual products; for an anatomy/mechanism topic use the relevant illustration. '
    'Do not force people into an object-centered video or force a recurring couple into every topic. '
)
ART_DIRECTION=(
    'Art direction is mandatory and overrides conflicting brief adjectives. Premium 2D hand-drawn cartoon illustration with clean dark outlines, expressive readable eyes, '
    'consistent adult proportions and subtle flat cel shading. No photorealism, no 3D rendering. '
    'Background exclusively white, off-white and light grey with fine grey environmental linework, '
    'simple relevant room or setting. Color reserved for the main people, clothing and meaningful props. '
    'Use bright yellow, red, blue and green character/prop accents for contrast on the pale background. '
    'No pastel blush, neon blue/magenta background, deep navy poster, sci-fi glow or luminous biological clock. '
    'Main subject must fill most of the cover below the headline, with a close-up readable pose and expression '
    'and at most one smaller meaningful supporting cue. No generic clip-art, tiny subjects, empty bottom strip or diagram collage. '
    'Reserve the top 22 percent for a short headline; keep faces and important gestures below it. '
    'No generated text, letters, numbers, logos or watermark. '
)

def art_prompt(brief,aspect,config=None):
    if brief.get('comparison',False):
        layout=('Comparison layout: two relevant subjects on the same white/grey illustrated background, '
                'distinguished by colored subjects and props. Small clear central area for a local VS badge and bottom labels. ')
    else:
        layout=('Single-topic layout: dominant story-relevant subject on a white/grey illustrated background. '
                'No VS badge, no split comparison panels, no left/right alternative labels, no forced opposing subjects. ')
    context=''
    if config:
        context='Full video context (interpret meaning; never print this text): '+json.dumps(
            {'title':config.get('title',''),'script':config.get('script','')},ensure_ascii=False)+'\n'
    return context+'Topic-specific composition: '+brief['visual_prompt']+'\n'+SUBJECT_DIRECTION+'\n'+ART_DIRECTION+'\n'+layout+f'Aspect ratio: {aspect}. Render only the artwork.'

def overlay(raw,output,headline,*,comparison=False,left_label='',right_label=''):
    from PIL import Image,ImageDraw,ImageFont
    image=Image.open(raw).convert('RGB');w,h=image.size;draw=ImageDraw.Draw(image)
    font_path=next((str(p) for p in (Path('C:/Windows/Fonts/impact.ttf'),Path('C:/Windows/Fonts/arialbi.ttf'),Path('C:/Windows/Fonts/arialbd.ttf')) if p.is_file()),'DejaVuSans-Bold.ttf')
    pad=max(4,int(w*.035))
    def band(text,y,height,fill,ink):
        if not text:return
        edge=max(2,int(w*.012))
        draw.polygon([(pad,y+height*.12),(w-pad,y),(w-pad-edge,y+height*.22),
                      (w-pad+edge,y+height*.25),(w-pad-edge*2,y+height*.44),
                      (w-pad+edge,y+height*.48),(w-pad*1.5,y+height*.88),
                      (pad*.5,y+height),(pad+edge,y+height*.73),(pad*.5,y+height*.68)],fill=fill)
        size=max(10,int(height*.76));font=ImageFont.truetype(font_path,size)
        while size>8 and draw.textbbox((0,0),text,font=font,stroke_width=1)[2]>w-pad*4:
            size-=1; font=ImageFont.truetype(font_path,size)
        bounds=draw.textbbox((0,0),text,font=font)
        # Slanted condensed lettering like the reference's energetic cover type.
        tw=bounds[2]-bounds[0];th=bounds[3]-bounds[1]
        lettering=Image.new('RGBA',(max(1,int(tw+height*.25)),max(1,int(height))),(0,0,0,0))
        ImageDraw.Draw(lettering).text((height*.05,(height-th)/2-bounds[1]),text,font=font,fill=ink)
        lettering=lettering.transform(lettering.size,Image.Transform.AFFINE,(1,.13,-height*.13,0,1,0),resample=Image.Resampling.BICUBIC)
        image.paste(lettering,(int((w-lettering.width)/2),int(y)),lettering)
    words=headline.upper().split();split=max(1,len(words)//2)
    if comparison and 'VS' in words and words.index('VS')+2<len(words):split=words.index('VS')+2
    band(' '.join(words[:split]),int(h*.015),int(h*.095),'#09090d','#ffffff')
    band(' '.join(words[split:]),int(h*.115),int(h*.105),'#ffe600','#09090d')
    if comparison:
        size=max(12,int(min(w*.17,h*.10)));font=ImageFont.truetype(font_path,size)
        bounds=draw.textbbox((0,0),'VS',font=font);tw=bounds[2]-bounds[0];th=bounds[3]-bounds[1]
        cx,cy=w*.5,h*.54;draw.polygon([(cx-tw*.8,cy-th*.8),(cx+tw*.9,cy-th),(cx+tw*.75,cy+th*.8),(cx-tw*.9,cy+th)],fill='#09090d')
        draw.text((cx-tw/2,cy-th/2-bounds[1]),'VS',font=font,fill='#ffffff')
        for label,x,fill in ((left_label,w*.04,'#0076d8'),(right_label,w*.54,'#db006a')):
            if not label:continue
            text=label.upper();y=int(h*.88);bw=int(w*.42);bh=int(h*.095)
            draw.polygon([(x,y+bh*.1),(x+bw,y),(x+bw,y+bh*.9),(x,y+bh)],fill=fill)
            size=max(10,int(bh*.63));font=ImageFont.truetype(font_path,size)
            while size>8 and draw.textlength(text,font=font)>bw*.9:
                size-=1;font=ImageFont.truetype(font_path,size)
            bounds=draw.textbbox((0,0),text,font=font)
            draw.text((x+(bw-(bounds[2]-bounds[0]))/2,y+(bh-(bounds[3]-bounds[1]))/2-bounds[1]),text,font=font,fill='#ffffff')
    temp=output.with_name(output.stem+'.writing.png');image.save(temp);temp.replace(output)

def generate(adapter,q,config):
    if not config.get('thumbnail_enabled',False):return
    count=validate(config);scenes=adapter.zb_scenes
    if not scenes or not all(valid_image(s.get('image_path','')) for s in scenes):
        raise RuntimeError('Finish all scene images before generating end thumbnails.')
    from zbot_ai_tab import RES_ASPECT
    aspect=RES_ASPECT.get(config['resolution'],'16:9')
    identity=fingerprint(THUMBNAIL_VERSION,config['title'],config['script'],config['style'],config['provider'],aspect)
    folder=Path(config['project'])/'thumbnails'/identity[:12];folder.mkdir(parents=True,exist_ok=True)
    file=folder/'plan.json';state=json.loads(file.read_text('utf8')) if file.exists() else {'identity':identity,'briefs':[]}
    if state.get('identity')!=identity:raise RuntimeError('Thumbnail plan identity is inconsistent; existing files preserved.')
    briefs=state['briefs']
    q.put(('log','info',f'All scene images finished. Generating {count} end thumbnail image(s)…'))
    if len(briefs)<count:
        q.put(('status','Writing thumbnail brief'))
        needed=count-len(briefs)
        system=('You are designing a striking professional viral educational YouTube cover, not a classroom slide or stock icon. '
            'Return ONLY a JSON array of objects with headline (2–5 words), visual_prompt, comparison (boolean), '
            'left_label and right_label (each at most 2 words, empty when not a comparison). '
            'Choose comparison=true only if this video actually compares alternatives, otherwise comparison=false. '
            'The headline names the concrete topic, e.g. MALE VS FEMALE CONDOMS for a comparison or FERTILITY WINDOW for an explainer, '
            'Prefer a natural curiosity question or punchy concrete hook, e.g. MOST FERTILE WHEN? rather than FERTILE WINDOW TIMING. Never claim certainty or guaranteed protection. No long sentence, explanatory subtitle or a list of facts. '
            'For a comparison describe the exact subject for each half, two large relevant subjects, each using distinctive clothing/prop colors on a shared white/grey background. '
            'For other topics use one dominant story-relevant subject on a white/grey illustrated background, with at most one supporting symbol. '
            'Do not force a VS, split screen or opposing subjects into a non-comparison topic. Keep either layout minimal and attractive. '
            'Do not invent claims, outcomes, danger or sensational facts absent from the script. '
            +SUBJECT_DIRECTION+ART_DIRECTION)
        request=json.dumps({'title':config['title'],'script':config['script'],'style':config['style'],
            'count':needed,'existing_options':briefs},ensure_ascii=False)
        check_cancel(adapter._zb_cancel)
        started=time.monotonic()
        raw,error=adapter._zb_llm(system,request,max_tokens=2500,provider=config['llm'])
        q.put(('log','info',f'Thumbnail brief writing: {time.monotonic()-started:.1f}s.'))
        check_cancel(adapter._zb_cancel)
        if error:
            q.put(('log','warn','Thumbnail writer unavailable; using the actual video title and script for artwork.'))
            words=re.findall(r'\S+',config['title']);headline=' '.join(words[:5])
            if len(words)<2:headline=(headline+' EXPLAINED').strip()
            raw=json.dumps([{'headline':headline,'visual_prompt':
                f'Use the supplied video topic to show a bold single-subject reveal, option {len(briefs)+i+1}. One main focal subject, strong contrast, no fabricated facts. Topic: '+config['title']+'. Context: '+config['script']} for i in range(needed)])
        try:
            rows=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',str(raw).strip(),flags=re.I))
            if not isinstance(rows,list) or len(rows)!=needed:raise ValueError()
            for row in rows:
                if not isinstance(row,dict) or not isinstance(row.get('headline'),str) or not 2<=len(row['headline'].split())<=5 or not isinstance(row.get('visual_prompt'),str) or not row['visual_prompt'].strip():raise ValueError()
                if not isinstance(row.get('comparison',False),bool):raise ValueError()
                for key in ('left_label','right_label'):
                    label=row.get(key,'')
                    if not isinstance(label,str) or len(label.split())>2:raise ValueError()
                if row.get('comparison') and (not row.get('left_label','').strip() or not row.get('right_label','').strip()):raise ValueError()
        except (ValueError,TypeError):raise RuntimeError('Thumbnail planner returned invalid briefs. Scene images retained; retry.')
        briefs.extend(rows);atomic_json(file,state)
    items=[]
    for i,brief in enumerate(briefs[:count],1):
        path=folder/f'thumbnail_{i:02d}.art.png'
        prompt=art_prompt(brief,aspect,config)
        if not valid_image(path):items.append((prompt,str(path)))
    if items:
        q.put(('status','Generating thumbnail artwork'))
        check_cancel(adapter._zb_cancel)
        if config['provider']=='gemini_api':
            from thumbnail_designer import generate_thumbnail
            for prompt,path in items:
                check_cancel(adapter._zb_cancel)
                result=generate_thumbnail(prompt,path,aspect=aspect,settings=config['settings'],
                    model=config['settings'].get('zb_gemini_image_model','gemini-2.5-flash-image'),log=lambda level,text:q.put(('log',level,text)))
                if not result or not valid_image(path):raise RuntimeError('Thumbnail generation failed. Scene images retained; retry.')
        else:
            from zbot_browser_images import ZBotImageGenerator
            from desktop.browser_accounts import browser_options
            generator=ZBotImageGenerator(config['provider'],mode=config['browser_mode'],flow_project_url=config['flow_url'],
                cancel=adapter._zb_cancel,share_google_profile=config.get('share_google_profile',False),flow_aspect_ratio=aspect,
                log=lambda text,level='info':q.put(('log',level,text)),**browser_options(config))
            generator.prime_flow_prompt_cache([Path(config['project'])/'images'/'image_batches.json'])
            results=generator.generate_batch(items,batch_size=config.get('image_batch_size',6),timeout=240,headless=config['headless'],retry_missing=config.get('_retry_missing_thumbnails',False))
            if len(results)!=len(items) or not all(ok for ok,detail in results):
                detail=next((str(detail) for ok,detail in results if not ok),'incomplete thumbnail batch')
                raise RuntimeError('Thumbnail generation paused: '+detail+'. Scene images and thumbnail checkpoints retained.')
    paths=[]
    for i,brief in enumerate(briefs[:count],1):
        check_cancel(adapter._zb_cancel)
        raw=folder/f'thumbnail_{i:02d}.art.png';output=folder/f'thumbnail_{i:02d}.png'
        if not valid_image(raw):raise RuntimeError('Thumbnail artwork is missing; retry generation.')
        if not valid_image(output):overlay(raw,output,brief['headline'],comparison=brief.get('comparison',False),left_label=brief.get('left_label',''),right_label=brief.get('right_label',''))
        paths.append(str(output));q.put(('log','success',f'Thumbnail {i}: saved {output}'))
    config['thumbnail_paths']=paths;config['thumbnail_identity']=identity
    adapter._zb_save_project(config);q.put(('refresh',))

def render_scenes(scenes,project,options,cancel=None):
    """Append normal still scenes without editing saved narration/scene records."""
    if not options.get('thumbnail_enabled',False):return scenes
    count=validate(options);paths=options.get('thumbnail_paths',[])
    if len(paths)!=count or not all(isinstance(path,str) and valid_image(path) for path in paths):
        raise RuntimeError('Generate Images or Thumbnails before rendering; end thumbnail files are missing.')
    from zbot_ai_tab import RES_ASPECT
    identities={fingerprint(version,options['title'],options['script'],options['style'],options['provider'],RES_ASPECT.get(options['resolution'],'16:9')) for version in ('end-thumbnail-v1','end-thumbnail-v2','end-thumbnail-v3',THUMBNAIL_VERSION)}
    if options.get('thumbnail_identity') not in identities:
        raise RuntimeError('Thumbnail settings or video content changed. Generate Images or Thumbnails again before rendering; old files retained.')
    duration=probe(scenes[-1]['audio_path'])[0]
    if duration<=0:raise RuntimeError('The final narration scene has no duration.')
    folder=Path(project)/'thumbnails';folder.mkdir(exist_ok=True)
    audio=folder/f'silence_{int(round(duration*48000))}.wav'
    if not audio.exists():
        with wave.open(str(audio),'wb') as output:
            output.setparams((2,2,48000,0,'NONE','not compressed'))
            output.writeframes(b'\0\0\0\0'*int(round(duration*48000)))
    check_cancel(cancel)
    result=copy.deepcopy(scenes)
    for i,path in enumerate(paths):result.append({'narration':'','caption':'','image_path':path,'audio_path':str(audio),'is_thumbnail':True})
    return result
