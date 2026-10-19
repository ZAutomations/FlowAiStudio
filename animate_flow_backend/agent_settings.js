const GR = require('./generate_refs');

// Runs in the page. Scope ratios to VIDEO so the reference-sheet ratio stays put.
function settingChoice({ kind, ratio, click }) {
    const visible = el => {
        if(!el || !el.getBoundingClientRect().width || !el.getBoundingClientRect().height)return false;
        if(el.checkVisibility && !el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}))return false;
        for(let e=el;e;e=e.parentElement){const s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}
        return true;
    };
    const heading = kind === 'confirm' ? /confirm before generating/i : (kind === 'imageRatio' || kind === 'imageCount') ? /image generation default/i : /video generation default/i;
    const section = [...document.querySelectorAll('.settings-section')]
        .find(el => visible(el) && heading.test(el.innerText || ''));
    if (!section) return false;
    const candidates = [...section.querySelectorAll('[role="radio"], mat-radio-button, button, label')];
    const target = candidates.find(el => {
        if (!visible(el)) return false;
        if (kind === 'imageCount') return (el.querySelector('.toggle-text')?.textContent || el.textContent || '').trim() === 'x1';
        if (kind === 'ratio' || kind === 'imageRatio') return (el.querySelector('.toggle-text')?.textContent || '').trim() === ratio;
        const label = (el.querySelector('.radio-label')?.textContent || el.textContent || '').trim();
        return /^never\b/i.test(label) || /Agent will generate media and spend credits automatically/i.test(label);
    });
    if (!target) return false;
    const input = target.querySelector('input[type="radio"]')
        || (target.tagName === 'LABEL' && target.control);
    const selected = target.getAttribute('aria-checked') === 'true' || !!input?.checked
        || target.querySelector('[role="radio"][aria-checked="true"]') !== null;
    if (!selected && click) (input || target).click();
    return selected;
}

async function saveAndVerifyAgentSettings(page,{videoModel='',imageModel='Nano Banana Pro',ratio='Flow',log=()=>{}}={}){
    if(!await GR.clickSave(page))throw Error('A unique visible enabled Agent settings Save button was not found. Generation stopped.');
    await new Promise(resolve=>setTimeout(resolve,600));
    // Save can apply values while leaving this drawer open. Dismiss it, then
    // reopen and read values rather than using closure as proof of persistence.
    if(!await GR.closeSettings(page,6))throw Error('Could not dismiss Agent settings after Save. No generation submitted.');
    if(!await GR.openSettingsPanel(page))throw Error('Could not reopen saved Agent settings for verification. No generation submitted.');
    const image=await GR.readSectionModel(page,'image');
    if(GR.modelKey(image)!==GR.modelKey(imageModel))throw Error(`Saved image model is ${image||'unreadable'}, expected ${imageModel}. No generation submitted.`);
    if(videoModel && !/^(flow|auto|default|none)$/i.test(videoModel)){
        const video=await GR.readSectionModel(page,'video');
        if(GR.modelKey(video)!==GR.modelKey(videoModel))throw Error(`Saved video model is ${video||'unreadable'}, expected ${videoModel}. No generation submitted.`);
    }
    for(const kind of ['confirm','imageCount',...(ratio==='Flow'?[]:['ratio','imageRatio'])]){
        if(!await page.evaluate(settingChoice,{kind,ratio,click:false}))throw Error(`Saved Agent ${kind} setting did not persist. No generation submitted.`);
    }
    log('Verified saved Agent model, x1 image output, confirmation and aspect settings after reopening.');
    if(!await GR.closeSettings(page,6))throw Error('Verified settings, but the drawer could not be dismissed. No generation submitted.');
}

async function applyAgentSettings(page, { videoModel = '', imageModel = 'Nano Banana Pro', aspect = 'Flow', resolution = 'Flow', log = () => {} } = {}) {
    const ratio = String(aspect || 'Flow').trim();
    if (!['Flow', '16:9', '1:1', '9:16'].includes(ratio)) throw Error(`Unsupported video aspect ratio: ${ratio}`);
    if (!['Flow','360p','720p'].includes(resolution)) throw Error('Choose Flow, 360p or 720p for Agent resolution.');
    if (!await GR.openSettingsPanel(page)) throw Error('Could not open Agent settings. Generation stopped.');
    const imageResult = await GR.setSectionModel(page, 'image', imageModel);
    if (!imageResult.ok) throw Error(`Could not select image model: ${imageResult.why}`);
    if (videoModel && !/^(flow|auto|default|none)$/i.test(videoModel)) {
        const result = await GR.setSectionModel(page, 'video', videoModel);
        if (!result.ok) throw Error(`Could not select video model: ${result.why}`);
        log(`Video generation default: ${result.model}`);
    }
    // Animate batches contain still images as well as clips. Set both media ratios.
    if (ratio !== 'Flow') await GR.setPanelRatio(page, ratio);
    // Agent resolution is requested in the prompt; this drawer has no resolution control.
    for (const kind of ['confirm','imageCount', ...(ratio === 'Flow' ? [] : ['ratio','imageRatio'])]) {
        await page.evaluate(settingChoice, { kind, ratio, click: true });
        try {
            await page.waitForFunction(settingChoice, { timeout: 5000 }, { kind, ratio, click: false });
        } catch (_) {
            throw Error(`Could not verify ${kind==='confirm'?'confirmation Never':(kind==='imageRatio'?'image':'video')+' ratio '+ratio}. Generation stopped.`);
        }
    }
    await saveAndVerifyAgentSettings(page,{videoModel,imageModel,ratio,log});
    log(`Agent settings saved: image model ${imageModel}; image count x1; confirmation Never; video ratio ${ratio}; resolution instruction ${resolution} (prompt only).`);
}

module.exports = { applyAgentSettings, settingChoice, saveAndVerifyAgentSettings };
