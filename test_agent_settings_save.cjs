const assert=require('node:assert/strict');
const GR=require('./animate_flow_backend/generate_refs');
const {applyAgentSettings,saveAndVerifyAgentSettings}=require('./animate_flow_backend/agent_settings');
const rect={x:50,y:70,width:120,height:40};
const make=(hidden=false,disabled=false)=>({disabled,parentElement:null,
 getBoundingClientRect:()=>rect,getAttribute:()=>null,
 style:{display:'block',visibility:hidden?'hidden':'visible',opacity:'1'},
 closest:()=>({}),querySelector:()=>null,cloneNode:()=>({innerText:'Save',querySelectorAll:()=>[]})});
const hidden=make(true),disabled=make(false,true),live=make();
global.getComputedStyle=el=>el.style;
let buttons=[hidden,disabled,live],panels=[hidden];
global.document={querySelectorAll:selector=>selector.includes('settings-content')?panels:buttons};
(async()=>{
 let clicks=[];const page={evaluate:async fn=>fn(),mouse:{click:async(x,y)=>clicks.push([x,y])}};
 assert.equal(await GR.clickSave(page),true);assert.deepEqual(clicks,[[110,90]]);
 assert.equal(await GR.settingsPanelOpen(page),false);
 panels.push(live);assert.equal(await GR.settingsPanelOpen(page),true);
 global.innerWidth=1440;global.innerHeight=900;
 panels=[{...live,getBoundingClientRect:()=>({left:1440,right:1840,top:0,bottom:900,width:400,height:900})}];
 assert.equal(await GR.settingsPanelOpen(page),false);
 panels=[live];delete global.innerWidth;delete global.innerHeight;
 buttons=[hidden,disabled];assert.equal(await GR.clickSave(page),false);
 buttons=[live,make()];assert.equal(await GR.clickSave(page),false);
 const keys=['openSettingsPanel','setSectionModel','setPanelRatio','clickSave','settingsPanelOpen','closeSettings','readSectionModel'];
 const originals=Object.fromEntries(keys.map(k=>[k,GR[k]]));
 const timer=global.setTimeout;let saves=0,opens=0,closes=0;
 global.setTimeout=fn=>{fn();return 0;};
 try{
  GR.openSettingsPanel=async()=>{opens++;return true;};GR.setSectionModel=async()=>({ok:true,model:'Veo 3.1 - Lite'});
  GR.setPanelRatio=async()=>{};GR.clickSave=async()=>{saves++;return true;};
  GR.settingsPanelOpen=async()=>true; // Save deliberately does not close this build's drawer.
  GR.closeSettings=async()=>{closes++;return true;};
  GR.readSectionModel=async(_,kind)=>kind==='image'?'Nano Banana Pro':'Veo 3.1 - Lite';
  const fixture={evaluate:async()=>true,waitForFunction:async()=>true};
  await applyAgentSettings(fixture,{videoModel:'Veo 3.1 - Lite',aspect:'9:16'});
  assert.equal(saves,1);assert.equal(opens,2);assert.equal(closes,2);
  for(const imageModel of ['Nano Banana 2.1','Nano Banana 2 Lite']){
   const selected=[];
   GR.setSectionModel=async(_,kind,model)=>{selected.push([kind,model]);return {ok:true,model};};
   GR.readSectionModel=async(_,kind)=>kind==='image'?imageModel:'Veo 3.1 - Lite';
   await applyAgentSettings(fixture,{videoModel:'Veo 3.1 - Lite',imageModel,aspect:'9:16'});
   assert.deepEqual(selected[0],['image',imageModel]);
  }
  GR.readSectionModel=async(_,kind)=>kind==='image'?'Nano Banana Pro':'Omni 1.1 Flash';
  await assert.rejects(()=>saveAndVerifyAgentSettings(fixture,{videoModel:'Veo 3.1 - Lite',ratio:'9:16'}),/Saved video model.*expected Veo/);
  GR.readSectionModel=async(_,kind)=>kind==='image'?'Nano Banana Pro':'Veo 3.1 - Lite';
  await assert.rejects(()=>saveAndVerifyAgentSettings({evaluate:async()=>false},{videoModel:'Veo 3.1 - Lite',ratio:'9:16'}),/did not persist/);
  GR.closeSettings=async()=>false;
  await assert.rejects(()=>saveAndVerifyAgentSettings(fixture,{videoModel:'Veo 3.1 - Lite',ratio:'9:16'}),/Could not dismiss/);
 }finally{Object.assign(GR,originals);global.setTimeout=timer;}
 console.log('Settings Save: visible controls, retained drawer, reopened model/ratio persistence, and dismissal failure passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
