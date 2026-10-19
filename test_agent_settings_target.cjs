const assert=require('node:assert/strict');
const GR=require('./animate_flow_backend/generate_refs');
const make=(icon,agent=false,x=0,hidden=false)=>({disabled:false,parentElement:null,
 classList:{contains:name=>agent&&name==='agent-action-button'},closest:()=>null,
 getBoundingClientRect:()=>({x,y:30,width:40,height:40}),
 style:{display:'block',visibility:hidden?'hidden':'visible',opacity:'1'},
 querySelectorAll:selector=>selector==='mat-icon'?[{textContent:icon}]:[],getAttribute:()=> 'Settings'});
const grid=make('settings_2',false,100),tune=make('tune',true,700),hidden=make('tune',true,900,true);
let buttons=[grid,tune,hidden],sections=[];
global.getComputedStyle=el=>el.style;
const save=make('save');
global.document={querySelectorAll:selector=>selector==='button'?buttons:selector==='.settings-section'?sections:selector==='.settings-save-button'?[save]:[]};
assert.deepEqual(GR.agentSettingsTrigger(),{ok:true,x:720,y:50,label:'Agent Settings (tune)'});
buttons=[grid,hidden];assert.equal(GR.agentSettingsTrigger().ok,false);
buttons=[grid,tune,make('tune',true,800)];assert.equal(GR.agentSettingsTrigger().ok,false);
buttons=[grid,tune,hidden];
const section=text=>({...make(''),innerText:text});
sections=[section('Grid settings')];
(async()=>{
 const clicks=[],page={evaluate:async(fn,arg)=>fn(arg),mouse:{click:async(x,y)=>{
  clicks.push([x,y]);sections=[section('Video generation default'),section('Confirm before generating')];
 }},keyboard:{press:async()=>{throw Error('No recovery key expected');}}};
 assert.equal(await GR.settingsPanelUsable(page),false);
 assert.equal(await GR.openSettingsPanel(page,()=>{},1),true);
 assert.deepEqual(clicks,[[720,50]]);assert.equal(await GR.settingsPanelUsable(page),true);
 console.log('Actual Agent settings selector: grid Settings excluded, tune selected, ambiguous matches rejected, correct drawer verified.');
})().catch(error=>{console.error(error);process.exitCode=1;});
