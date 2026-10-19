const assert=require('node:assert/strict');
const {categoryState,categoryStateSelected,selectImages}=require('./animate_flow_backend/reference_picker_images');
const rect=()=>({x:20,y:30,width:100,height:40});
const item={className:'mat-mdc-list-item selected',getBoundingClientRect:rect,hasAttribute:()=>false,parentElement:null};
let parent=item;
for(let i=0;i<5;i++)parent={className:'wrapper',parentElement:parent,hasAttribute:()=>false};
const label={textContent:'Images',className:'side-nav-list-item-title',parentElement:parent,
    getBoundingClientRect:rect,hasAttribute:()=>false,closest:()=>item};
global.document={querySelectorAll:()=>[label]};
assert.equal(categoryState('Images').selected,true);
assert.equal(categoryStateSelected('Images'),true);
item.className='mat-mdc-list-item';item.hasAttribute=key=>key==='aria-selected';item.getAttribute=()=> 'false';
item.querySelector=()=>null;
assert.equal(categoryState('Images').selected,false);
assert.equal(categoryStateSelected('Images'),false);
(async()=>{
 const originalTimer=global.setTimeout;global.setTimeout=fn=>{fn();return 0;};
 try{
  let clicks=0,waits=0;
  const page={evaluate:async()=>({found:true,selected:false,x:70,y:50}),
   mouse:{click:async()=>{clicks++;}},waitForFunction:async()=>{if(++waits<2)throw Error('not ready');}};
  await selectImages(page);assert.equal(clicks,2);assert.equal(waits,2);
  page.waitForFunction=async()=>{throw Error('not selected');};
  await assert.rejects(()=>selectImages(page),/after 3 attempts.*No asset selected/);
 }finally{global.setTimeout=originalTimer;}
 console.log('Deep category selection, asynchronous retry, and fail-closed reference picker passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
