'use strict';
const fs=require('fs'),crypto=require('crypto');
function fileHash(file){return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');}
function load(file){try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch{return {};}}
function cached(state,scope,ref){return !!ref.file&&state[scope]?.[ref.name]===fileHash(ref.file);}
function record(state,scope,refs){
 state[scope]=state[scope]||{};
 for(const ref of refs)if(ref.file)state[scope][ref.name]=fileHash(ref.file);
 return state;
}
function namedImagePresent(name){
 const key=s=>String(s||'').trim().replace(/\.(png|jpe?g|webp)$/i,'').toLowerCase();
 return [...document.querySelectorAll('flow-image-tile')].some(tile=>{
  const title=tile.querySelector('.footer-title')?.textContent||'';
  return key(title)===key(name)&&!!tile.querySelector('img[data-media-id]');
 });
}
module.exports={load,cached,record,namedImagePresent};
