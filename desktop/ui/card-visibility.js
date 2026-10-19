'use strict';
let cardPreferenceSave=Promise.resolve();
// Secondary Quick Process options and the full settings index start as a
// compact overview. Explicit saved choices always take precedence.
function defaultCardCollapsed(card){
 return (current==='quick'&&!!card.closest('.original-full')) ||
        (current==='settings'&&card.hasAttribute('data-group-panel'));
}
function isCardCollapsed(card){
 return state.preferences.collapsed_cards?.[card.dataset.collapseKey] ?? defaultCardCollapsed(card);
}
function applyCardVisibility(card){
 const button=card.querySelector(':scope > .card-collapse-heading > .card-visibility-toggle');if(!button)return;
 const searching=card.hasAttribute('data-group-panel')&&!!card.closest('.organized-settings')?.querySelector('#group-search')?.value.trim();
 const collapsed=isCardCollapsed(card)&&!searching;
 card.classList.toggle('is-collapsed',collapsed);
 button.textContent=collapsed?'Show ▾':'Hide ▴';button.setAttribute('aria-expanded',String(!collapsed));
 button.setAttribute('aria-label',(collapsed?'Show ':'Hide ')+card.dataset.collapseTitle);
}
function bindCardVisibility(){
 let tools=document.querySelector('#card-density-tools');
 if(!tools){
  tools=document.createElement('div');tools.id='card-density-tools';tools.className='actions';
  tools.setAttribute('aria-label','Card layout');
  for(const [label,collapsed] of [['Collapse cards',true],['Expand cards',false]]){
   const button=document.createElement('button');button.type='button';button.textContent=label;
   button.onclick=()=>run(async()=>{
    const cards=[...document.querySelectorAll('#content [data-collapse-key]')];
    const previous={...state.preferences.collapsed_cards};
    const patch=Object.fromEntries(cards.map(card=>[card.dataset.collapseKey,collapsed]));
    state.preferences.collapsed_cards={...previous,...patch};cards.forEach(applyCardVisibility);
    cardPreferenceSave=cardPreferenceSave.catch(()=>{}).then(()=>api('settings/preferences',{collapsed_cards:patch}));
    try{await cardPreferenceSave;}catch(error){state.preferences.collapsed_cards=previous;cards.forEach(applyCardVisibility);throw error;}
   });
   tools.append(button);
  }
  document.querySelector('.page-heading').append(tools);
 }
 const occurrences=new Map();
 document.querySelectorAll('#content .card, #content .workflow-section, main > .activity').forEach(card=>{
  if(card.dataset.collapseKey){applyCardVisibility(card);return;}
  let heading=card.querySelector(':scope > .group-panel-heading, :scope > .card-heading, :scope > .os-group-heading');
  const titleElement=heading?.querySelector('h2,h3')||card.querySelector(':scope > h2, :scope > h3');
  const title=titleElement?.textContent.trim()||(card.querySelector('#workflow-form')?'Processing':null);if(!title)return;
  if(!heading){heading=document.createElement('div');if(titleElement)heading.append(titleElement);else{const h=document.createElement('h3');h.textContent=title;heading.append(h);}card.prepend(heading);}
  heading.classList.add('card-collapse-heading');
  const scope=card.classList.contains('activity')?'global':card.closest('.os-preview-column')?'shared-preview':current;
  const name=scope+'|'+title,number=occurrences.get(name)||0;occurrences.set(name,number+1);
  card.dataset.collapseKey=name+'|'+number;card.dataset.collapseTitle=title;
  const body=document.createElement('div');body.className='collapsible-card-body';body.id='card-body-'+encodeURIComponent(card.dataset.collapseKey);
  for(const child of [...card.childNodes])if(child!==heading)body.append(child);
  card.append(body);
  const button=document.createElement('button');button.type='button';button.className='card-visibility-toggle';button.setAttribute('aria-controls',body.id);heading.append(button);
  button.onclick=()=>{
   const key=card.dataset.collapseKey;state.preferences.collapsed_cards??={};
   const previous=isCardCollapsed(card),collapsed=!previous;state.preferences.collapsed_cards[key]=collapsed;applyCardVisibility(card);
   cardPreferenceSave=cardPreferenceSave.catch(()=>{}).then(()=>api('settings/preferences',{collapsed_cards:{[key]:collapsed}}));
   run(async()=>{try{await cardPreferenceSave;}catch(error){if(state.preferences.collapsed_cards[key]===collapsed){state.preferences.collapsed_cards[key]=previous;applyCardVisibility(card);}throw error;}});
  };
  applyCardVisibility(card);
 });
}
