"""ChatGPT master prompts and strict narration-preserving Animate story import."""
import json,re
from ai_studio_animate_options import animation_count

SCHEMA='''{"version":1,"title":"Story title","script":"FULL ORIGINAL NARRATION VERBATIM","animation":{"animation_mode":"partial","partial_animation_unit":"seconds","animate_seconds":80,"animate_count":10,"animate_clip_seconds":8,"animate_multishot":true},"scenes":[{"scene":1,"narration":"Exact consecutive passage from the script","visual_prompt":"Detailed scene-specific visual action and composition","media_type":"video","shots":[{"start":0,"end":3,"visual_prompt":"First narrated visual action"},{"start":3,"end":6,"visual_prompt":"Connected second action"},{"start":6,"end":8,"visual_prompt":"Reaction or detail concluding this clip"}]}]}'''

POSTING_PACKAGE = r"""
ADDITIONAL SEPARATE DELIVERABLE FILES (required, alongside the story JSON):
Create thumbnail_prompts.json and video_metadata.json as independently valid JSON files. Never put posting metadata or thumbnail scenes into the narration/story arrays. Never append thumbnails to the scene plan. Keep story import schemas unchanged.
If your environment supports file creation, attach each named file for download. Otherwise output one separate labelled JSON code block per filename; never combine files in one JSON or truncate any file.

thumbnail_prompts.json schema:
{"version":1,"video_title":"Selected best title","visual_preset":"Exact selected preset name","aspect_ratio":"Selected app ratio","thumbnails":[{"id":1,"concept":"Distinct topic-specific hook","headline":"2-5 short words in the narration language","references":["Exact relevant declared asset name"],"prompt":"Complete standalone image-generation prompt including full selected visual style, topic-specific subject/action/expression, composition, background, colors, lighting, exact headline placement and lettering, required reference identities and exclusions","negative_prompt":"Off-topic metaphors, clutter, long copy, wrong period, duplicate subjects, illegible text"}]}
Exactly FOUR thumbnails, ids 1-4, with genuinely different compositions/hooks, not color variations. Read the FULL story first. Show its actual main person/object or central conflict; do not illustrate isolated keywords or invent plot twists, evidence, outcomes or unsupported factual claims. Use the selected visual preset including its complete style text in EACH prompt: handpainted presets remain handpainted; white/light-grey backgrounds stay white/light-grey when specified. For documentary/explainer topics, show the relevant subject/illustration and use people only when needed. Use VS layouts only for an actual comparison. Otherwise use a clear single focal subject, expressive pose/reaction when relevant, one meaningful clue/prop, strong contrast and uncluttered negative space. Aim for mobile readability, compelling curiosity and 2-5-word headlines; no paragraphs or excessive labels. Headlines are allowed ONLY in thumbnails; scene media remains text-free. Respect selected aspect ratio. Reuse only appropriate declared references; do not invent attachment identifiers.

video_metadata.json schema:
{"version":1,"language":"Narration language","best_title":"Strong truthful topic-specific posting title","alternative_titles":["Alternative 1","Alternative 2","Alternative 3"],"description":"Copy-ready description: compelling accurate opening, concise story/topic summary without invented claims, natural relevant search phrases, appropriate call to action, and relevant hashtags at the end","hashtags":["#RelevantHashtag"],"tags":["relevant search phrase"],"tags_csv":"Same tags joined with commas","thumbnail_recommendation":1}
Choose ONE strongest title and three alternatives in the narration language. Write a clear curiosity-driven title grounded in the actual story; no fabricated shocking claims or promises of guaranteed virality. Provide 3-5 relevant hashtags and 10-20 distinct relevant tags with no unrelated trending terms or spam. Description must be ready to post, with no placeholders, invented timestamps, fake links or claims. Keep tags_csv within 500 characters. Any real-person/fiction disclosure must reflect supplied context; do not invent biographical facts. thumbnail_recommendation must select one of ids 1-4.
"""

def master_prompt(mode='partial'):
    if mode not in ('partial','full'):raise ValueError('Choose partial or full master prompt')
    selection=('Set animation_mode to full. EVERY scene must have media_type video.' if mode=='full' else
      'Set animation_mode to partial. Default: partial_animation_unit seconds and animate_seconds 80. '
      'If I specify a number of opening scenes instead, set partial_animation_unit scenes and animate_count to that number. '
      'Mark the estimated opening narration span as video and the remainder as image. Never assume 80 seconds means 80 scenes. '
      'The app uses actual locally generated narration durations to make the final video/still decision, so estimates are planning guidance only.')
    return '''You are the visual scene planner for Flow AI Studio Animate. Read the FULL narration before planning any scene.

I will provide a title, original narration, visual preset, context/culture/period, and optional recurring character/location references.
In animation set animate_clip_seconds to 8 and animate_multishot to true. Return the story as one complete valid JSON file named ready_story.json, plus the two additional deliverable files specified below. No explanations, ellipses or omitted scenes inside JSON.

NARRATION IS LOCKED: preserve every word and punctuation in its original language. Do not translate, rewrite, shorten, add dialogue, repeat or reorder passages. Each scene narration is a consecutive exact slice. Joining the scenes with whitespace must reproduce the full original narration. Include the complete unchanged narration in script.

MEDIA PLAN:
'''+selection+'''
If CURRENT APP SELECTION has animate_narration_mode cinematic, return semantic source beats with unchanged narration. The app generates continuous voice, regroups VIDEO beats against measured eight-second windows while retaining narration-based IMAGE beat boundaries, and writes the final continuity storyboard. Imported shot times are guidance only in that mode. Do not claim they are measured audio timings.
For VIDEO ROWS ONLY: split at natural sentence/clause boundaries into short scenes suitable for eight-second generated clips, usually about 16–20 spoken words; use shorter scenes when needed for Urdu/Hindi or slow expressive delivery. These are estimates, not a substitute for measuring TTS. Do not pad, remove or rewrite narration to meet timing. Each video row is ONE generated 8-second clip, containing 2–3 distinct connected sequential shots. A shot is not a separate media request. Provide shots with contiguous local start/end seconds covering exactly 0–8 seconds, and a specific visual_prompt for each shot. Use narration meaning to choose the shot count and cuts; do not force one image/shot per sentence. Show the shots sequentially inside the clip, never as a simultaneous collage or storyboard. The editor fits the clip to actual narration. Still-image rows remain ordinary narration-based images and need no shots array.

VISUAL DIRECTION:
Honor the selected visual preset consistently. Read each passage in full-story context: show the actual people, objects, place, events and meaning; never illustrate isolated keywords with unrelated metaphors. Do not add events, clues, suspects or conclusions absent from the script. Keep recurring faces, age, hair, fixed clothing and location layout consistent with the supplied reference names. Include only the people/places actually needed in that scene. Documentary passages may use topic-specific illustrations, objects or diagrams without invented recurring characters.

VIDEO PROMPTS: Mandatory visible hard cuts: default shots 0-3s, 3-6s, 6-8s; alternatively two shots 0-4s and 4-8s when the narration has two visual beats. Each shot visual_prompt MUST state the shot size/angle, its own narration-driven action, and the continuity to the preceding shot. Repeating one action with only a pan or zoom is not multiple shots. Do not write one continuous-shot prompt. Describe clear subject action, facial/body reactions, setting, framing and restrained camera movement. Characters remain silent with naturally closed mouths: no talking, lip-sync, singing or narration to camera. The narrator is added locally. No generated speech, voice-over, music, sound effects, subtitles, speech bubbles, logos or embedded text.
STILL-IMAGE TIMING IS DIFFERENT FROM VIDEO TIMING: eight seconds applies ONLY to video clips. Split the remaining narration into natural semantic image beats aiming for about 4 seconds each, usually 2-6 seconds depending on delivery and meaning. Estimate roughly 5-12 spoken words per image as a flexible guide, not a quota; prefer one complete short clause/idea. Break long sentences at meaningful clause boundaries; do not group several ideas to fill an eight-second image slot. Each image visual_prompt must depict precisely that row's narration in full-story context. Preserve every word in order; never shorten, pad or rewrite narration to force a duration. Do not split a word. Actual display duration is measured from generated narration, not fixed by this estimate. Still images require ONE image per narration beat, no shots array or video cuts.

IMAGE PROMPTS: describe one polished still with the same visual style, topic accuracy and reference identities. Do not request a video, collage, storyboard or multiple variants.
Default aspect: 16:9 landscape unless I explicitly request another ratio. Do not introduce portrait images accidentally. No tracking labels are needed; the app adds them at generation time.

OUTPUT FORMAT (expand scenes to the complete story; consecutive numbers starting at 1):
'''+SCHEMA+'''
For full animation change animation_mode to full. For a partial scene-count plan, include the requested animate_count and use scenes as the unit. media_type is advisory; the app's selected mode and actual narration clock are authoritative. For full story consistency, include a top-level assets array declaring every recurring character/location (up to 40),
with name, kind (character or location), aliases and detailed fixed description. Each scene includes references: an array
of only visibly required asset names (up to six), or []. Do not invent cast for documentary scenes. The app opens cast
review; references are created or selected there, not uploaded by this JSON.

INPUT:
Title: [PASTE TITLE]
Visual preset and extra direction: [PASTE PRESET / STYLE]
Animation requirement: '''+('FULL ANIMATION, all scenes.' if mode=='full' else 'First 80 seconds animated, remaining scenes as still images. [Change 80 or specify first 10 scenes.]')+'''
Reference identity descriptions (optional): [PASTE REFERENCES]
Original narration:
[PASTE COMPLETE SCRIPT]
'''+POSTING_PACKAGE

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
    selected={key:options[key] for key in ('animate_narration_mode','animation_mode','partial_animation_unit','animate_seconds','animate_count','animate_clip_seconds','animate_multishot') if key in options}
    selected['planning_source']='chatgpt_ready'
    result={'title':str(data.get('title',''))[:300],'script':script,'scenes':scenes,'options':selected}
    if 'assets' in data:
        from ai_studio_cast import validate
        cast=validate({'assets':data['assets'],'scenes':[{'scene':i+1,'narration':row['narration'],'references':row.get('references',[]),'visual_prompt':row['visual_prompt']} for i,row in enumerate(rows)]},script=script)
        result['assets']=cast['assets'];result['options'].update(character_consistency=True,reference_mode='characters')
        for target,row in zip(scenes,cast['scenes']):target['reference_names']=row['references']
    return result


def split_master_prompt():
    return '''Create FOUR separate complete JSON files: video_clips.json, image_scenes.json, thumbnail_prompts.json and video_metadata.json. No Gemini planning will follow.
Read the full narration. Preserve every original word, punctuation and order. Never rewrite or summarize narration.
I specify N opening eight-second video clips (e.g. 10 or 15); remaining narration becomes still-image scenes.
Use consecutive exact narration passages for each row. Spoken duration is estimated here; the app later measures
continuous audio and maps VIDEO directions to actual eight-second windows. IMAGE rows keep their own narration-based beat boundaries. Never claim estimates are measured.
STILL-IMAGE TIMING IS DIFFERENT FROM VIDEO TIMING: eight seconds applies ONLY to video clips. Split the remaining narration into natural semantic image beats aiming for about 4 seconds each, usually 2-6 seconds depending on delivery and meaning. Estimate roughly 5-12 spoken words per image as a flexible guide, not a quota; prefer one complete short clause/idea. Break long sentences at meaningful clause boundaries; do not group several ideas to fill an eight-second image slot. Each image visual_prompt must depict precisely that row's narration in full-story context. Preserve every word in order; never shorten, pad or rewrite narration to force a duration. Do not split a word. Actual display duration is measured from generated narration, not fixed by this estimate. Still images require ONE image per narration beat, no shots array or video cuts.

Use 2-3 distinct sequential shots per video, local start/end covering exactly 0-8. Prefer 0-3, 3-6, 6-8 seconds. Explicitly label HARD CUT at each boundary. A pan/zoom is not a cut. Each shot must state its narration beat, distinct framing/action, and continuity of cast, props and screen direction. Keep characters silent; local narrator speaks.
Keep recurring faces, dress, props, location layout, screen direction, lighting and emotional state consistent.
Each video has continuity {location,start_state,end_state,continues_previous}; a continuation's start_state must exactly
equal the preceding end_state and location. New time/place must be explicitly established. Reference names must match
the supplied filenames exactly, without extension. Do not invent cast for documentary scenes.
Use the supplied visual preset and 16:9 unless requested otherwise. No dialogue, lip-sync, music, embedded text or collage.

video_clips.json schema:
{"version":1,"title":"TITLE","script":"COMPLETE ORIGINAL SCRIPT","video_clips":[
{"narration":"EXACT FIRST PASSAGE","visual_prompt":"Concrete action and composition","references":["DSPMalik"],
"continuity":{"location":"PoliceStation","start_state":"At doorway","end_state":"At desk","continues_previous":false},
"shots":[{"start":0,"end":4,"visual_prompt":"First action"},{"start":4,"end":8,"visual_prompt":"Connected reaction"}]}]}

image_scenes.json schema:
{"version":1,"image_scenes":[{"narration":"EXACT NEXT PASSAGE","visual_prompt":"One concrete image matching story context",
"references":["DSPMalik"]}]}

Joining ALL video narration followed by ALL image narration must reproduce COMPLETE ORIGINAL SCRIPT unchanged.
Return every scene; no omissions, ellipses or duplicated narration. Exactly N video rows unless full animation is requested.
Keep images as ordinary narration-based images, not multi-shot videos. Each file is independently valid JSON.
For full story character consistency, ALSO include an "assets" array at the top level of video_clips.json.
Declare EVERY recurring character/location used in EITHER file, up to 40:
"assets":[{"name":"DSPMalik","kind":"character","aliases":["DSP"],"description":"Fixed face, age, hair, clothing and colors"},
{"name":"PoliceStation","kind":"location","aliases":[],"description":"Fixed architecture, entrances and layout"}]
Every references entry in both files must name a declared asset. At most six references per scene.
The app opens cast review and generates/reuses the complete approved library before attaching only needed identities.
Input: title, full original narration, desired N video clips (or full animation), selected visual preset and reference descriptions.
'''+POSTING_PACKAGE


def parse_split(video_raw,image_raw,original=''):
    def read(raw):
        try:return json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',str(raw).strip(),flags=re.I))
        except ValueError as exc:raise ValueError('Paste both complete ready JSON files.') from exc
    video=read(video_raw);images=read(image_raw)
    if not isinstance(video,dict) or not isinstance(images,dict) or video.get('version')!=1 or images.get('version')!=1:raise ValueError('Both ready JSON files must use version 1.')
    clips=video.get('video_clips');stills=images.get('image_scenes')
    if not isinstance(clips,list) or not clips or not isinstance(stills,list):raise ValueError('Use video_clips and image_scenes arrays.')
    combined=[];previous=None
    from ai_studio_cinematic import validate_plan
    for i,row in enumerate(clips+stills,1):
        if not isinstance(row,dict):raise ValueError('Every ready scene must be an object.')
        refs=row.get('references',[])
        if not isinstance(refs,list) or any(not isinstance(r,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',r) for r in refs):raise ValueError('Invalid reference identity name.')
        combined.append({**row,'scene':i})
        if i<=len(clips):
            state=row.get('continuity',{})
            item={**state,'clip':i,'visual_prompt':row.get('visual_prompt'),'shots':row.get('shots'),'references':refs}
            try:validate_plan(json.dumps([item]),[{'id':i,'cinematic_kind':'video'}],set(refs),previous)
            except (RuntimeError,TypeError) as exc:raise ValueError(str(exc)) from exc
            previous=item
    options={'animate_narration_mode':'cinematic','animate_clip_seconds':8,'animate_multishot':True,
             'animation_mode':'partial' if stills else 'full','partial_animation_unit':'scenes','animate_count':len(clips)}
    result=parse_ready(json.dumps({'version':1,'title':video.get('title',''),'script':video.get('script',''),
                                 'animation':options,'scenes':combined}),original)
    for target,row in zip(result['scenes'],combined):
        target['reference_names']=row.get('references',[])
        if 'continuity' in row:target['cinematic_continuity']=row['continuity']
    if 'assets' in video:
        from ai_studio_cast import validate
        cast=validate({'assets':video['assets'],'scenes':[{'scene':i+1,'narration':r['narration'],'references':r.get('references',[]),'visual_prompt':r['visual_prompt']} for i,r in enumerate(combined)]},script=video['script'])
        result['assets']=cast['assets']
        result['options'].update(character_consistency=True,reference_mode='characters')
    for target,row in zip(result['scenes'],combined):
        if 'continuity_updates' in row:target['continuity_updates']=row['continuity_updates']
    for key,source in [('style_name','visual_preset_name'),('animate_model','video_model')]:
        if video.get(source):result['options'][key]=video[source]
    ratios={'16:9':'1920x1080','9:16':'1080x1920','1:1':'1080x1080'}
    if video.get('aspect_ratio') in ratios:result['options']['resolution']=ratios[video['aspect_ratio']]
    result['options']['cinematic_ready_prompts']=True
    return result
