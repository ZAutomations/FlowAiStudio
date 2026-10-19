// Restrict reference selection to the Images category in Flow's asset picker.
function categoryState(category){
 const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;};
 const labels=[...document.querySelectorAll('.side-nav-list-item-title')].filter(e=>visible(e)&&(e.textContent||'').trim()===category);
 if(labels.length!==1)return {found:false,why:labels.length?'multiple visible category rails':'category not visible'};
 const label=labels[0],item=label.closest('mat-list-item,button,[role="tab"],[role="option"],[role="listitem"],a')||label.parentElement;
 let selected=false,signals=false;
 for(let e=label,n=0;e&&n<12;e=e.parentElement,n++){
  for(const attr of ['aria-selected','aria-current','aria-pressed','aria-checked']){
   if(e.hasAttribute(attr)){signals=true;const v=e.getAttribute(attr);if(v==='true'||v==='page')selected=true;}
  }
  if(/(?:^|[\s_-])(?:active|selected|activated)(?:$|[\s_-])/i.test(String(e.className||'')))selected=true;
  if(e===item)break;
 }
 const r=item.getBoundingClientRect();
 return {found:true,selected,x:r.x+r.width/2,y:r.y+r.height/2};
}
async function selectCategory(page,category,{log=()=>{},timeout=12000}={}){
 for(let attempt=0;attempt<3;attempt++){
  const before=await page.evaluate(categoryState,category);
  if(!before.found){
   if(attempt===2)throw Error(`Reference picker ${category} category was not found. No asset selected.`);
   await new Promise(resolve=>setTimeout(resolve,300));continue;
  }
  if(!before.selected)await page.mouse.click(before.x,before.y);
  try{await page.waitForFunction(categoryStateSelected,{timeout:Math.ceil(timeout/3)},category);break;}
  catch{
   if(attempt===2)throw Error(`Reference picker did not confirm ${category} is selected after 3 attempts. No asset selected.`);
   log(`Reference picker: rechecking ${category} selection (${attempt+2}/3).`);
  }
 }
 // The selected state above is the readiness signal; no extra fixed pause.
 log(`Reference picker: ${category} selected; videos excluded.`);
}
async function selectImages(page,opts){return selectCategory(page,'Images',opts);}
function categoryStateSelected(category){
 const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;};
 const labels=[...document.querySelectorAll('.side-nav-list-item-title')].filter(e=>visible(e)&&(e.textContent||'').trim()===category);
 if(labels.length!==1)return false;
 let signals=false;
 const item=labels[0].closest('mat-list-item,button,[role="tab"],[role="option"],[role="listitem"],a')||labels[0].parentElement;
 for(let e=labels[0],n=0;e&&n<12;e=e.parentElement,n++){
  for(const a of ['aria-selected','aria-current','aria-pressed','aria-checked'])if(e.hasAttribute(a)){
   signals=true;const v=e.getAttribute(a);if(v==='true'||v==='page')return true;
  }
  if(/(?:^|[\s_-])(?:active|selected|activated)(?:$|[\s_-])/i.test(String(e.className||'')))return true;
  if(e===item)break;
 }
 let scope=labels[0].closest('mat-list-item,button,[role="tab"],[role="option"],[role="listitem"],a')||labels[0].parentElement;
 while(scope&&!scope.querySelector('button.asset-item,[role="option"],[class*="asset-card"]'))scope=scope.parentElement;
 const rows=scope?[...scope.querySelectorAll('button.asset-item,[role="option"],[class*="asset-card"]')].filter(visible):[];
 return !signals&&category==='Images'&&rows.length>0&&rows.every(e=>/\bImage\s*$/i.test(String(e.innerText||e.textContent||'').trim()));
}
async function focusReferenceSearch(page){
 await page.evaluate(()=>{
  const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;};
  const overlay=[...document.querySelectorAll('.cdk-overlay-pane')].find(e=>visible(e)&&e.querySelector('.side-nav-list-item-title'));
  const search=overlay&&[...overlay.querySelectorAll('input')].find(e=>visible(e)&&/search/i.test(`${e.placeholder||''} ${e.getAttribute('aria-label')||''}`));
  const editor=[...document.querySelectorAll('.ProseMirror[contenteditable="true"]')].find(visible);
  (search||editor)?.focus();
 });
}
function clickNamedAsset(name){
 const norm=s=>String(s||'').trim().replace(/\.(?:jpg|jpeg|png|webp)$/i,'').toLowerCase();
 const buttons=[...document.querySelectorAll('.cdk-overlay-pane button.asset-item')].filter(b=>b.getBoundingClientRect().width>0&&!b.disabled&&norm(b.querySelector('.asset-title')?.textContent||b.textContent)===norm(name));
 if(buttons.length!==1)return false;
 const b=buttons[0];
 if(b.getAttribute('aria-selected')!=='true'&&b.getAttribute('aria-pressed')!=='true'&&!/(?:^|\s)selected(?:\s|$)/.test(b.className))b.click();
 return true;
}
function selectionState(){
 const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;};
 const editor=[...document.querySelectorAll('.ProseMirror')].find(visible);
 const labels=[...(editor?.querySelectorAll('.mention-chip')||[])].map(e=>(e.innerText||e.textContent||'').trim());
 const chips=labels.length;
 const add=[...document.querySelectorAll('.cdk-overlay-pane button')].filter(b=>visible(b)&&/^add to prompt$/i.test((b.innerText||b.textContent||'').trim())&&!b.disabled&&b.getAttribute('aria-disabled')!=='true');
 return {chips,labels,canConfirm:add.length===1};
}
function clickAddToPrompt(){
 const buttons=[...document.querySelectorAll('.cdk-overlay-pane button')].filter(b=>b.getBoundingClientRect().width>0&&/^add to prompt$/i.test((b.innerText||b.textContent||'').trim())&&!b.disabled&&b.getAttribute('aria-disabled')!=='true');
 if(buttons.length!==1)return false;buttons[0].click();return true;
}
async function confirmSelection(page,{expected,name='',log=()=>{},timeout=90000}={}){
 if(page.bringToFront)await page.bringToFront();
 const key=s=>String(s||'').trim().replace(/\.(png|jpe?g|webp)$/i,'').toLowerCase();
 const complete=state=>state.chips===expected&&(!name||(state.labels||[]).filter(label=>key(label)===key(name)).length===1);
 const started=Date.now(),deadline=started+timeout;let confirmations=0,lastConfirm=0,reported=false,selections=0,lastSelection=started;
 do{
  const state=await page.evaluate(selectionState);
  if(complete(state))return;
  if(state.chips>expected)throw Error('Reference selection produced extra attachment chips. No generation submitted.');
  if(state.canConfirm&&confirmations<3&&(!lastConfirm||Date.now()-lastConfirm>=15000)){
   if(await page.evaluate(clickAddToPrompt)){
    confirmations++;lastConfirm=Date.now();log(confirmations===1?'Reference selection: Add to prompt confirmed.':'Reference selection still open; retrying its Add to prompt control once.');
   }
  }
  if(name&&!state.canConfirm&&state.chips<expected&&selections<3&&Date.now()-lastSelection>=15000){
   if(await page.evaluate(clickNamedAsset,name)){
    selections++;lastSelection=Date.now();log('Reference not attached yet; reselecting exact image '+name+' ('+selections+'/3).');
   }
  }
  if(!reported&&confirmations&&Date.now()-lastConfirm>3000){log('Waiting for Flow to finish attaching '+(name||'the selected reference')+'; no generation will be submitted before it is verified.');reported=true;}
  await new Promise(r=>setTimeout(r,100));
 }while(Date.now()<deadline);
 if(complete(await page.evaluate(selectionState)))return;
 throw Error(`Reference attachment did not confirm ${name||expected+' chip(s)'} within ${timeout/1000}s. No generation submitted.`);
}
module.exports={selectCategory,selectImages,categoryState,categoryStateSelected,focusReferenceSearch,clickNamedAsset,selectionState,confirmSelection};
