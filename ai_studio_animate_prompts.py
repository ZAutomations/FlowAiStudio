"""ChatGPT master prompts and strict narration-preserving Animate story import."""
import json,re
from ai_studio_animate_options import animation_count

SCHEMA='''{"version":1,"title":"Story title","script":"FULL ORIGINAL NARRATION VERBATIM","animation":{"animation_mode":"partial","partial_animation_unit":"seconds","animate_seconds":80,"animate_count":10,"animate_clip_seconds":8,"animate_multishot":true},"scenes":[{"scene":1,"narration":"Exact consecutive passage from the script","visual_prompt":"Detailed scene-specific visual action and composition","media_type":"video","shots":[{"start":0,"end":3,"visual_prompt":"First narrated visual action"},{"start":3,"end":6,"visual_prompt":"Connected second action"},{"start":6,"end":8,"visual_prompt":"Reaction or detail concluding this clip"}]}]}'''

def master_prompt(mode='partial'):
    if mode not in ('partial','full'):raise ValueError('Choose partial or full master prompt')
    selection=('Set animation_mode to full. EVERY scene must have media_type video.' if mode=='full' else
      'Set animation_mode to partial. Default: partial_animation_unit seconds and animate_seconds 80. '
      'If I specify a number of opening scenes instead, set partial_animation_unit scenes and animate_count to that number. '
      'Mark the estimated opening narration span as video and the remainder as image. Never assume 80 seconds means 80 scenes. '
      'The app uses actual locally generated narration durations to make the final video/still decision, so estimates are planning guidance only.')
    return '''You are the visual scene planner for Flow AI Studio Animate. Read the FULL narration before planning any scene.

I will provide a title, original narration, visual preset, context/culture/period, and optional recurring character/location references.
In animation set animate_clip_seconds to 8 and animate_multishot to true. Return ONLY one complete valid JSON object. Do not use Markdown fences, explanations, ellipses or omitted scenes.

NARRATION IS LOCKED: preserve every word and punctuation in its original language. Do not translate, rewrite, shorten, add dialogue, repeat or reorder passages. Each scene narration is a consecutive exact slice. Joining the scenes with whitespace must reproduce the full original narration. Include the complete unchanged narration in script.

MEDIA PLAN:
'''+selection+'''
Split at natural sentence/clause boundaries into short scenes suitable for eight-second generated clips, usually about 16–20 spoken words; use shorter scenes when needed for Urdu/Hindi or slow expressive delivery. These are estimates, not a substitute for measuring TTS. Do not pad, remove or rewrite narration to meet timing. Each video row is ONE generated 8-second clip, containing 2–4 connected sequential shots. A shot is not a separate media request. Provide shots with contiguous local start/end seconds covering exactly 0–8 seconds, and a specific visual_prompt for each shot. Use narration meaning to choose the shot count and cuts; do not force one image/shot per sentence. Show the shots sequentially inside the clip, never as a simultaneous collage or storyboard. The editor fits the clip to actual narration. Still-image rows remain ordinary narration-based images and need no shots array.

VISUAL DIRECTION:
Honor the selected visual preset consistently. Read each passage in full-story context: show the actual people, objects, place, events and meaning; never illustrate isolated keywords with unrelated metaphors. Do not add events, clues, suspects or conclusions absent from the script. Keep recurring faces, age, hair, fixed clothing and location layout consistent with the supplied reference names. Include only the people/places actually needed in that scene. Documentary passages may use topic-specific illustrations, objects or diagrams without invented recurring characters.

VIDEO PROMPTS: describe clear subject action, facial/body reactions, setting, framing and restrained camera movement. Characters remain silent with naturally closed mouths: no talking, lip-sync, singing or narration to camera. The narrator is added locally. No generated speech, voice-over, music, sound effects, subtitles, speech bubbles, logos or embedded text.
IMAGE PROMPTS: describe one polished still with the same visual style, topic accuracy and reference identities. Do not request a video, collage, storyboard or multiple variants.
Default aspect: 16:9 landscape unless I explicitly request another ratio. Do not introduce portrait images accidentally. No tracking labels are needed; the app adds them at generation time.

OUTPUT FORMAT (expand scenes to the complete story; consecutive numbers starting at 1):
'''+SCHEMA+'''
For full animation change animation_mode to full. For a partial scene-count plan, include the requested animate_count and use scenes as the unit. media_type is advisory; the app's selected mode and actual narration clock are authoritative. Reference files are chosen/created in the app; this JSON does not upload them.

INPUT:
Title: [PASTE TITLE]
Visual preset and extra direction: [PASTE PRESET / STYLE]
Animation requirement: '''+('FULL ANIMATION, all scenes.' if mode=='full' else 'First 80 seconds animated, remaining scenes as still images. [Change 80 or specify first 10 scenes.]')+'''
Reference identity descriptions (optional): [PASTE REFERENCES]
Original narration:
[PASTE COMPLETE SCRIPT]
'''

def parse_ready(raw,original=''):
    raw=re.sub(r'^```(?:json)?\s*|\s*```$','',str(raw).strip(),flags=re.I)
    try:data=json.loads(raw)
    except ValueError as error:raise ValueError('Paste the complete Animate story JSON.') from error
    if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('Animate story JSON must use version 1.')
    rows=data.get('scenes');script=data.get('script');options=data.get('animation',{})
    if not isinstance(rows,list) or not rows or not isinstance(script,str) or not script.strip() or not isinstance(options,dict):raise ValueError('Ready story requires script, animation options and scenes.')
    animation_count(options,0);scenes=[]
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict) or type(row.get('scene')) is not int or row['scene']!=i:raise ValueError('Scene numbers must start at 1 and be consecutive.')
        narration=row.get('narration');visual=row.get('visual_prompt')
        if not isinstance(narration,str) or not narration.strip() or not isinstance(visual,str) or not visual.strip():raise ValueError(f'Scene {i} needs narration and a visual prompt.')
        shots=row.get('shots',[])
        if shots:
            from ai_studio_animate_options import clip_seconds
            seconds=clip_seconds(options)
            if not isinstance(shots,list) or not 2<=len(shots)<=4:raise ValueError(f'Clip {i} needs 2–4 sequential shots.')
            previous=0
            for shot in shots:
                if not isinstance(shot,dict) or not isinstance(shot.get('visual_prompt'),str) or not shot['visual_prompt'].strip():raise ValueError('Every shot needs a visual direction.')
                try:start=float(shot['start']);end=float(shot['end'])
                except (KeyError,ValueError,TypeError):raise ValueError('Shot start/end times must be numbers.')
                if abs(start-previous)>1e-6 or not start<end<=seconds:raise ValueError('Shots must be contiguous and inside their clip duration.')
                previous=end
            if abs(previous-seconds)>1e-6:raise ValueError('Shots must cover the complete clip duration.')
        scenes.append({'id':i,'narration':narration,'visual_prompt':visual,'caption':'',**({'shots':shots} if shots else {})})
    normalize=lambda value:' '.join(value.split())
    if normalize(' '.join(s['narration'] for s in scenes))!=normalize(script):raise ValueError('Scene narration must preserve the complete original script.')
    if original.strip() and normalize(original)!=normalize(script):raise ValueError('Imported narration differs from the script currently pasted in Animate. Use a new project for a different story.')
    selected={key:options[key] for key in ('animation_mode','partial_animation_unit','animate_seconds','animate_count','animate_clip_seconds','animate_multishot') if key in options}
    return {'title':str(data.get('title',''))[:300],'script':script,'scenes':scenes,'options':selected}
