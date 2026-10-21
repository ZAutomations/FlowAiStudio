'use strict';
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function waitForUploadIdle(page,{log=()=>{},timeout=180000,poll=1000,wait=sleep}={}) {
    const deadline=Date.now()+timeout;
    let stable=0;
    // Allow the upload UI to mount before testing for completion.
    await wait(2000);
    while(Date.now()<deadline){
        const busy=await page.evaluate(()=>{
            const visible=e=>!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
            return [...document.querySelectorAll('[role="progressbar"],mat-progress-bar,mat-progress-spinner,[aria-busy="true"]')].some(visible)
                || [...document.querySelectorAll('[role="dialog"],.cdk-overlay-pane')].some(e=>visible(e)&&/uploading|processing upload|upload in progress/i.test(e.innerText||''));
        });
        stable=busy?0:stable+1;
        if(stable>=3)return;
        if(busy)log('      waiting for reference upload/processing to finish...');
        await wait(poll);
    }
    throw Error('Reference upload is still processing after 180 seconds. No attachment or generation submitted. Retry when the connection recovers.');
}
async function waitForReference(check,{log=()=>{},name='',timeout=120000,poll=1500,wait=sleep}={}){
    const deadline=Date.now()+timeout;
    while(Date.now()<deadline){
        const found=await check();
        if(found)return found;
        log(`      waiting for uploaded reference ${name} to become selectable...`);
        await wait(poll);
    }
    throw Error(`Uploaded reference ${name} did not become selectable. No generation submitted; saved progress retained.`);
}
module.exports={waitForUploadIdle,waitForReference};
