'use strict';
let studioCastDocument=null,studioCastKind="studio";
function studioCastExecute(action,extra){return studioCastKind==="animate"?animateExecute(action,extra):studioExecute(action,extra);}
function bindStudioCast(kind="studio"){
 studioCastKind=kind;studioCastDocument=null;
 for(const id of ['studio-cast-dialog','studio-ready-dialog'])document.getElementById(id)?.remove();
 document.body.insertAdjacentHTML('beforeend',`<dialog id="studio-cast-dialog"><h2>Review cast, locations & scene references</h2><p class="help">Descriptions are proposed designs. Correct identities, aliases and period details. Tick only subjects visible in each scene. Narration stays unchanged.</p><div id="studio-cast-editor"></div><div class="actions"><button type="button" id="studio-cast-add">Add reference</button><button type="button" id="studio-cast-approve" class="primary">Approve reviewed cast</button><button type="button" data-cast-close>Close</button></div></dialog><dialog id="studio-ready-dialog"><h2>Import Ready Story</h2><p class="help">Copy the master prompt into ChatGPT with your full script. Paste its JSON response below. Import creates project/story files without an API writing call, then opens cast review. Use a new video for a new story.</p><label>Master prompt<textarea id="studio-ready-master" rows="9" readonly></textarea></label><button type="button" id="studio-ready-copy">Copy master prompt</button><label>Ready-story JSON<textarea id="studio-ready-json" rows="10" placeholder='{"version":1,"title":"...","script":"...","assets":[],"scenes":[]}'></textarea></label><div class="actions"><button type="button" id="studio-ready-import" class="primary">Import script to story files</button><button type="button" data-ready-close>Close</button></div></dialog>`);
 $('#studio-cast-review').onclick=()=>run(()=>studioCastRefresh($('#workflow-form').elements.project.value,true));
 $('#studio-ready-open').onclick=()=>run(async()=>{
  const p=values($('#workflow-form')),response=await api('studio/cast-review',{project:p.project||'.'});
  $('#studio-ready-master').value=response.master_prompt+'\nSelected style: '+p.style_name+'\nExtra style: '+(p.custom_style||'')+'\nDesign guidance: '+(p.reference_design||'')+'\nFULL ORIGINAL SCRIPT:\n'+p.script;
  if(studioCastKind==='animate'){const scenes=projectScenes.animate||[];if(scenes.length)$('#studio-ready-master').value+='\nEXISTING NUMBERED SCENES: keep their numbers and narration exactly unchanged.\n'+JSON.stringify(scenes.map((s,i)=>({scene:i+1,narration:s.narration})));}
  $('#studio-ready-dialog').showModal();
 });
 $('#studio-ready-copy').onclick=()=>run(async()=>{await navigator.clipboard.writeText($('#studio-ready-master').value);toast('Master prompt copied.');});
 $('#studio-ready-import').onclick=()=>run(async()=>{
  let data;try{data=JSON.parse($('#studio-ready-json').value.replace(/^```(?:json)?\s*|\s*```$/gi,''));}catch{throw Error('Paste valid complete JSON from the master prompt.');}
  if(typeof data.script!=='string'||!data.script.trim())throw Error('The ready story needs its full script field.');
  const form=$('#workflow-form');if(studioCastKind==='studio'&&form.elements.project.value)throw Error('Click New Video Project before importing a ready story.');
  if(data.title)form.elements.title.value=data.title;form.elements.script.value=data.script;form.elements.character_consistency.checked=true;
  await studioCastExecute('import-ready',{ready_story:data,auto_cast:true});$('#studio-ready-dialog').close();
 });
 $('#studio-cast-add').onclick=()=>{studioCastDocument=studioReadCastReview();let n=1;while(studioCastDocument.assets.some(a=>a.name==='Reference'+n))n++;studioCastDocument.assets.push({name:'Reference'+n,kind:'character',aliases:[],description:''});studioRenderCastReview();};
 $('#studio-cast-approve').onclick=()=>run(async()=>{const review=studioReadCastReview();await studioCastExecute('approve-cast',{cast_review:review,auto_cast:true});$('#studio-cast-dialog').close();});
 $('[data-cast-close]').onclick=()=>$('#studio-cast-dialog').close();$('[data-ready-close]').onclick=()=>$('#studio-ready-dialog').close();
}
async function studioCastRefresh(project,open=false){
 if(!project){if(open)throw Error('Parse Scenes or Analyze full script first.');return;}
 const response=await api('studio/cast-review',{project});
 if(current!==studioCastKind)return;
 const data=response.analysis,status=$('#studio-cast-status');
 if(!data){if(open)throw Error('Click Analyze full script first.');return;}
 if(status)status.textContent=`${data.approved?'Approved':'Review required'} · ${data.assets.length} references · ${data.scenes.length} scenes. ${data.approved?'Create references, then generate media / Build All.':'Review the proposed designs and scene assignments, then approve.'}`;
 studioCastDocument=data;
 if(open||!data.approved){studioRenderCastReview();if(!$('#studio-cast-dialog').open)$('#studio-cast-dialog').showModal();}
}
function studioReadCastReview(){
 const data=structuredClone(studioCastDocument);
 data.assets=[...document.querySelectorAll('[data-cast-asset]')].map(row=>({name:row.querySelector('[data-cast-name]').value.trim(),kind:row.querySelector('[data-cast-kind]').value,aliases:row.querySelector('[data-cast-aliases]').value.split(',').map(s=>s.trim()).filter(Boolean),description:row.querySelector('[data-cast-description]').value.trim()}));
 for(const row of document.querySelectorAll('[data-cast-scene]'))data.scenes[Number(row.dataset.castScene)].references=[...row.querySelectorAll('input:checked')].map(el=>el.value);
 return data;
}
function studioRenderCastReview(){
 const d=studioCastDocument,e=escapeHtml;
 $('#studio-cast-editor').innerHTML=`<h3>Characters & locations</h3><div class="cast-assets">${d.assets.map((a,i)=>`<section class="cast-asset" data-cast-asset="${i}"><label>Identifier<input data-cast-name value="${e(a.name)}"></label><label>Type<select data-cast-kind><option value="character" ${a.kind==='character'?'selected':''}>Character</option><option value="location" ${a.kind==='location'?'selected':''}>Location</option><option value="prop" ${a.kind==='prop'?'selected':''}>Prop / object</option></select></label><label>Aliases / roles<input data-cast-aliases value="${e(a.aliases.join(', '))}"></label><label>Identity / appearance / layout<textarea data-cast-description rows="4">${e(a.description)}</textarea></label><button type="button" data-cast-remove="${i}">Remove reference</button></section>`).join('')}</div><h3>Scene assignments</h3>${d.scenes.map((s,i)=>`<details class="cast-scene" data-cast-scene="${i}"><summary>Scene ${s.scene} · ${e(s.references.join(', ')||'No recurring references')}</summary><p>${e(s.narration)}</p><div class="cast-choices">${d.assets.map(a=>`<label><input type="checkbox" value="${e(a.name)}" ${s.references.includes(a.name)?'checked':''}> ${e(a.name)} (${a.kind})</label>`).join('')}</div></details>`).join('')}`;
 for(const button of document.querySelectorAll('[data-cast-remove]'))button.onclick=()=>{const next=studioReadCastReview(),index=Number(button.dataset.castRemove),name=next.assets[index].name;next.assets.splice(index,1);for(const s of next.scenes)s.references=s.references.filter(n=>n!==name);studioCastDocument=next;studioRenderCastReview();};
 for(const row of document.querySelectorAll('[data-cast-asset]')){
  const input=row.querySelector('[data-cast-name]');let old=input.value;
  input.addEventListener('change',()=>{const name=input.value.trim();for(const choice of document.querySelectorAll('[data-cast-scene] input'))if(choice.value===old){choice.value=name;choice.parentElement.lastChild.textContent=' '+name+' (reference)';}old=name;});
 }
}
