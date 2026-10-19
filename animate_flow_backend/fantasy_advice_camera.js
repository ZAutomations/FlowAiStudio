const CAMERA='LOCKED CHEST-UP PORTRAIT: frame Lilly from the top of her tiara to her upper chest, with the lower edge crossing the bodice at chest level. Show her face, hair, shoulders and upper chest only. Keep her modest gown neckline and outfit unchanged. Her face dominates the portrait with little headroom; her tiara remains fully visible. Her waist, hands, lap, skirt, legs and bench are outside the frame. Face-level frontal camera, centered composition, softly blurred garden background. Keep the small reference frog Pip visible perched on one of her shoulders inside this same crop. His movements never change the camera framing. Once this close portrait is established during clip 1, hold exactly the same crop and camera position through the final clip. No further zoom, pan, tracking, orbit, camera sway, wide shot or reframing.';
function shoulderAction(index){
 if(index===0)return 'As Lilly sits, Pip makes one small gentle hop onto her right shoulder (screen-left in the frontal view), then settles there. By the final close frame he is visibly perched on that shoulder.';
 const start=index%2===1?'right':'left',end=start==='right'?'left':'right';
 return `Pip begins on Lilly\'s ${start} shoulder, matching the preceding final frame. Once during a brief natural speech pause, he makes one playful gentle hop to her ${end} shoulder, then settles there until the clip ends. Shoulder sides refer to Lilly\'s own body; in this frontal shot her right is screen-left and her left is screen-right. Keep his small hopping arc behind or beside her neck, away from her face and mouth. No repeated bouncing, distress, face obstruction, talking, transformation or duplication. Lilly continues her calm advice with a small natural smile; no interruption or camera movement.`;
}
function apply(story){
 story.single_speaker_advice=true;
 story.voice_direction=require('./fantasy_advice_voice').TONE;
 story.camera_direction=CAMERA;
 for(let i=0;i<story.scenes.length;i++){
  const s=story.scenes[i],look=String(s.veo3_prompt||'').split('[LOOK]')[1]?.split('[AUDIO]')[0]?.trim()||story.style;
  const audio=require('./fantasy_advice_voice').audio(s);
  const action=i===0?'Lilly walks a few steps toward the stone bench with Pip while speaking the hook. As she sits, make ONE smooth zoom into the chest-up portrait. Complete this camera move during her sitting action, then hold still for the remaining speech. The final frame must be the locked chest-up portrait, not a wide seated shot.':`Lilly is already seated at the start. Match the preceding final frame exactly: the same locked chest-up portrait. She continues speaking naturally with subtle facial expressions and small head movements. Do not repeat her walk, sitting action or the opening zoom.`;
  const framing=i===0?'Opening camera move: approach shot, then one smooth zoom as Lilly sits; end locked in a head-and-upper-chest portrait.':'The FIRST FRAME and every subsequent frame use the identical chest-up crop established at the end of clip 1. Hold the camera completely still.';
  s.narrative_context=[framing,CAMERA,action,shoulderAction(i),story.place?.description].filter(Boolean).join(' ');
  s.veo3_prompt=`[SHOT] ${s.narrative_context}\n[LOOK] ${look}\n[AUDIO] ${audio}`;
 }
 return story;
}
function writeExtend(dir,story){
 const fs=require('fs'),path=require('path'),prompts={};
 story.scenes.slice(1).forEach((s,i)=>{const audio=String(s.veo3_prompt).split('[AUDIO]')[1]||'';prompts[i+2]=`Continue from the preceding final chest-up frame. Keep the same Lilly identity, outfit, seated posture, garden and locked camera crop.\n[SHOT] ${s.narrative_context}\n[AUDIO] ${audio.trim()}`;});
 fs.writeFileSync(path.join(dir,'extend_prompts.json'),JSON.stringify({note:'Fantasy advice continuation prompts preserving the locked chest-up frame established in clip 1.',derivedFrom:path.basename(dir)+'_story.json',prompts},null,2)+'\n');
}
module.exports={CAMERA,shoulderAction,apply,writeExtend};
