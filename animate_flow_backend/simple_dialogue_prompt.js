const TURN_GAP=0.30;
const { COMPOSITION } = require('./relationship_composition');
function enabled(story){return story.narration_scope==='dialogue' && ['simple','minimal-test'].includes(story.dialogue_prompt_format);}
function gaze(story){return story.gaze_direction || (story.niche==='Relationship Dialogue — Stylized 3D' ? require('./relationship_3d_style').GAZE : '');}
function plan(story,scene,{extend=false}={}){
    if(!enabled(story))return null;
    const turns=scene.dialogue||[];
    if(!turns.length)return null;
    for(const t of turns)if(!['Sarah','George'].includes(t.speaker)||!String(t.line||'').trim())throw Error('Invalid dialogue speaker or empty line.');
    if(story.dialogue_prompt_format==='minimal-test'){
        const prompt=String(scene.veo3_prompt||'').trim();
        if(!prompt)throw Error('Minimal test scene has no saved prompt.');
        const text=extend ? prompt.replace(/^Generate one 8-second clip\./, 'Continue from the previous clip for 8 seconds.') : prompt;
        return {visual:'Natural conversation in the same room.',audio:text.split('AUDIO:')[1]||'',prompt:text};
    }
    const first=turns[0].speaker;
    const visual=`${extend?'Continue naturally in':'Natural conversation in'} ${story.place?.name||'the established room'}. Same reference characters, outfits and location. ${COMPOSITION} ${story.camera_direction || ''} ${story.performance_direction || ''} ${gaze(story)} ${first} delivers the first line. Optional gentle speaker close-ups; return to the established two-person framing without forcing cuts after every line.`;
    const audio='Calm, respectful speech at normal indoor volume. Finish each line, pause 0.30 seconds, then the next speaker responds. No overlapping speech. Only the named speaker talks; the other listens naturally.\n'+turns.map(t=>`${t.speaker} says in a natural ${t.speaker==='George'?'male':'female'} voice: "${t.line}"`).join('\n');
    return {visual,audio,prompt:`[SHOT] ${visual}\n[LOOK] ${story.style}\n[AUDIO] ${audio}`};
}
function agent(story,{from=1,to=story.scenes.length,aspect=null,seconds=8,native=false}={}){
    if(!enabled(story))return null;
    const scenes=story.scenes.slice(from-1,to),names=['George','Sarah'],place=story.place?.name;
    const refs=[...names,...(place?[place]:[])].map(n=>'@'+n).join(', ');
    if(story.dialogue_prompt_format==='minimal-test'){
        return [`Create ${scenes.length} separate clips for scenes ${from}-${to} only. One clip per scene; do not add, split or rewrite scenes.`,
            `REFERENCES: ${refs}. Keep the reference faces, hair and outfits.`,
            `FORMAT: ${aspect||'Keep the aspect ratio selected in Flow.'}`,
            ...scenes.map((s,i)=>`\nScene ${from+i} - ${s._scene_title||'Conversation'}\n${s.veo3_prompt}`)].join('\n')+'\n';
    }
    const out=[`Create ${scenes.length} separate clips, one clip per scene, using ${refs}, up to ${seconds} seconds each. Generate only scenes ${from}-${to}. Do not add, merge, split or rewrite scenes.`,
        `FORMAT: ${aspect||'Keep the aspect ratio selected in Flow settings.'}`,
        `STYLE: ${story.style}`];
    if(native)out.push('Use the attached named Flow Characters with their assigned voices: George is the man; Sarah is the woman. Keep each character’s own appearance and voice in every clip.');
    else out.push(...names.map(n=>`IDENTITY ${n}: ${story.character_descriptions[n.toLowerCase()]}`));
    out.push(`LOCATION: ${place||'Same room throughout'}. ${story.place?.description||''}`,
        `COMPOSITION: ${COMPOSITION}`,
        ...(story.camera_direction ? [`CAMERA: ${story.camera_direction}`] : []),
        ...(story.performance_direction ? [`ACTING: ${story.performance_direction}`] : []),
        ...(gaze(story) ? [gaze(story)] : []),
        'Natural, relaxed conversation. Comfortable posture, eye contact and small gestures. Gentle close-ups are optional. Calm, respectful tone at normal volume. Finish each line and pause 0.30 seconds before the next voice; no overlap. Only the labelled character speaks. Read every line exactly. No narrator, invented dialogue or captions.');
    scenes.forEach((s,i)=>{for(const d of s.dialogue||[])if(!names.includes(d.speaker)||!String(d.line||'').trim())throw Error('Invalid dialogue speaker or empty line.');out.push(`\nScene ${from+i} - ${s._scene_title||'Conversation'}`);for(const d of s.dialogue||[])out.push(`${d.speaker}: "${d.line}"`);});
    return out.join('\n')+'\n';
}
module.exports={enabled,plan,agent,TURN_GAP};
