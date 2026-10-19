const {replaceNames}=require('./couple_names');
function enabled(p){return p.id==='fantasy-princess-relationship-advice';}
function cast(p,characters){
 if(!enabled(p))return characters;
 const typed=characters.map(c=>({...c,type:c.type||(/\b(frog|parrot|cat|dove|animal)\b/i.test(c.description||'')?'animal':'human')}));
 if(typed.length!==2||typed.filter(c=>c.type==='human').length!==1||typed.filter(c=>c.type==='animal').length!==1)throw Error('Fantasy preset requires one adult woman Lilly and one animal Pip.');
 const aliases=new Map(typed.map(c=>[c.name,c.type==='human'?'Lilly':'Pip']));
 return typed.map(c=>({...replaceNames(c,aliases),name:aliases.get(c.name),source_names:[...new Set([c.name,...(c.source_names||[])])]}));
}
function inputs(p,characters,meta,scenes){
 if(!enabled(p))return {meta,scenes};
 const aliases=new Map();for(const c of characters)for(const old of c.source_names||[])aliases.set(old,c.name);
 return {meta:{...replaceNames(meta,aliases),place_name:'garden'},scenes:replaceNames(scenes,aliases)};
}
module.exports={cast,inputs};
