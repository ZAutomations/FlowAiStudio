const assert=require('node:assert/strict');
const {settingChoice}=require('./animate_flow_backend/agent_settings');
const rect=()=>({width:100,height:30});
global.getComputedStyle=()=>({display:'block',visibility:'visible',opacity:'1'});
let selected='x2',videoClicks=0;
const button=label=>({textContent:label,parentElement:null,getBoundingClientRect:rect,
 querySelector:()=>null,getAttribute:key=>key==='aria-checked'?String(selected===label):null,
 click:()=>{selected=label;}});
const image={innerText:'Image generation default',parentElement:null,getBoundingClientRect:rect,querySelectorAll:()=>[button('x1'),button('x2')]};
const video={innerText:'Video generation default',parentElement:null,getBoundingClientRect:rect,querySelectorAll:()=>[{...button('x1'),click:()=>videoClicks++}]};
global.document={querySelectorAll:()=>[video,image]};
assert.equal(settingChoice({kind:'imageCount',click:false}),false);
settingChoice({kind:'imageCount',click:true});
assert.equal(selected,'x1');assert.equal(videoClicks,0);
assert.equal(settingChoice({kind:'imageCount',click:false}),true);
console.log('Image output count x1 selected and verified only in Agent image section.');
