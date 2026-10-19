const fs=require('fs'),path=require('path');
function applies(p,story){return String(p?.id||'').startsWith('relationship-dialogue')&&story.narration_scope==='dialogue';}
function render(story,scene){
 const style=/Stylized 3D/i.test(story.niche||'')?'Polished stylized 3D animation':/Ghibli/i.test(story.niche||'')?'Hand-painted 2D animation with soft watercolor shading':/Realistic/i.test(story.niche||'')?'Photorealistic cinematic film':'Human-like 2.5D illustration with soft dimensional shading';
 const turns=scene.dialogue||[];
 if(!turns.length||turns.some(d=>!['Sarah','George'].includes(d.speaker)||!String(d.line||'').trim()))throw Error('Simple relationship prompt requires labelled Sarah/George dialogue.');
 return [`Generate one ${Number(story.scene_seconds)||8}-second clip. Keep the aspect ratio selected in Flow.`,
 `STYLE: ${style}, matching the character reference images.`,
 `SETTING: A bright, clean ${story.place?.name||'domestic room'} with natural daylight. Sarah and George have a natural conversation.`,
 'CHARACTERS: Sarah is a 25-year-old adult woman. George is a 28-year-old adult man. Keep the same reference faces, hair and outfits. Use the attached references for their appearance.',
 'AUDIO: Calm, respectful conversation at a clearly audible normal volume. Speak the following lines exactly, in this order. Only the labelled character speaks each entire line; the other listens. Finish the last word, then leave a 0.30-second pause before the next line. No overlapping voices or narrator.',
 ...turns.map(d=>`${d.speaker} (${d.speaker==='Sarah'?'female':'male'} voice): ${JSON.stringify(d.line)}`)].join('\n')+'\n';
}
function apply(story){
 story.dialogue_prompt_format='minimal-test';
 for(const key of ['camera_direction','performance_direction','gaze_direction','blocking'])delete story[key];
 for(const scene of story.scenes){scene.veo3_prompt=render(story,scene);scene.narrative_context=`Natural conversation in the same ${story.place?.name||'room'}.`;}
 return story;
}
function write(dir,story){
 if(story.dialogue_prompt_format!=='minimal-test'||story.narration_scope!=='dialogue')return;
 const folder=path.join(dir,'simple_test_clip_prompts');fs.mkdirSync(folder,{recursive:true});
 fs.writeFileSync(path.join(dir,'SIMPLE_TEST.json'),JSON.stringify(story,null,2)+'\n');
 const combined=[];
 for(let i=0;i<story.scenes.length;i++){const n=String(i+1).padStart(3,'0');const prompt=story.scenes[i].veo3_prompt;fs.writeFileSync(path.join(folder,`clip_${n}.txt`),prompt);combined.push(`=== CLIP ${n} - ${story.scenes[i]._scene_title||'Conversation'} ===`,prompt);}
 fs.writeFileSync(path.join(dir,'ALL_SIMPLE_CLIP_PROMPTS.txt'),combined.join('\n'));
}
module.exports={applies,render,apply,write};
