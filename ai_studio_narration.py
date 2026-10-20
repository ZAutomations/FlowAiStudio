"""Gemini narration delivery, independent of visual style and spoken script."""
import re

STYLES={
    'original':('Audio Settings · unchanged',1.0,''),
    'auto':('Auto · match video topic',1.0,''),
    'storytelling':('Storytelling · warm and expressive',.96,'Tell a human story naturally: inviting opening, conversational phrasing, gentle emotional changes, meaningful pauses and a warm reflective ending. Avoid a flat announcer cadence.'),
    'relationship':('Relationship / family · intimate storyteller',.94,'Narrate as a thoughtful, empathetic storyteller sharing a family or relationship story. Warm conversational intimacy, natural rises and falls, softer reflective moments, restrained tension during conflict, and a sincere hopeful lesson. Do not sound flirtatious, theatrical or judgmental.'),
    'horror':('Horror · eerie and restrained',.88,'Tell a frightening fictional story with a low, restrained ominous tone, measured pacing, controlled breath and deliberate pauses before reveals. Build intensity gradually. Avoid constant whispering, screaming, sound effects or an exaggerated trailer voice.'),
    'suspense':('Suspense · tension and reveal',.93,'Build curiosity with precise rhythmic phrasing, brief anticipatory pauses and a restrained increase in urgency. Slow slightly before important reveals, then release tension. Do not rush every line or overact.'),
    'documentary':('Documentary · clear and authoritative',1.0,'Deliver a clear, composed documentary narration. Confident factual tone, articulate terminology, measured conversational rhythm and natural emphasis on explanations. Use short pauses between ideas. No sensationalism, seductive delivery or dramatic horror tension.'),
    'dsp_memoir':('Retired DSP · Punjabi case memoir',.94,'Narrate as a seasoned retired police officer recalling a case personally: composed authority, thoughtful recollection, measured conversational pace, restrained suspense while weighing evidence and a sober reflective ending. Use the language of the supplied narration, with natural Urdu/Punjabi pronunciation where applicable; never translate or add dialect words. Avoid a newsreader cadence, exaggerated gravel, shouting, theatrical horror or a promotional tone.'),
}

def validate(config):
    if config.get('animate_narration_mode','scene') not in ('scene','cinematic'):raise ValueError('Choose existing or narration-first cinematic Animate workflow')
    if config.get('narration_mode','scene') not in ('scene','continuous'):raise ValueError('Choose scene-by-scene or continuous narration')
    if config.get('narration_style','original') not in STYLES:raise ValueError('Choose a supported narration style')
    if len(str(config.get('narration_direction','')))>2000:raise ValueError('Extra narration direction must be at most 2000 characters')

def resolve(config):
    validate(config)
    selected=config.get('narration_style','original')
    if selected!='auto':return selected
    from ai_studio_story import PUNJAB_DSP_STYLE,PUNJAB_DSP_COLORMIX_STYLE
    if config.get('style_name') in (PUNJAB_DSP_STYLE,PUNJAB_DSP_COLORMIX_STYLE):return 'dsp_memoir'
    # Explicit content genres win over a visual rendering technique.
    topic=(str(config.get('title',''))+' '+str(config.get('script',''))).lower()
    if re.search(r'\b(horror|haunted|ghost|terrifying|demonic)\b',topic):return 'horror'
    if re.search(r'\b(suspense|thriller|mystery)\b',topic):return 'suspense'
    visual=str(config.get('style_name','')).lower()
    if 'document' in visual or 'documentry' in visual:return 'documentary'
    if 'relationship' in visual or re.search(r'\b(wife|husband|mother|father|family|marriage)\b',topic):return 'relationship'
    return 'storytelling'

def settings_for(config,index=0,total=1):
    style=resolve(config);settings=dict(config['settings'])
    if config.get('voice_engine')!='google_cloud':return settings,'original'
    if style=='original':return settings,style
    _,pace,direction=STYLES[style]
    position='opening' if index==0 else 'ending' if index==total-1 else 'middle'
    instruction=(direction+' Keep one consistent narrator identity across the video. This is the '+position+
        ' of a continuous narration; continue smoothly without restarting your introduction. '
        'Read ONLY the supplied narration verbatim. Do not speak these instructions, add words, music or sound effects.')
    extra=str(config.get('narration_direction','')).strip()
    if extra:instruction+=' Additional delivery direction: '+extra
    settings['gemini_tts_prompt']=instruction
    # Studio delivery presets require expressive Gemini synthesis, not the
    # conventional Studio/WaveNet route which cannot apply this instruction.
    settings['use_cloud_tts']=False
    settings['gemini_tts_speed']=round(max(.5,min(2,float(settings.get('gemini_tts_speed',1))*pace)),3)
    return settings,style
