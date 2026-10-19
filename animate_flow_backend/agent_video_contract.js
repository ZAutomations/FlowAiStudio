function withSettings(prompt,{model='',resolution='Flow',seconds=8,aspect='Flow'}={}){
 if(!prompt||resolution==='Flow')return prompt;
 if(!['360p','720p'].includes(resolution))throw Error('Invalid Agent video resolution.');
 const settings=`VIDEO GENERATION SETTINGS: Model ${model||'the selected Flow model'}; duration ${seconds} seconds; resolution ${resolution}; aspect ${aspect==='Flow'?'selected Flow ratio':aspect}; quantity 1. Use these settings for this clip.`;
 return settings+'\n'+prompt.replace(/^(Scene\s+\d+[^\n]*|CLIP\s+\d+[^\n]*)$/gim,line=>line+'\n'+settings);
}
module.exports={withSettings};
