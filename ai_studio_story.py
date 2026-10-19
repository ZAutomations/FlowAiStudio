"""Gemini visual-story planning with unchanged narration and silent characters."""
import copy
import json
import re
from pathlib import Path
from ai_studio_visual_context import TOPIC_DIRECTION,MEANING_DIRECTION

STYLE_NAME = 'colorfull cartoon - relationship narration'
DOCUMENTARY_STYLE = '2D Documentary · illustrations'
HANDPAINTED_DOCUMENTARY_STYLE='handpanted documentry'
HANDPAINTED_RELATIONSHIP_STYLE='handpanted relationship'
MODERN_MIXED_STORY_STYLE='Modern Stories · Colorful Handpainted + Hyperrealistic'
MODERN_MIXED_STORY_DIRECTION=(
    'This is an off-screen narrated contemporary story: crime, love, betrayal, family drama or suspense as established by the script. '
    'Keep the original narration unchanged; show its actual events through silent character actions, expressions and concrete story details. '
    'Use a modern present-day setting when no date is specified; honor any explicit country, culture, year and location in the narration. '
    'Do not impose historical Punjab, a retired DSP, village scenery or a recurring couple unless the script requires them. '
    'Maintain recurring faces, ages, hair, clothes and location layouts; attach only the references assigned to that scene. '
    'Love scenes should convey tenderness or emotional distance through natural gestures; betrayal through the specific discovery and reactions; '
    'crime through the actual investigation, clues and consequences described. Never invent evidence, extra suspects or events. '
    'Interpret each scene within the full story context; never replace abstract words with unrelated literal metaphors. '
    'On-screen characters remain silent: no dialogue, lip-sync, singing or narration to camera. '
    'No generated voice-over, music, subtitles, speech bubbles or embedded text.'
)
PUNJAB_DSP_STYLE='Punjab DSP · village case memoirs (1920–1960)'
PUNJAB_DSP_COLORMIX_STYLE='Punjab DSP Handpantend ColorMix'
PUNJAB_DSP_DIRECTION=(
    'This is a retired DSP recounting a case from his service in the Punjab region now in Pakistan, between 1920 and 1960. '
    'The off-screen memoir narration is added locally; the visuals show the actual narrated case, not a talking presenter. '
    'Keep the story language and narration unchanged. Depict the officer at his age during the events in flashbacks; '
    'show him as retired only if the narration explicitly returns to his later recollection. '
    'Use the year, season, village, district and social context stated in the script. Before 1947 portray pre-Partition Punjab; '
    'after 1947 portray Pakistani Punjab. Never introduce post-independence flags, uniforms or emblems into a pre-1947 scene. '
    'If the year is unstated, avoid date-specific insignia and symbols and keep one consistent broadly mid-century rural setting. '
    'Show plausible Punjabi village courtyards, modest brick or earth-built homes, lanes, fields and period police stations, '
    'with locally appropriate practical dress and headwear selected from the script, not a generic fantasy village. '
    'Use period-appropriate simple furniture, paper case registers, handwritten records, lamps and transport only where relevant. '
    'No smartphones, CCTV, computers, modern police vehicles, modern road markings, LED lighting or contemporary branding. '
    'Do not dress everyone identically or force religious, class or ethnic stereotypes. Preserve named character roles and identities. '
    'Build the atmosphere through restrained investigative action, expressions, village details and natural suspense. '
    'Do not invent evidence, suspects, violence, confessions or conclusions that are absent from the narration. '
    'On-screen characters remain silent, with no dialogue, lip-sync or narration to camera. '
    'No generated voice-over, music, subtitles, speech bubbles or embedded text.'
)
DOCUMENTARY_STYLES=(DOCUMENTARY_STYLE,HANDPAINTED_DOCUMENTARY_STYLE)
DOCUMENTARY_DIRECTION = ('This is an off-screen narrated educational documentary explainer. The narration is added locally. '
    'Illustrate the exact scene subject using objects, diagrams, simple cutaway illustrations and clear visual demonstrations. '
    'Do not invent a recurring couple, named cast or fixed story location. Include people only when the specific explanation needs them. '
    'Any people remain silent, with no dialogue, speech, singing or lip-sync. Use restrained object motion and camera movement. '
    'No generated voice-over, music, subtitles, speech bubbles or embedded text. '+TOPIC_DIRECTION)
SILENT_DIRECTION = ('This is an off-screen narrated relationship story. The narrator is added locally after generation. '
    'On-screen characters remain silent: no dialogue, talking, speech, singing or lip-sync; keep mouths naturally closed. '
    'Show the meaning of the narration through character actions, facial reactions, body language and concrete visual events. '
    'Do not portray a character delivering the narration to the camera. No generated voice-over, music, subtitles, speech bubbles or embedded text.')

def is_narration_story(config):
    return config.get('style_name') in (STYLE_NAME,MODERN_MIXED_STORY_STYLE,HANDPAINTED_RELATIONSHIP_STYLE,PUNJAB_DSP_STYLE,PUNJAB_DSP_COLORMIX_STYLE,*DOCUMENTARY_STYLES)

def narration_direction(config):
    if config.get('style_name')==MODERN_MIXED_STORY_STYLE:return MODERN_MIXED_STORY_DIRECTION
    if config.get('style_name') in (PUNJAB_DSP_STYLE,PUNJAB_DSP_COLORMIX_STYLE):return PUNJAB_DSP_DIRECTION
    return DOCUMENTARY_DIRECTION if config.get('style_name') in DOCUMENTARY_STYLES else SILENT_DIRECTION

def can_replan_pending(config,scenes):
    """Only unsent requests with no generated scene files may be replanned."""
    if any(s.get('video_path') or s.get('image_path') for s in scenes):return False
    file=Path(config['project'])/'animate_media.json'
    if not file.is_file():return False
    try:
        state=json.loads(file.read_text('utf-8'))
        if not re.fullmatch(r'[a-f0-9]{64}',str(state.get('identity',''))):return False
        rows=state.get('records',[])
    except (ValueError,OSError):return False
    if not rows or len(rows)!=len(scenes):return False
    return all(r.get('index')==i and r.get('status')=='pending' and isinstance(r.get('output'),str)
               and not Path(r['output']).exists() for i,r in enumerate(rows))

def scene_direction(prompt,direction=SILENT_DIRECTION):
    return prompt if direction in prompt else prompt + '\n\n' + direction

def video_direction(prompt,direction=SILENT_DIRECTION):
    prompt=prompt.replace('Generate one finished image, not a description or a storyboard.',
                          'Generate one silent six-second animated video clip, not a still image or storyboard.')
    prompt=prompt.replace('One scene in this image.', 'One continuous scene in this video clip.')
    return scene_direction(prompt,direction)

def parse_prompts(raw, scenes):
    raw=str(raw or '').strip()
    raw=re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.I)
    try:rows=json.loads(raw)
    except ValueError as error:raise RuntimeError('Gemini returned invalid story JSON. Existing narration and prompts were preserved; retry Write Story.') from error
    if not isinstance(rows,list) or len(rows)!=len(scenes):
        raise RuntimeError('Gemini returned an incomplete scene plan. Existing narration and prompts were preserved.')
    prompts=[]
    for index,(row,scene) in enumerate(zip(rows,scenes),1):
        if (not isinstance(row,dict) or type(row.get('scene')) is not int or row['scene']!=index or
            row.get('narration')!=scene['narration'] or not isinstance(row.get('visual_prompt'),str) or not row['visual_prompt'].strip()):
            raise RuntimeError('Gemini changed the narration or scene order, or omitted a visual prompt. Existing scenes were preserved.')
        prompts.append(row['visual_prompt'].strip())
    return prompts

def write_story(adapter, q, config):
    from ai_studio_pipeline import atomic_json, check_cancel, fingerprint
    scenes=copy.deepcopy(adapter.zb_scenes)
    documentary=config.get('style_name') in DOCUMENTARY_STYLES
    direction=narration_direction(config)
    if not scenes:raise ValueError('Paste narration before Write Story')
    identity=fingerprint('narration-story-v2',config['script'],[s['narration'] for s in scenes],config['style'],
        config.get('continuity',''),config.get('reference_design',''),config.get('character_names',''),config.get('place_name',''))
    legacy_identity=fingerprint('narration-story-v1',config['script'],[s['narration'] for s in scenes],config['style'],
        config.get('continuity',''),config.get('reference_design',''),config.get('character_names',''),config.get('place_name',''))
    if documentary:
        from ai_studio_animate_options import reference_mode
        identity=fingerprint(identity,reference_mode(config))
        legacy_identity=fingerprint(legacy_identity,reference_mode(config))
    path=Path(config['project'])/'narration_story.json'
    cache=json.loads(path.read_text('utf-8')) if path.is_file() else {}
    committed=(Path(config['project'])/'animate_media.json').exists() or any(s.get('video_path') or s.get('image_path') for s in scenes)
    compatible=cache.get('identity')==identity or (committed and cache.get('identity')==legacy_identity)
    prompts=cache.get('prompts',[]) if compatible else []
    if len(prompts)==len(scenes) and all(isinstance(p,str) and p.strip() for p in prompts):
        q.put(('log','info','Reusing the saved Gemini visual story; narration is unchanged.'))
    else:
        # Changing a submitted plan must not lose recovery identities or assign
        # old clips to new prompts. The New Project action preserves the old files.
        if ((Path(config['project'])/'animate_media.json').exists() and not can_replan_pending(config,scenes)) or any(s.get('video_path') or s.get('image_path') for s in scenes):
            raise RuntimeError('This project already has visual media or Agent requests. Use New Animate Project before Write Story; existing clips, images and checkpoints are preserved.')
        system=('You are a visual director for an off-screen narrated story. Return ONLY a JSON array, in order, '
            'with one object per supplied scene: {"scene":1,"narration":"exact input narration","visual_prompt":"visual directions"}. '
            'Scene numbers restart at 1 for each request. Copy narration exactly; never rewrite or omit words. '
            'Create one concrete visual beat that illustrates the meaning, rather than characters talking about it. '
            +('Describe objects, diagrams, illustrative demonstrations and composition. Use people only when needed by the explanation; never invent a recurring cast. ' if documentary else 'Describe recurring character identities, physical action, emotion, environment, composition and restrained camera motion. ')+
            'Use one plausible six-second action for a video; no montage or multiple cuts. '+direction+'\n'+TOPIC_DIRECTION+'\n'+MEANING_DIRECTION)
        prompts=[]
        for start in range(0,len(scenes),8):
            check_cancel(adapter._zb_cancel)
            group=scenes[start:start+8]
            request={'style':config['style'],'continuity':config.get('continuity',''),
                'character_names':config.get('character_names',''),'place_name':config.get('place_name',''),
                'reference_design':config.get('reference_design',''),
                'video_title':config.get('title',''), 'story_context':config['script'],
                'preceding_narration':scenes[start-1]['narration'] if start else '',
                'following_narration':scenes[start+len(group)]['narration'] if start+len(group)<len(scenes) else '',
                'scenes':[{'scene':i+1,'narration':s['narration']} for i,s in enumerate(group)]}
            if documentary and reference_mode(config)=='none':
                for key in ('character_names','place_name','reference_design'):request[key]=''
            q.put(('log','info',f'Gemini Write Story: visual directions for scenes {start+1}–{start+len(group)}; narration stays unchanged.'))
            raw,error=adapter._zb_llm(system,json.dumps(request,ensure_ascii=False),max_tokens=6000,provider='gemini')
            check_cancel(adapter._zb_cancel)
            if error:raise RuntimeError('Gemini Write Story failed: '+str(error)+'. Narration and prompts were preserved.')
            prompts.extend(parse_prompts(raw,group))
        # Commit only after every batch validates, never a half-written story.
        atomic_json(path,{'version':1,'identity':identity,'prompts':prompts,'narration_unchanged':True})
    changed=any(scene.get('visual_prompt')!=scene_direction(prompt,direction) for scene,prompt in zip(scenes,prompts))
    for scene,prompt in zip(scenes,prompts):scene['visual_prompt']=scene_direction(prompt,direction)
    adapter.zb_scenes=scenes
    if changed:adapter.zb_last_video=None
    adapter._zb_save_project(config)
    q.put(('refresh',))
    subject='scene illustrations follow the explanation' if documentary else 'characters act silently'
    q.put(('log','success',f'Wrote visual prompts for {len(scenes)} scenes. Narration is unchanged; {subject}. Next: Generate Agent Media or Build All.'))
