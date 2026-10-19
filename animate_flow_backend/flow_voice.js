/**
 * FLOW VOICES
 * ===========
 * Which voice a story is narrated in, and how to put it on a clip.
 *
 * Veo invents its own narrator when the prompt box names no voice, and it
 * invents a DIFFERENT one for every clip. Measured on a real film: the same
 * narrator read clip 1 in one timbre, clip 3 in another, and clip 5 sounded
 * like a third person. The preset already says which voice the film is
 * supposed to be in (`flow_voice` on the style), so the fix is to attach that
 * voice to every clip the way Agent Mode does - and the extend engine, which
 * generates the clips one at a time, never did.
 *
 * Three parts, all of them here so the two callers cannot drift apart:
 *
 *   presetVoices(id)        the voice(s) a preset asks for, from the style lists
 *   resolveFlowVoice(story)  the voice for a STORY: its own field, else its preset
 *   attachVoice(page, name)  the picker walk that actually puts it on the clip
 *
 * The picker walk was measured working in Agent Mode (agent_mode.js) and is
 * moved here unchanged - a synthetic el.click() selects the row but does not
 * arm the detail pane, so the "Add to prompt" button never appears; every press
 * below is a REAL mouse click at the element's centre.
 */

const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const STYLE_FILES = ['styles.json', 'genai_styles.json'];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The Flow voice asset(s) a preset asks for: one narrator, or one per character
// for a two-hander. Optional; empty means "let Veo choose".
function presetVoices(id) {
    if (!id) return [];
    for (const f of STYLE_FILES) {
        try {
            const db = JSON.parse(fs.readFileSync(path.join(HERE, f), 'utf8'));
            const p = (db.styles || []).find((x) => x.id === id || x.label === id);
            if (p) {
                if (Array.isArray(p.flow_voices)) return p.flow_voices.map(String).filter(Boolean);
                if (p.flow_voice) return [String(p.flow_voice)];
                return [];
            }
        } catch (e) { /* a missing optional list is fine */ }
    }
    return [];
}

// The voice a story is narrated in.
//
// The story's own field first - it is a fact about THIS film, and it survives
// the preset being renamed or re-voiced. Older stories have no such field, so
// the preset is looked up instead. Their `niche` holds the preset's LABEL
// (write_story.js writes `niche: p.label`), which is why every story written
// before this existed still resolves without being edited.
function resolveFlowVoice(story) {
    if (!story || typeof story !== 'object') return null;
    if (Array.isArray(story.flow_voices)) {
        const first = story.flow_voices.map(String).filter(Boolean)[0];
        if (first) return { name: first, source: 'the story' };
    }
    if (story.flow_voice) return { name: String(story.flow_voice), source: 'the story' };
    const key = story.style_id || story.preset || story.niche;
    const found = presetVoices(key).filter(Boolean)[0];
    if (found) return { name: found, source: `the preset "${key}"` };
    return null;
}

// Is that voice actually on the prompt box? An attached voice shows up there
// beside the prompt, as a chip or as an @mention - the same readback the
// ingredients use (refs_for_scene.js). Read rather than assumed: the whole
// point of attaching is that the clip is generated with it, and a walk that
// silently dropped the voice looks identical to one that worked.
async function voiceOnPromptBox(page, name, opts = {}) {
    const wait = opts.wait || sleep;
    try {
        for (let i = 0; i < 5; i++) {
            const held = await page.evaluate((want) => {
                const box = document.querySelector('.ProseMirror[contenteditable="true"]')
                    || [...document.querySelectorAll('[contenteditable="true"]')].pop();
                if (!box) return null;
                const key = String(want).toLowerCase().replace(/[^a-z0-9]/g, '');
                const chips = [...box.querySelectorAll('[class*=mention], [class*=chip], [class*=ingredient], [data-mention]')]
                    .map((el) => (el.innerText || el.textContent || ''))
                    .join(' ');
                const text = (box.innerText || box.textContent || '') + ' ' + chips;
                return text.toLowerCase().replace(/[^a-z0-9]/g, '').includes(key);
            }, name);
            if (held) return true;
            if (held === null) return false;   // no prompt box on screen at all
            await wait(700);
        }
    } catch (e) { /* an unanswered poll is not a verdict */ }
    return false;
}

// Attach a named voice from Flow's Voices library to the prompt box:
//   "+" (Add ingredients) -> Voices filter -> search the name -> pick the
//   asset-item -> "Add to prompt".
// Without this Veo invents its own narrator and the voice drifts clip to clip.
//
// Ported from agent_mode.js, where it is measured working. `log` and `wait` are
// injected so the caller's console and pacing are used.
async function attachVoice(page, name, opts = {}) {
    const log = opts.log || (() => {});
    const wait = opts.wait || sleep;
    const attempts = Number(opts.attempts) > 0 ? Number(opts.attempts) : 3;
    if (!name) return false;

    for (let attempt = 1; attempt <= attempts; attempt++) {
        await page.keyboard.press('Escape');
        await wait(700);
        const btnBox = await page.evaluate(() => {
            const b = [...document.querySelectorAll('button')].find((x) => !!x.querySelector('.add-menu-icon'))
                || document.querySelector('button[aria-label="Add ingredients to the prompt box"]');
            if (!b) return null;
            b.scrollIntoView({ block: 'center' });
            const r = b.getBoundingClientRect();
            return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
        });
        if (!btnBox) { log(`  voice attempt ${attempt}: no ingredients menu button`); await wait(1200); continue; }
        await page.mouse.click(btnBox.x, btnBox.y);
        await wait(2500);
        const menuOpen = await page.evaluate(() => !!document.querySelector('input[aria-label="Search assets"]'));
        if (!menuOpen) { log(`  voice attempt ${attempt}: ingredients menu did not open`); await wait(800); continue; }
        await page.evaluate(() => {
            const el = [...document.querySelectorAll('mat-list-item, [role="menuitem"], button, li, span')]
                .find((x) => /^voices$/i.test((x.innerText || '').trim()));
            if (el) el.click();
        });
        await wait(1300);
        const preCount = await page.evaluate(() => document.querySelectorAll('button.asset-item').length);
        log(`  (voice list shows ${preCount} item(s) before search)`);
        const wantedSrc = '\\b' + String(name).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b';
        const findItem = () => page.evaluate((src) => {
            const re = new RegExp(src, 'i');
            const el = [...document.querySelectorAll('button.asset-item')].find((x) => re.test(x.innerText || ''));
            if (!el) return null;
            el.scrollIntoView({ block: 'center' });
            const r = el.getBoundingClientRect();
            return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 42) };
        }, wantedSrc);
        // The voices list is short, so SCAN it first. The search box is fussy
        // about a full name and often says "No assets found" for an item that is
        // plainly in the list, so it is only the fallback.
        let item = await findItem();
        if (!item) {
            const query = String(name).slice(0, Math.max(3, Math.min(String(name).length, 4)));
            const inp = await page.evaluate(() => {
                // The top bar has input.search-input too, so match the aria-label
                // that only the assets picker uses.
                const i = document.querySelector('input[aria-label="Search assets"]')
                    || [...document.querySelectorAll('input')].find((x) => /search assets/i.test(x.getAttribute('placeholder') || ''));
                if (!i) return null;
                const r = i.getBoundingClientRect();
                return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
            });
            if (inp) {
                await page.mouse.click(inp.x, inp.y);
                await wait(300);
                await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
                await page.keyboard.press('Backspace');
                await page.keyboard.type(query, { delay: 60 });
                await wait(2200);
                item = await findItem();
            }
        }
        if (!item) {
            const info = await page.evaluate(() => ({
                items: [...document.querySelectorAll('button.asset-item')].map((x) => (x.innerText || '').replace(/voice_selection/i, '').replace(/\s+/g, ' ').trim()).slice(0, 20),
                searchVal: (document.querySelector('input[aria-label="Search assets"]') || {}).value,
                pane: (document.querySelector('.cdk-overlay-pane') || {}).innerText
                    ? document.querySelector('.cdk-overlay-pane').innerText.replace(/\n/g, ' | ').slice(0, 200) : null,
            }));
            log(`  voice attempt ${attempt}: no voice matched "${name}" | listed=${JSON.stringify(info.items)} searchVal=${JSON.stringify(info.searchVal)} pane=${JSON.stringify(info.pane)}`);
            await page.keyboard.press('Escape');
            await wait(900);
            continue;
        }
        // A REAL click: a synthetic .click() selects the row but does not arm the
        // detail pane, so the "Add to prompt" button never appears.
        await page.mouse.click(item.x, item.y);
        log(`  selected voice: ${item.text}`);
        await wait(2400);
        const addBtn = await page.evaluate(() => {
            const b = document.querySelector('[class*=detail-add-to]')
                || [...document.querySelectorAll('button')].find((x) => /add to prompt/i.test((x.innerText || '').trim()));
            if (!b) return null;
            const r = b.getBoundingClientRect();
            return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
        });
        let added = false;
        if (addBtn) { await page.mouse.click(addBtn.x, addBtn.y); added = true; }
        await wait(1500);
        await page.keyboard.press('Escape');
        await wait(800);
        log(`  voice "${name}" ${added ? 'added to the prompt' : 'selected, but Add-to-prompt not found'}`);
        if (!added) continue;
        // Pressed is not the same as landed - and only the readback can tell
        // them apart, because the button sits enabled and answers a click
        // whether or not the asset reaches the box.
        const on = await voiceOnPromptBox(page, name, { wait });
        if (on) return true;
        // Deliberately NOT retried. The press went in; a second attempt could
        // add the same voice twice, and a doubled voice asset is a worse
        // outcome than an honest "check this clip".
        log(`  voice "${name}" was pressed onto the prompt but is not visible there - NOT pressing it again`);
        return false;
    }
    log(`  could not attach voice "${name}" after ${attempts} attempts`);
    return false;
}

module.exports = { presetVoices, resolveFlowVoice, attachVoice, voiceOnPromptBox };
