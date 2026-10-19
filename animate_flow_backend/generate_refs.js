#!/usr/bin/env node
/**
 * GENERATE REFERENCE IMAGES IN FLOW  (Agent Mode pre-step)
 * =======================================================
 * Builds the reference images INSIDE the Flow project, so nothing is generated
 * by hand, saved to a folder, or renamed by hand. Then the normal Agent Mode run
 * just @-mentions the tiles this made (agent_mode.js --no-upload-refs), instead
 * of uploading local files.
 *
 * For each entry in the story's refs.json:
 *   1. Agent Mode OFF (a plain prompt makes an image; Agent Mode makes clips)
 *   2. select Image / 16:9 / Nano Banana Pro in the compact settings summary
 *   3. paste the sheet/plate prompt into the Flow prompt box
 *   4. click Start generation
 *   5. wait for a completed image; unusual activity waits 120s, max 2 retries
 *   6. open that tile's More options -> Rename -> type the simple name ("Maya",
 *      "Leo", "Apartment") -> Done
 * Then Agent Mode ON again.
 *
 * Selectors are pinned from a live probe (probe_refs.js), not guessed:
 *   agent chip  flow-agent-mode-toggle-chip, class "checked" when ON
 *   prompt box  .ProseMirror
 *   submit      button[aria-label="Start generation"]   (enabled once text is in)
 *   tiles       [class*=hover-overlay] holding button[aria-label="More options"],
 *               newest FIRST; the header's own More-options is excluded
 *   menu        button.mat-mdc-menu-item with span.item-text "Rename"
 *   rename      .rename-tile-overlay input.editable-text-input  +  button[aria-label="Done"]
 *
 * Requires: the automation browser (CDP) on a Flow PROJECT page. The chip is
 * handled here: this script checks the Agent Mode chip and turns it OFF first,
 * because while it is ON the image models are not offered at all and a sheet
 * prompt makes a clip instead. The chip is put back ON at the end for the film
 * run, unless --keep-agent-on.
 *
 * Usage:
 *   node generate_refs.js --story stories/<slug>
 *   node generate_refs.js --story stories/<slug> --only Maya
 *   node generate_refs.js --refs stories/<slug>/refs.json --cdp 9222
 *   node generate_refs.js --story stories/<slug> --keep-agent-on
 *
 * Flags:
 *   --story DIR|FILE  the story folder (reads refs.json) or the refs file itself
 *   --refs FILE       explicit refs.json
 *   --only NAME       generate just this one ref (retry a single failure)
 *   --cdp N           CDP port (default 9222)
 *   --wait N          seconds to wait for each image (default 180)
 *   --keep-agent-on   leave Agent Mode as it was instead of turning it back on
 *   --dry             list what it would do; touch nothing
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const RI = require('./reference_image_step.js');

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
function ts() { return new Date().toTimeString().slice(0, 8); }
function log(m) { console.log(`[${ts()}] ${m}`); }
// The console sink, kept under its own name so generateRefs() below can shadow
// `log` with its caller's sink without losing this one.
const moduleLog = log;

const argv = process.argv.slice(2);
function flag(name, def = null) {
    const i = argv.indexOf(name);
    if (i < 0) return def;
    const v = argv[i + 1];
    return (v && !v.startsWith('--')) ? v : true;
}
function num(name, def) {
    const n = parseInt(flag(name), 10);
    return Number.isFinite(n) && n > 0 ? n : def;
}
const CDP_PORT = String(flag('--cdp', '9222'));
const STORY = typeof flag('--story') === 'string' ? flag('--story') : '';
const REFS_FILE = typeof flag('--refs') === 'string' ? flag('--refs') : '';
const ONLY = typeof flag('--only') === 'string' ? flag('--only') : '';
const WAIT_S = num('--wait', 180);
const KEEP_AGENT = !!flag('--keep-agent-on', false);
const DRY = !!flag('--dry', false);

// ── refs.json ----------------------------------------------------------------
function refsPath() {
    if (REFS_FILE) return path.resolve(REFS_FILE);
    if (!STORY) return null;
    const p = path.resolve(STORY);
    if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
    return path.join(p, 'refs.json');
}
// Reading the refs is shared with the Scenes/Ingredients engine, so both routes
// cannot disagree about the cast or the place. See refs_for_scene.js.
const { readRefsFile, loadStoryRefs } = require('./refs_for_scene.js');

function loadRefs() {
    const f = refsPath();
    if (!f) { console.error('Give --story <folder> or --refs <refs.json>.'); process.exit(1); }
    if (REFS_FILE && !fs.existsSync(f)) {
        console.error(`No such refs file: ${f}`);
        process.exit(1);
    }
    let refs = [], source = '';
    if (fs.existsSync(f) && fs.statSync(f).isFile()) {
        refs = readRefsFile(f);
        source = path.basename(f);
    } else {
        // No refs.json: loadStoryRefs falls back to the story's
        // character_sheets.txt, which older stories have instead.
        const loaded = loadStoryRefs(path.dirname(f), null);
        refs = loaded.refs;
        source = loaded.source;
        log(`No refs.json - read ${source} instead.`);
    }
    if (!refs.length) {
        console.error(`No reference images found for ${f}.`);
        console.error('Write the story first (`node write_story.js ...`), which writes refs.json.');
        process.exit(1);
    }
    if (ONLY) {
        const want = ONLY.toLowerCase();
        refs = refs.filter((r) => String(r.name || '').toLowerCase() === want);
        if (!refs.length) { console.error(`--only ${ONLY} matches no ref in ${f}.`); process.exit(1); }
    }
    return refs;
}

// ── page helpers -------------------------------------------------------------
const MEDIA_MORE = `[...document.querySelectorAll('button[aria-label="More options"]')]
    .filter(b => !b.closest('.header-right-container, .header-desktop-main-row')
              && !!b.closest('[class*=hover-overlay]'))`;

async function countTiles(page) {
    return await page.evaluate((expr) => eval(expr).length, MEDIA_MORE);
}

// ---- the Agent Mode chip --------------------------------------------------
// This one chip decides whether a plain prompt makes an IMAGE or a CLIP. With it
// ON the image models are not even offered in the picker, so a sheet prompt
// submitted in that state comes back as a video - the "reference images came out
// as clips" failure. It is the whole switch, so this step reads it and turns it
// off before generating anything.
//
// Live DOM (Angular): the host carries class "checked" while ON, and the inner
// button carries "agent-mode-chip-checked" plus aria-pressed="true". Read the
// class AND the attribute, so a change to either binding still reads correctly.
// Returns null when the chip is not on the page at all (not a project page).
async function agentOn(page) {
    return await page.evaluate(() => {
        const host = document.querySelector('flow-agent-mode-toggle-chip');
        if (!host) return null;
        if (/checked/.test(String(host.className))) return true;
        const b = host.querySelector('button.agent-mode-chip') || host.querySelector('button');
        if (!b) return null;
        if (b.getAttribute('aria-pressed') === 'true') return true;
        return /agent-mode-chip-checked/.test(String(b.className));
    });
}

async function setAgent(page, want) {
    const now = await agentOn(page);
    // Current project-home builds can omit the Agent chip entirely while the
    // compact Image/Video settings remain available. An absent chip cannot be
    // switched on, so it is a valid Agent-off state for reference/Ingredients
    // generation. Turning Agent on still requires the actual control.
    if (now === null) return want
        ? { ok: false, changed: false, why: 'the Agent chip is not on the page' }
        : { ok: true, changed: false, why: 'Agent chip absent; treated as off' };
    if (now === want) return { ok: true, changed: false, why: 'already there' };
    const clicked = await page.evaluate(() => {
        const host = document.querySelector('flow-agent-mode-toggle-chip');
        const b = host && (host.querySelector('button.agent-mode-chip') || host.querySelector('button'));
        if (!b) return false;
        b.click();
        return true;
    });
    if (!clicked) return { ok: false, changed: false, why: 'the chip button could not be clicked' };
    // Angular sets the class after the click, so poll for the new state rather
    // than sleeping a fixed time and assuming it took.
    for (let i = 0; i < 12; i++) {
        await wait(500);
        if (await agentOn(page) === want) return { ok: true, changed: true, why: 'clicked' };
    }
    return { ok: false, changed: true, why: `clicked, but it did not turn ${want ? 'ON' : 'OFF'}` };
}
// Is the Settings panel actually on screen? Presence in the DOM is not the same
// thing - a closed panel's nodes can linger, and a hidden panel would then read
// as open forever.
async function settingsPanelOpen(page) {
    return await page.evaluate(() => {
        return [...document.querySelectorAll('.settings-content, .settings-section')].some(el=>{
            const r=el.getBoundingClientRect();
            if(!r.width || !r.height)return false;
            // Angular retains a translated drawer in the DOM after Save.
            // Nonzero dimensions alone do not mean it is still on screen.
            if(typeof innerWidth!=='undefined' && (r.right<=0 || r.left>=innerWidth))return false;
            if(typeof innerHeight!=='undefined' && (r.bottom<=0 || r.top>=innerHeight))return false;
            if(el.checkVisibility && !el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}))return false;
            for(let e=el;e;e=e.parentElement){
                const style=getComputedStyle(e);
                if(style.display==='none' || style.visibility==='hidden' || Number(style.opacity)===0)return false;
            }
            return true;
        });
    });
}

// Is the FULL Settings panel open - the one with the generation-default
// sections and its Save button?
//
// `settingsPanelOpen` above answers the weaker question "are any of this
// panel's nodes on screen", which is all that closing it needs. Opening it
// needs the stronger one. The compact "Settings trigger" summary opens a quick
// view that carries no generation-default sections and no Save button, and
// reporting THAT as success is worse than reporting failure: the caller then
// reads the model rows, finds none, sets nothing, and walks away leaving the
// view sitting over the prompt bar - which is the state that keeps Start
// generation disabled. Save is also this drawer's only way out, so a panel
// without one must not be entered at all.
async function settingsPanelUsable(page) {
    return await page.evaluate(() => {
        const visible=el=>{
            const r=el.getBoundingClientRect();if(!r.width||!r.height)return false;
            if(el.checkVisibility&&!el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}))return false;
            for(let e=el;e;e=e.parentElement){const s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}
            return true;
        };
        const sections=[...document.querySelectorAll('.settings-section')].filter(visible);
        return sections.some(s=>/video generation default/i.test(s.innerText||''))
            && sections.some(s=>/confirm before generating/i.test(s.innerText||''))
            && [...document.querySelectorAll('.settings-save-button')].filter(visible).length===1;
    });
}

// Both the main grid and Agent use aria-label="Settings". Only the Agent's
// action button has the tune icon. Never fall back to the grid settings_2 icon.
function agentSettingsTrigger(){
    const visible=el=>{
        const r=el.getBoundingClientRect();if(!r.width||!r.height||el.disabled)return false;
        if(el.checkVisibility&&!el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}))return false;
        for(let e=el;e;e=e.parentElement){const s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}
        return true;
    };
    const buttons=[...document.querySelectorAll('button')].filter(b=>visible(b)
        && [...b.querySelectorAll('mat-icon')].some(icon=>(icon.textContent||'').trim()==='tune')
        && (b.classList.contains('agent-action-button') || b.closest('.agent-panel-wrapper,.agent-panel-prompt-box')));
    if(buttons.length!==1)return {ok:false,reason:buttons.length?'ambiguous Agent tune buttons':'Agent tune button not visible'};
    const r=buttons[0].getBoundingClientRect();
    return {ok:true,x:r.x+r.width/2,y:r.y+r.height/2,label:'Agent Settings (tune)'};
}

// The tune button ("Settings") opens the full Settings panel, which holds the
// Image and Video generation defaults. We read the image default to confirm the
// sheets will be images (Nano Banana) and not clips.
//
// Two different buttons carry a settings label and which one exists depends on
// the page state: the tune button ("Settings"), and a compact "Settings trigger"
// summary that is display:none on a fresh project. A run with Agent Mode off was
// seen with only "Settings trigger" present, so matching "Settings" exactly left
// the panel unopenable and - because the caller is `if (await openSettingsPanel)`
// - silently skipped the whole settings block. Try both labels and take the one
// that is actually visible: clicking a hidden button dispatches an event Angular
// ignores, which looks exactly like the panel refusing to open.
//
// Success means the USABLE panel, not just its container - see
// settingsPanelUsable above for why that distinction matters.
async function openSettingsPanel(page, say = moduleLog, seconds = 12) {
    const budget = Number(seconds) > 0 ? Number(seconds) : 12;
    for (let i = 1; i <= 3; i++) {
        if(await settingsPanelUsable(page))return true;
        const clicked = await page.evaluate(agentSettingsTrigger);
        if (!clicked.ok) {
            say(`  Agent settings: ${clicked.reason} (attempt ${i}/3). Main-page settings excluded.`);
            await wait(1500);
            continue;
        }
        await page.mouse.click(clicked.x,clicked.y);
        say('  Opening Agent settings using its tune button.');
        // Poll for the usable panel rather than waiting a fixed 2.2s: the
        // drawer mounts its contents a moment after its container, so a single
        // fixed read can catch a working panel mid-mount and call it empty.
        //
        // Wait WHILE THE PANEL IS UP, and only give up on it once it has stopped
        // changing. The old version polled a flat 8 seconds and then pressed
        // Escape regardless - so a drawer that was open on screen but still
        // short of its Save button got closed by us and re-opened, and the run
        // read as "it opens the settings and then does nothing ... then 15 to 20
        // seconds later it does the same thing and this time it works". Nothing
        // was logged either way, so the second open was the only evidence the
        // first had happened at all.
        const t0 = Date.now();
        let lastWhy = '';
        while ((Date.now() - t0) / 1000 < budget) {
            await wait(400);
            if (await settingsPanelUsable(page)) {
                if (i > 1) say(`  settings: opened on attempt ${i} (clicked "${clicked.label}")`);
                return true;
            }
            const why = await page.evaluate(() => {
                const el = document.querySelector('.settings-content, .settings-section');
                if (!el) return 'not-on-screen';
                const r = el.getBoundingClientRect();
                if (!r.width && !r.height) return 'not-on-screen';
                const hasSave = !!document.querySelector('.settings-save-button')
                    || [...document.querySelectorAll('button')].some((b) => {
                        const src = b.querySelector('.mdc-button__label') || b;
                        const c = src.cloneNode(true);
                        c.querySelectorAll('mat-icon').forEach((x) => x.remove());
                        return /^save$/i.test((c.innerText || c.textContent || '').replace(/\s+/g, ' ').trim());
                    });
                return hasSave ? 'usable' : 'open-without-save';
            });
            if (why !== lastWhy) lastWhy = why;
        }
        // Say what actually happened. A silent retry is indistinguishable from a
        // button that did nothing, which is what made this cost a run.
        if (lastWhy === 'open-without-save') {
            say(`  settings: a panel opened (clicked "${clicked.label}") but it has no Save`);
            say('  button - that is the compact view, not the generation defaults. Backing out.');
        } else if (lastWhy === 'not-on-screen') {
            say(`  settings: clicking "${clicked.label}" opened nothing (attempt ${i}/3)`);
        } else {
            say(`  settings: the panel went unused for ${budget}s (attempt ${i}/3) - backing out`);
        }
        // Whatever opened is not the panel we came for. Back out the way that
        // has always worked, rather than leaving it up for the caller to trip
        // over.
        await page.keyboard.press('Escape');
        await wait(700);
    }
    return false;
}
// ---- the model dropdown in a "generation default" section ------------------
// Each generation-default section holds a Material dropdown: a button showing
// the current model with an arrow_drop_down icon at its end, and a menu of
// <span class="label"> items. The Image and the Video section each have one, so
// the trigger is always looked for INSIDE the named section - matching on the
// arrow alone would pick whichever section happened to come first, and setting
// the video model on the image row is a silent, expensive mistake.
//
// Icon ligatures ("arrow_drop_down", "crop_16_9") render as text, so a button's
// innerText is not its model name. Strip the icons rather than pattern-matching
// them away, so an icon Flow adds later does not quietly join the name.
const SECTION_OF = { image: 'image generation default', video: 'video generation default' };

// Flow also names both pickers outright, which is exact where the section scan
// has to infer: <button class="... video-model-picker-button" aria-label="Video
// generation default model">. Preferred when present, because it cannot pick the
// wrong row no matter how the section is laid out; the scan below is the
// fallback for a build without them.
//
// Both the class and the aria-label are matched because only the pair was
// verified live, and either could change independently.
const PICKER_OF = {
    image: '.image-model-picker-button, button[aria-label="Image generation default model"]',
    video: '.video-model-picker-button, button[aria-label="Video generation default model"]',
};

// Compare model names loosely: "Veo 3.1 - Fast" and "veo3.1-fast" are the same
// model, and the menu is not obliged to spell it the way the GUI does.
const modelKey = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');

async function readSectionModel(page, which) {
    return await page.evaluate(({ heading, picker }) => {
        const strip = (el) => {
            const src = el.querySelector('.mdc-button__label') || el;
            const c = src.cloneNode(true);
            c.querySelectorAll('mat-icon').forEach((i) => i.remove());
            return (c.innerText || c.textContent || '').replace(/\s+/g, ' ').trim();
        };
        const visible=el=>{
            const r=el.getBoundingClientRect();if(!r.width||!r.height)return false;
            if(el.checkVisibility&&!el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}))return false;
            for(let e=el;e;e=e.parentElement){const s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}
            return true;
        };
        const direct = [...document.querySelectorAll(picker)].find(visible);
        if (direct) return strip(direct) || null;
        const sec = [...document.querySelectorAll('.settings-section')]
            .find((s) => visible(s) && new RegExp(heading, 'i').test(s.innerText || ''));
        if (!sec) return null;
        const trig = [...sec.querySelectorAll('button')].find((b) =>
            [...b.querySelectorAll('mat-icon')].some((i) => /arrow_drop_down/.test(i.textContent || '')));
        // No arrow icon found: fall back to any button naming a model, which is
        // how this read the row before the dropdown shape was known.
        if (!trig) {
            return [...sec.querySelectorAll('button')]
                .map(strip)
                .find((t) => /nano|imagen|banana|veo|omni|flash/i.test(t)) || null;
        }
        return strip(trig) || null;
    }, { heading: SECTION_OF[which], picker: PICKER_OF[which] });
}
// Read just the model row under "Image generation default".
const readImageModel = (page) => readSectionModel(page, 'image');
const readVideoModel = (page) => readSectionModel(page, 'video');
const looksImageModel = (m) => /nano|imagen|banana/i.test(String(m));

// Pick a model in one of those dropdowns -> { ok, changed, why, model }.
// The menu renders in a CDK overlay outside the settings panel, so the item is
// searched for document-wide. The row is re-read afterwards rather than assumed:
// a click that lands nowhere leaves the old model in place, and generating a
// whole film on the wrong model is exactly what this is here to prevent.
async function setSectionModel(page, which, want) {
    const heading = SECTION_OF[which];
    const now = await readSectionModel(page, which);
    if (now && modelKey(now) === modelKey(want)) {
        return { ok: true, changed: false, why: 'already set', model: now };
    }
    const opened = await page.evaluate(({ h, picker }) => {
        // The named picker first - it cannot be the other section's dropdown.
        const direct = document.querySelector(picker);
        if (direct) { direct.click(); return true; }
        const sec = [...document.querySelectorAll('.settings-section')]
            .find((s) => new RegExp(h, 'i').test(s.innerText || ''));
        if (!sec) return false;
        const trig = [...sec.querySelectorAll('button')].find((b) =>
            [...b.querySelectorAll('mat-icon')].some((i) => /arrow_drop_down/.test(i.textContent || '')));
        if (!trig) return false;
        trig.click();
        return true;
    }, { h: heading, picker: PICKER_OF[which] });
    if (!opened) return { ok: false, changed: false, why: `no model dropdown in the ${which} section` };

    await wait(1200);
    const picked = await page.evaluate((name) => {
        const key = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        const want = key(name);
        const items = [...document.querySelectorAll('.cdk-overlay-pane span.label, ' +
            '.cdk-overlay-pane [role="option"], mat-option, [role="listbox"] [role="option"]')];
        const text = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
        // Exact on the loose key first: "Veo 3.1 - Lite" must not win over
        // "Veo 3.1 - Lite [Lower Priority]" just by being shorter.
        const hit = items.find((el) => key(text(el)) === want)
            || items.find((el) => key(text(el)).startsWith(want));
        if (!hit) return false;
        const clickable = hit.closest('[role="option"], mat-option, button, li') || hit;
        clickable.click();
        return true;
    }, want);
    if (!picked) {
        await page.keyboard.press('Escape');
        await wait(500);
        return { ok: false, changed: false, why: `"${want}" is not in the ${which} model menu` };
    }

    await wait(900);
    const after = await readSectionModel(page, which);
    if (modelKey(after) !== modelKey(want)) {
        return { ok: false, changed: true, why: `clicked "${want}" but the row reads "${after}"`, model: after };
    }
    return { ok: true, changed: true, why: 'picked', model: after };
}
// Set the aspect ratio in the two "generation default" sections of the open
// Settings panel, then Save. This is what actually makes the project generate
// in the batch's ratio - the prompt alone cannot change Flow's own setting.
async function setPanelRatio(page, ratio) {
    return await page.evaluate((r) => {
        const want = String(r).replace(/\s/g, '');
        let clicks = 0;
        for (const sec of document.querySelectorAll('.settings-section')) {
            if (!/image generation default|video generation default/i.test(sec.innerText || '')) continue;
            const target = [...sec.querySelectorAll('[role="radio"], button')]
                .find((el) => (el.innerText || '').replace(/\s+/g, '').includes(want));
            if (target && target.getAttribute('aria-checked') !== 'true') { target.click(); clicks++; }
        }
        return clicks;
    }, ratio);
}
async function clickSave(page) {
    const point = await page.evaluate(() => {
        // Read the label span rather than the button's own text: Material renders
        // an icon's ligature ("check", "save") as text, so a button carrying one
        // would read "checkSave" and an exact match on "Save" would miss it. The
        // live button is <button class="settings-save-button"><span
        // class="mdc-button__label"> Save </span></button> - the padding is why
        // the comparison trims.
        const text = (el) => {
            const src = el.querySelector('.mdc-button__label') || el;
            const c = src.cloneNode(true);
            c.querySelectorAll('mat-icon').forEach((i) => i.remove());
            return (c.innerText || c.textContent || '').replace(/\s+/g, ' ').trim();
        };
        const visible=el=>{
            const r=el.getBoundingClientRect();
            if(!r.width || !r.height || el.disabled || el.getAttribute('aria-disabled')==='true')return false;
            if(el.checkVisibility && !el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}))return false;
            for(let e=el;e;e=e.parentElement){const s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}
            return true;
        };
        const preferred=[...document.querySelectorAll('.settings-save-button')].filter(visible);
        const fallback=[...document.querySelectorAll('button')].filter(x=>visible(x)&&/^save$/i.test(text(x))&&x.closest('.settings-content,[role="dialog"],mat-dialog-container'));
        const choices=preferred.length?preferred:fallback;
        if(choices.length!==1)return null;
        const r=choices[0].getBoundingClientRect();
        return {x:r.x+r.width/2,y:r.y+r.height/2};
    });
    if(!point)return false;
    await page.mouse.click(point.x,point.y);
    return true;
}
// "Confirm before generating: Always | Never". A fresh project (or a new account)
// comes up on "Always", which makes the agent STOP for a manual approval on
// every project. Set it to "Never" so generation is unattended.
async function setConfirmNever(page) {
    return await page.evaluate(() => {
        const sec = [...document.querySelectorAll('.settings-section')]
            .find((s) => /confirm before generating/i.test(s.innerText || ''));
        if (!sec) return 'no-section';
        // The option is a container holding the label AND a subtext ("Agent will
        // generate media and spend credits automatically"), so the whole
        // element's text is never just "Never". Read the label span when there is
        // one; \b rather than $ because the subtext may still be inside it.
        const never = [...sec.querySelectorAll('[role="radio"], button')].find((el) => {
            const lbl = el.querySelector('.radio-label');
            const t = ((lbl ? lbl.innerText : el.innerText) || '').trim();
            return /^never\b/i.test(t);
        });
        if (!never) return 'no-never';
        if (never.getAttribute('aria-checked') === 'true') return 'already';
        never.click();
        return 'clicked';
    });
}
// The panel leaves a backdrop that keeps Start generation disabled until it is
// really gone, so wait it out rather than assuming one Escape is enough.
// Dismiss the Settings panel WITHOUT writing anything.
//
// This panel is a drawer inside the agent panel - <flow-agent-panel> >
// .agent-panel-content > flow-settings-view > .container > .settings-content -
// and on the build it was measured on it has exactly ONE way out: Save.
//
// Save COMMITS, so closing is a write. It is the project's own settings being
// written back, so it is a no-op when nothing was changed - but it is still a
// write, and the way to get the drawer out of the way of the prompt bar.
//
// Save is TRIED FIRST, and Escape is kept as the fallback. That order matters:
// a build can show a settings view with no Save button in it at all, and then
// Save-only closing reports failure every time and leaves the drawer up - which
// is exactly the state that keeps Start generation disabled, so every ref after
// it fails with the prompt sitting in the box. Escape and a click on empty
// space are what closed this drawer before Save was used, and they still do.
async function closeSettings(page, seconds = 6) {
    if (!await settingsPanelOpen(page)) return true;
    await clickSave(page);
    // The drawer animates out, so poll for it instead of guessing a delay: a
    // fixed 1200ms was measured as too short and made this report failure on a
    // panel that was already on its way out.
    const t0 = Date.now();
    while ((Date.now() - t0) / 1000 < seconds) {
        await wait(300);
        if (!await settingsPanelOpen(page)) return true;
    }
    // Save did not do it - no Save button on this build, or it did not take.
    for (let i = 0; i < 4; i++) {
        await page.keyboard.press('Escape');
        await wait(800);
        if (!await settingsPanelOpen(page)) return true;
    }
    await page.mouse.click(5, 5);
    await wait(700);
    return !(await settingsPanelOpen(page));
}
// A freshly created project takes a moment to paint its prompt bar. Without
// this the very first settings click lands on nothing - which stopped a whole
// batch right after new_project.
async function waitForProjectReady(page, seconds = 45) {
    const t0 = Date.now();
    while ((Date.now() - t0) / 1000 < seconds) {
        const ready = await page.evaluate(() => !!(
            document.querySelector('button[aria-label="Settings"]')
            || document.querySelector('button[aria-label="Settings trigger"]')
            || document.querySelector('flow-base-prompt-box .ProseMirror, .ProseMirror')
        ));
        if (ready) return true;
        await wait(2000);
    }
    return false;
}
async function insertPrompt(page, text) {
    const ok = await page.evaluate(() => {
        const b = document.querySelector('flow-base-prompt-box .ProseMirror, .ProseMirror, [contenteditable="true"]');
        if (!b) return false;
        b.focus();
        return true;
    });
    if (!ok) { log('  no prompt box found'); return false; }
    await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
    await page.keyboard.press('Backspace');
    try {
        const client = (typeof page.createCDPSession === 'function')
            ? await page.createCDPSession() : await page.target().createCDPSession();
        await client.send('Input.insertText', { text });
        await client.detach().catch(() => {});
    } catch (e) {
        await page.keyboard.type(text, { delay: 2 });
    }
    await wait(700);
    // Verify it actually landed: after the Settings panel closes, focus can be
    // elsewhere, the insert goes nowhere, and Start generation stays disabled.
    const landed = await page.evaluate(() => {
        const b = document.querySelector('flow-base-prompt-box .ProseMirror, .ProseMirror, [contenteditable="true"]');
        return b ? (b.innerText || b.textContent || '').trim().length : 0;
    });
    if (!landed) { log('  prompt did not land in the box'); return false; }
    return true;
}
// Submit with a REAL mouse click at the button's centre - never el.click().
//
// el.click() dispatches a synthetic DOM event carrying isTrusted:false, and
// Flow's Angular handler ignores it. The click throws nothing, so this used to
// return ok:true - while the prompt sat in the box untouched. That is the exact
// signature of the failure: a run reports "0 made, N failed" and there is NO
// "could not submit" line anywhere in the log, because as far as this function
// was concerned the submit had worked.
//
// Measured live on this build: el.click() on the button -> the prompt box still
// holds its 282 characters after the full 180s wait and no tile ever appears.
// page.mouse.click() at the same coordinates -> the box clears within 7s and the
// tiles appear. The mention picker and the picker's own rows already click by
// coordinate for this same reason; the submit was the one left on the synthetic
// path.
async function clickSubmit(page) {
    const where = await page.evaluate(() => {
        const b = [...document.querySelectorAll('button')]
            .find((x) => /start generation/i.test(x.getAttribute('aria-label') || ''));
        if (!b) return { ok: false, why: 'no Start generation button' };
        if (b.disabled || String(b.className).includes('disabled')) return { ok: false, why: 'Start generation is disabled' };
        const r = b.getBoundingClientRect();
        if (!r.width || !r.height) return { ok: false, why: 'Start generation is not on screen' };
        return { ok: true, cx: Math.round(r.x + r.width / 2), cy: Math.round(r.y + r.height / 2) };
    });
    if (!where.ok) return where;
    await page.mouse.click(where.cx, where.cy);
    return { ok: true };
}
async function waitForNewTile(page, before, seconds) {
    const t0 = Date.now();
    while ((Date.now() - t0) / 1000 < seconds) {
        const n = await countTiles(page);
        if (n > before) return n;
        await wait(3000);
    }
    return await countTiles(page);
}
// Read the on-screen name of tile `idx` (0 = newest). Hovering a tile swaps its
// label for action icons (favorite / redo / more_vert ...), so strip the icon
// ligature words and walk up until only real text is left.
//
// The name is NOT always in innerText. On the build this broke on, the tile's
// label is an <input class="editable-text-input"> - the same kind of field the
// rename box uses - and an input's text lives in .value, which innerText never
// sees. The read therefore came back null on every attempt, a rename that HAD
// committed was scored a failure, the same tile was renamed three more times,
// and the whole refs stage was thrown away with "0 made, 1 failed, of 1".
// Inputs and titles are read too, so "I cannot see a name" stops being treated
// as "the name is wrong".
//
// Action labels are not names: the tile's own More-options button carries
// aria-label="More options", which would otherwise be the first thing found.
const TILE_UI_LABEL = /^(more options|rename|done|cancel|favorite|favourite|redo|undo|download|share|delete|delete forever|edit|play|pause|expand|open|close|add|add to|flag|copy|tune|refresh)\b/i;
// Whether a rename attempt is to be believed, and on what evidence.
//
// `label` is what tileName could read back, `typed` is what the rename box
// actually held before Done, `closed` is whether the box then went away.
//
// The box is the authority. It is this process's own input, and a box that held
// the wanted name and then closed is a committed rename - whereas the tile's
// label is read from markup we do not control, and on the build this broke on
// it could not be read at all. Scoring an unreadable label as "the name is
// wrong" is what renamed one tile three times and threw the stage away.
//
// A label that AGREES is still the nicer confirmation, so it is used when it is
// there and named in the log. A label that disagrees is reported, not acted on:
// it is usually a stale render, and failing the batch over it costs the story,
// the project and the generated image to save a rename that already happened.
function renameVerdict({ label, typed, closed, want }) {
    const w = String(want || '').trim().toLowerCase();
    if (label && String(label).toLowerCase().includes(w)) return { ok: true, via: 'tile label' };
    if (closed && String(typed || '').trim().toLowerCase() === w) {
        return { ok: true, via: 'rename box', labelSays: label || null };
    }
    return { ok: false, via: null };
}
async function tileName(page, idx) {
    return await page.evaluate(({ expr, i }) => {
        const WORDS = ['play_circle', 'favorite', 'favourite', 'redo', 'undo', 'more_vert', 'edit',
            'download', 'delete', 'delete_forever', 'keyboard_return', 'expand', 'add_2', 'add',
            'tune', 'arrow_forward', 'article_spark', 'thumb_up', 'thumb_down', 'content_copy',
            'flag', 'volume_up', 'share', 'video_library', 'photo_library', 'motion_blur', 'image',
            'videocam', 'crop_free', 'crop_16_9', 'crop_9_16', 'crop_landscape', 'crop_square',
            'crop_portrait', 'close', 'home', 'search', 'filter_list', 'help', 'refresh', 'check', 'done'];
        const ICON = new RegExp('\\b(' + WORDS.join('|') + ')\\b', 'gi');
        const ANY = new RegExp(WORDS.join('|'), 'gi');
        const UI = /^(more options|rename|done|cancel|favorite|favourite|redo|undo|download|share|delete|delete forever|edit|play|pause|expand|open|close|add|add to|flag|copy|tune|refresh)\b/i;
        const more = eval(expr);
        const b = more[i];
        if (!b) return null;
        const clean = (s) => String(s || '').replace(ICON, ' ').replace(/\s+/g, ' ').trim();
        // Nothing but icon ligatures, run together with no separators between
        // them: Flow's hover actions come back as one word, "favoriteredom
        // ore_vert". Stripping on word boundaries cannot touch that, so it was
        // read as the tile's name and every rename was judged a failure. A real
        // name is never spelled entirely from these words, so a label that
        // disappears when they are removed anywhere is icons, not a name.
        const soup = (s) => !String(s || '').replace(ANY, '').replace(/[\s_]+/g, '').trim();
        const textsOf = (el) => {
            const out = [];
            const raw = String(el.innerText || el.textContent || '');
            // The soup test belongs to innerText alone: it is the only place the
            // hover ligatures appear. An input holds a real name, so a place
            // called "Home" must not be thrown away for spelling an icon word.
            if (raw && !soup(raw)) {
                const t = clean(raw);
                if (t && !UI.test(t)) out.push(t);
            }
            // The label is an input on some builds, and its text is in .value.
            for (const f of el.querySelectorAll('input:not([type=hidden]), textarea')) {
                const v = String(f.value || '').trim();
                if (v && !UI.test(v)) out.push(v);
            }
            for (const x of el.querySelectorAll('[title]')) {
                const v = String(x.getAttribute('title') || '').trim();
                if (v && !UI.test(v)) out.push(v);
            }
            return out;
        };
        let el = b.closest('[class*=hover-overlay], flow-image-tile, flow-video-tile');
        for (let k = 0; k < 6 && el; k++) {
            const t = textsOf(el)[0];
            if (t) return t;
            el = el.parentElement;
        }
        return null;
    }, { expr: MEDIA_MORE, i: idx });
}

// The rename box is its OWN overlay (.rename-tile-overlay). An earlier version
// queried the whole document for ".editable-text-input, input[aria-label=
// Editable text]" and matched the FIRST such input - which is another tile's
// inline name field. The typed text went there, Done committed the rename
// box's still-unchanged value, and the function returned ok:true regardless.
// So: scope every lookup to the overlay, and VERIFY the tile name took.
async function renameNewest(page, name, tileIndex = 0) {
    for (let attempt = 1; attempt <= 3; attempt++) {
        await page.keyboard.press('Escape');
        await wait(700);
        const opened = await page.evaluate(({ expr, index }) => {
            const more = eval(expr)[index];
            if (!more) return { ok: false, why: 'no media tile' };
            more.scrollIntoView({ block: 'center' });
            more.click();
            return { ok: true };
        }, { expr: MEDIA_MORE, index: tileIndex });
        if (!opened.ok) return opened;
        await wait(1800);
        const clicked = await page.evaluate(() => {
            const el = [...document.querySelectorAll('button.mat-mdc-menu-item, .item-text, [role="menuitem"]')]
                .find((x) => /^rename$/i.test((x.innerText || '').trim()));
            if (!el) return false;
            el.click();
            return true;
        });
        if (!clicked) { await page.keyboard.press('Escape'); return { ok: false, why: 'no Rename menu item' }; }
        await wait(2000);
        const focused = await page.evaluate(() => {
            const inp = document.querySelector('.rename-tile-overlay input.editable-text-input')
                || document.querySelector('.rename-tile-overlay input')
                || document.querySelector('.rename-tile-overlay [contenteditable="true"]')
                || document.querySelector('input.editable-text-input.editing');
            if (!inp) return false;
            inp.focus();
            return true;
        });
        if (!focused) { await page.keyboard.press('Escape'); return { ok: false, why: 'no rename input' }; }
        await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
        await page.keyboard.press('Backspace');
        await page.keyboard.type(name, { delay: 25 });
        await wait(700);
        // What the box actually holds, read BEFORE committing. This is the
        // rename's own value, so it does not depend on how the tile draws its
        // label - and on a tile whose label reads null it is the only evidence
        // there is that the rename went in.
        const typed = await page.evaluate(() => {
            const o = document.querySelector('.rename-tile-overlay');
            const inp = o && o.querySelector('input.editable-text-input, input');
            if (inp) return String(inp.value || '');
            const ce = o && o.querySelector('[contenteditable="true"]');
            return ce ? String(ce.innerText || ce.textContent || '') : '';
        });
        const clickedDone = await page.evaluate(() => {
            const b = document.querySelector('.rename-tile-overlay button[aria-label="Done"]')
                || [...document.querySelectorAll('button')]
                    .find((x) => /^done$/i.test(x.getAttribute('aria-label') || ''));
            if (!b) return false;
            b.click();
            return true;
        });
        if (!clickedDone) await page.keyboard.press('Enter');
        await wait(1700);
        const closed = await page.evaluate(() => !document.querySelector('.rename-tile-overlay'));
        const now = await tileName(page, tileIndex);
        const verdict = renameVerdict({ label: now, typed, closed, want: name });
        if (verdict.ok) return { ok: true, name: now || name, verified: verdict.via, labelSays: verdict.labelSays };
        log(`  rename attempt ${attempt} did not take (tile still "${now}", ` +
            `box held "${typed}", box ${closed ? 'closed' : 'still open'}) - retrying`);
    }
    return { ok: false, why: 'rename did not commit after 3 attempts' };
}

// ── main ---------------------------------------------------------------------
// ── the routine ──────────────────────────────────────────────────────────────
// Exported so the Scenes/Ingredients engine can make the sheets on a page it has
// already opened, in the project it is about to generate in - that is the whole
// port, only the caller differs. `page` must be a Flow PROJECT page.
// Returns { made, failed, total }.
async function generateRefs(page, refs, opts = {}) {
    refs = require('./saved_couple').applySavedRefs(refs,
        opts.savedCouple === undefined ? require('./saved_couple').loadSavedCouple('agent') : opts.savedCouple);
    // Shadowing `log` with the caller's sink; the body's log() calls need no
    // change for it.
    const log = opts.log || moduleLog;
    const waitS = opts.waitS || WAIT_S;
    const keepAgentOn = opts.keepAgentOn !== undefined ? opts.keepAgentOn : KEEP_AGENT;

    log(`${refs.length} reference image(s) to make:`);
    refs.forEach((r) => log(`  - ${r.name}  (${r.kind || 'ref'})`));
    if (!await waitForProjectReady(page)) log('warning: prompt bar is slow to appear - still trying.');

    // A plain prompt can still be in VIDEO mode with Agent off. Require both
    // the Agent chip and the compact Image controls to read back correctly.
    const prepare = async () => {
        const off = await setAgent(page, false);
        if (!off.ok) throw new Error(`Cannot prepare reference images: ${off.why}. Nothing submitted.`);
        await RI.configureReferenceImages(page, log);
    };

    let made = 0, failed = 0;
    for (const r of refs) {
        const name = String(r.name || '').trim();
        log(`\n[${made + failed + 1}/${refs.length}] ${name}`);
        if (r.localFile) {
            const uploaded = await require('./upload_saved_reference').uploadSavedReference(page, r, log);
            if (!uploaded.ok) throw Error(`Saved ${name} upload failed: ${uploaded.why}. No replacement character will be generated.`);
            made++;
            continue;
        }
        const result = await RI.withActivityWait(async () => {
            // Recheck before every sheet and retry, so a stale Video selection
            // never silently turns a character sheet into a video.
            await prepare();
            if (!await insertPrompt(page, String(r.prompt).trim())) {
                return { ok: false, why: 'Reference prompt did not land.' };
            }
            const before = await page.evaluate(RI.referenceState);
            let click = await clickSubmit(page);
            for (let a = 2; a <= 6 && !click.ok; a++) {
                await wait(5000);
                click = await clickSubmit(page);
            }
            if (!click.ok) return { ok: false, why: `Could not submit: ${click.why}` };
            log(`  generating image... (up to ${waitS}s)`);
            return RI.waitForReferenceImage(page, before, waitS);
        }, { log });
        if (!result.ok) {
            failed++;
            log(`  FAILED: ${result.why}`);
            // A persistent activity block applies to the session. Do not send
            // the next sheet (or next film) straight into the same restriction.
            if (result.blocked) return { made, failed, total: refs.length, blocked: true };
            continue;
        }
        log(`  completed image appeared; renaming to "${name}"`);
        const ren = await renameNewest(page, name, result.tileIndex);
        if (ren.ok) {
            made++;
            log(`  ok - tile renamed "${name}"${ren.verified ? ` (read back from the ${ren.verified})` : ''}`);
            // Worth saying out loud: the rename box is the authority, but if the
            // tile is still drawing the old label the later @mention has nothing
            // to match, and that is much easier to act on here than in the agent
            // step's "no tile named X".
            if (ren.labelSays) {
                log(`  note: the tile label still reads "${ren.labelSays}" - if the agent`);
                log(`  cannot find @${name} later, that label is why.`);
            }
        } else { failed++; log(`  generated, but rename failed: ${ren.why}`); }
    }

    // Hand the chip back in the state the film run needs. agent_mode.js turns
    // Agent Mode ON itself, but leaving it OFF here means the next thing to touch
    // this project starts from the wrong state. --keep-agent-on opts out.
    if (keepAgentOn) {
        log('(--keep-agent-on: leaving Agent Mode as it was.)');
    } else {
        const on = await setAgent(page, true);
        log(on.ok
            ? 'Agent Mode is ON again, ready for the film run.'
            : `WARNING: could not turn Agent Mode back ON (${on.why}) - agent_mode.js will retry.`);
    }
    log(`\nDone: ${made} made, ${failed} failed, of ${refs.length}.`);
    return { made, failed, total: refs.length };
}

// ── CLI ─────────────────────────────────────────────────────────────────────
if (require.main === module) (async () => {
    const couple = require('./saved_couple').loadSavedCouple('agent');
    if (couple && STORY) {
        const dir = fs.statSync(STORY).isDirectory() ? STORY : path.dirname(STORY);
        const storyFile = fs.readdirSync(dir).find(f => /_story\.json$/i.test(f));
        if (storyFile) require('./saved_couple').bindSavedStory(path.join(dir, storyFile), couple);
    }
    const refs = loadRefs();
    if (DRY) { log(`${refs.length} reference image(s) would be made - --dry: nothing generated.`); return; }

    let browser;
    try {
        browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${CDP_PORT}`, defaultViewport: null });
    } catch (e) {
        console.error(`Could not connect to Chrome on CDP port ${CDP_PORT}. Start the automation browser first.`);
        process.exit(1);
    }
    const { normalizeProjectUrl, selectAgentPage } = require('./flow_project');
    const requested = flag('--project-url');
    const target = requested ? normalizeProjectUrl(requested) : null;
    const { page } = await selectAgentPage(browser, target);
    if (!page) { console.error('No Flow PROJECT tab open (need /project/<id>).'); await browser.disconnect(); process.exit(1); }
    const home = target || normalizeProjectUrl(page.url());
    if (page.url() !== home) await page.goto(home, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.bringToFront();
    log(`Project: ${page.url()}`);

    const r = await generateRefs(page, refs, {
        waitS: WAIT_S, keepAgentOn: KEEP_AGENT,
    });
    log('Next: run agent_mode (or the MCP run_agent) with --no-upload-refs so it');
    log('@-mentions the tiles just made instead of uploading local files.');
    await browser.disconnect();
    process.exit(r.blocked ? 4 : r.failed ? 1 : 0);
})().catch((e) => { console.error('FAILED: ' + (e && e.message)); process.exit(1); });

module.exports = {
    // generateRefs is what the Scenes/Ingredients engine calls on a page it has
    // already opened - see the note above it. It was missing from this list, so
    // that route died on its first line with "generateRefs is not a function"
    // after the story, the project and the browser attach had all been paid for.
    generateRefs,
    refsPath, loadRefs, renameNewest, tileName, renameVerdict, agentOn, setAgent, clickSubmit,
    readSectionModel, readImageModel, readVideoModel, setSectionModel,
    setConfirmNever, modelKey, SECTION_OF, PICKER_OF,
    // The Settings-panel plumbing, so agent_mode.js can set the video model in
    // the same place and the same way this does.
    openSettingsPanel, closeSettings, settingsPanelOpen, clickSave, setPanelRatio,
    agentSettingsTrigger, settingsPanelUsable,
};
