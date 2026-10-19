"""Shared topic grounding for image and animated scene planning."""
TOPIC_DIRECTION=(
    'Interpret every scene in the domain and purpose of the FULL video script, never from isolated keywords. '
    'Resolve short questions, pronouns and abstract words using the surrounding narration. '
    'Each visual prompt must explicitly name the relevant topic-specific subjects and illustrate the intended meaning. '
    'Keep the same subject domain throughout; do not substitute unrelated literal word associations or generic stock metaphors. '
    'For example, safer in a sexual-health comparison means the discussed pregnancy/STI risks and protective barriers, '
    'not a pedestrian crossing, road safety or a helmet. In a road-safety video, roads would be appropriate. '
    'Likewise protection, risk, control and transmission must depict their meaning in this video. '
    'Use topic-relevant objects, diagrams or actions for abstract lines; do not invent factual claims.'
)
MEANING_DIRECTION=(
    'Respect negation and the actual explanation: if narration says a process is NOT a switch, '
    'show the coordinated biological process rather than a literal wall switch, even crossed out. '
    'Avoid generic stand-ins such as thermostats for comfort, clocks for the whole event, or unrelated scenery. '
    'For health explainers name the specific relevant anatomical system and its function in this topic, '
    'using non-graphic clinical diagrams and restrained illustrative motion. Avoid erotic acts or explicit performance. '
    'Do not invent measured durations, brain-region assignments, symptoms or anatomical details absent from the script. '
    'Show one clear topic-specific causal event per scene. When a short rhetorical line adds no new visual fact, '
    'continue the preceding topic-specific illustration or introduce the next explanation instead of changing domains. '
    'Before returning each visual prompt, check it against the complete script, surrounding lines and any negation; '
    'revise unrelated word associations. No talking heads or characters narrating to camera.'
)

def planning_context(config,scenes,indices):
    return {'video_title':config.get('title',''), 'full_video_script':config.get('script',''),
            'scenes':[{'scene':i+1, 'narration':scenes[i]['narration'],
                       'previous_narration':scenes[i-1]['narration'] if i else '',
                       'next_narration':scenes[i+1]['narration'] if i+1<len(scenes) else ''}
                      for i in indices]}

def contextual_fallback(config,scenes,index):
    import json
    return (TOPIC_DIRECTION+'\nIllustrate ONLY the current scene, using this context to resolve its meaning: '
            +json.dumps(planning_context(config,scenes,[index]),ensure_ascii=False))
