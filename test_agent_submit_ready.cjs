const assert=require('node:assert/strict');
const {agentSubmitReady}=require('./animate_flow_backend/agent_submit_ready');
const el=(extra={})=>({getBoundingClientRect:()=>({width:100,height:30}),getAttribute:()=>null,classList:{contains:()=>false},...extra});
let panel=el(),submit=el(),chip=null;
global.document={querySelector:selector=>selector==='button.agent-mode-chip'?chip:null,
 querySelectorAll:selector=>selector.startsWith('.agent-panel')?(panel?[panel]:[]):[submit]};
assert.equal(agentSubmitReady(),true,'visible Agent panel works without old toggle');
submit.disabled=true;assert.equal(agentSubmitReady(),false);
submit.disabled=false;panel=null;assert.equal(agentSubmitReady(),false,'normal composer is insufficient');
chip=el({getAttribute:()=> 'true'});assert.equal(agentSubmitReady(),true);
chip=null;panel=el({getBoundingClientRect:()=>({width:0,height:0})});assert.equal(agentSubmitReady(),false);
console.log('Agent panel readiness checks passed.');
