#!/usr/bin/env node
/**
 * FLOW AGENT MODE DRIVER  (separate from the ingredients/extend engine)
 * ======================================================================
 * Agent Mode is a DIFFERENT surface from the ingredients path:
 *
 *   ingredients path : needs the SCENE EDITOR  (/project/<id>/edit/<scene>)
 *                      -> one continuous timeline -> ffmpeg SPLIT into scenes
 *   Agent Mode       : lives in the PROJECT MAIN WINDOW (/project/<id>)
 *                      -> the agent plans a storyboard and emits clips
 *                      -> post-processing would be ffmpeg CONCAT, not split
 *
 * So this script deliberately does NOT reuse veo3_flow_new_ui.js. That engine
 * forces the editor open (ensureEditor) and would break Agent Mode. Nothing in
 * this file reads or modifies the ingredients path.
 *
 * Selectors below were taken from a live DOM probe (logs/agent_probe_*.json),
 * not guessed:
 *   flow-agent-mode-toggle-chip           wrapper, gets class "checked" when ON
 *   button.agent-mode-chip                the clickable toggle
 *   button[aria-label="Agent instructions"]   article_spark icon
 *   button[aria-label="Settings"]         tune icon, inside .agent-footer-actions
 *   flow-base-prompt-box .ProseMirror     the prompt editor
 *   button[aria-label="Start generation"] arrow_forward, disabled while empty
 *
 * WHAT WE HAVE NOT SEEN YET: the storyboard / approval UI, because nothing has
 * been submitted on this account yet. Rather than guess it, every run writes a
 * numbered DOM snapshot at each stage into logs/agent_run_<ts>/. The FIRST run
 * is therefore also the probe for the rest of the flow.
 *
 * MODEL LIMITS (stated by the agent itself, 2026-09-11) - prompt accordingly:
 *   - Veo 3.1 - Lite [Lower Priority] makes AT MOST 8 SECONDS PER CLIP. Asking for a
 *     single "15-second" video makes the agent refuse or re-plan, because no single
 *     clip on this model can be that long.
 *   - Veo 3.1 accepts AT MOST 3 REFERENCE IMAGES (R2V), so a cast of 2-3 is the
 *     ceiling. Each character contributes ONE image: the reference sheet, which
 *     shows that character from several angles in a single file.
 *   - One scene per clip; several distinct scenes cannot share one clip.
 *   So ask for "N separate clips, one per scene, up to 8 seconds each". Total length
 *   is the SUM of the clips - it is not something you request.
 *
 * Usage:
 *   node agent_mode.js --check
 *   node agent_mode.js --prompt "Create 3 separate clips, one per scene, using @Mia in every scene, up to 8 seconds each" --model "veo3.1 low priority"
 *   node agent_mode.js --prompt "..." --auto-approve --watch 600
 *
 * Flags:
 *   --cdp N          CDP port (default 9222)
 *   --prompt "..."   the Agent prompt. An "@Name" inside it is SPLIT OUT and
 *                    typed last, because typing it mid-sentence sends the rest
 *                    of the sentence into the picker as a search filter.
 *   --file story.txt the same thing, read from a file. Use this for FULL STORIES:
 *                    they are thousands of characters with line breaks, which
 *                    Windows cannot pass through --prompt without mangling.
 *                    Long prompts are pasted in one shot instead of typed.
 *   --mention Name   characters to reference, comma-separated for several:
 *                    --mention "Mia,Jon,Sara". Overrides any "@" in --prompt.
 *                    Any "@Name" already in --prompt is picked up automatically.
 *                    NOTE: Veo 3.1 accepts at most 3 reference images, so more
 *                    than 3 characters will be refused or silently dropped.
 *   --model "..."    appended as "Use ... for all clips." - Agent Mode takes the
 *                    model as plain English, e.g. --model "veo3.1 low priority".
 *                    This is the only way to reach the lower-priority model,
 *                    which is absent from the ingredients extend menu.
 *   --check          report state only; type and click nothing
 *   --settings       open the Agent settings menu and dump it (the "never ask"
 *                    confirmation toggle lives there), then stop
 *   --no-submit      type the prompt but do not click Start generation
 *   --auto-approve   click approval buttons the agent offers (SPENDS CREDITS)
 *   --paste          paste the prompt as one blob instead of real keystrokes
 *   --watch N        seconds to keep recording after submit (default 240)
 *   --refs <what>    character reference sheets to put in the project before the
 *                    prompt is typed, so "@name" can offer a raw IMAGE tile.
 *                    A story .json (reads character_references), a folder, or a
 *                    comma-separated list of images. THIS IS THE FIX FOR DRIFT:
 *                    an Image tile holds the cast across clips, a saved Flow
 *                    Character does not. See mention_target.js.
 *   --no-upload-refs do not upload; only prefer an Image tile if one is already
 *                    in the project.
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
// The "@" picker offers the same character as either a raw Image or a saved
// Flow Character, and that choice - not the prompt text - decides whether the
// cast holds across clips. See mention_target.js for the measurement.
const MT = require('./mention_target.js');
const W  = require('./write_story.js');
const { applyAgentSettings } = require('./agent_settings.js');
// The narrator's voice: which one a preset asks for, and the picker walk that
// attaches it. Shared with the extend engine, which now attaches the same voice
// to every clip - see flow_voice.js.
const { attachVoice: attachVoiceShared } = require('./flow_voice.js');

const wait = (ms) => new Promise(r => setTimeout(r, ms));

function ts() { return new Date().toTimeString().slice(0, 8); }
function log(msg) { console.log(`[${ts()}] ${msg}`); }
function banner(msg) { console.log(`\n${'='.repeat(70)}\n${msg}\n${'='.repeat(70)}`); }

// ---- args -----------------------------------------------------------------
const argv = process.argv.slice(2);
function flag(name, def = null) {
    const i = argv.indexOf(name);
    if (i < 0) return def;
    const v = argv[i + 1];
    return (v && !v.startsWith('--')) ? v : true;
}
const CDP_PORT   = flag('--cdp', '9222');
const CDP_URL    = `http://127.0.0.1:${CDP_PORT}`;
// A specific project to open before anything else. project_setup.js prints this
// URL, so a batch can give every film its own project instead of trusting
// whichever tab happens to be open.
const { normalizeProjectUrl, selectAgentPage } = require('./flow_project.js');
const PROJECT_URL = typeof flag('--project-url') === 'string' ? normalizeProjectUrl(flag('--project-url')) : '';
// The video model this project must generate with ("Veo 3.1 - Fast",
// "Omni 1.1 Flash", ...). Empty leaves Flow's own setting alone, which is what
// every run did before this existed.
const VIDEO_MODEL = typeof flag('--video-model') === 'string' ? flag('--video-model').trim() : '';

// A full story is thousands of characters with line breaks - Windows cannot pass
// that through --prompt "..." without mangling it. --file reads the story from a
// text file instead, which is the only sane way to submit long-form prompts.
const FILE_RAW   = flag('--file');
const FILE_BODY  = (typeof FILE_RAW === 'string')
    ? (fs.existsSync(FILE_RAW)
        ? fs.readFileSync(FILE_RAW, 'utf8').replace(/\r\n/g, '\n').trim()
        : `__MISSING__:${FILE_RAW}`)
    : null;
const PROMPT_RAW = flag('--prompt');
const PROMPT     = (typeof PROMPT_RAW === 'string')
    ? PROMPT_RAW
    : (FILE_BODY && !FILE_BODY.startsWith('__MISSING__') ? FILE_BODY : null);

// The "@" mention MUST be typed last. On the first live run the prompt was typed
// as one string, so everything after "@" - "Mia in every scene" - went into the
// picker as a search FILTER. It matched nothing ("No assets found."), the picker
// stayed open, and the prompt box was left truncated at "using @".
// So: split the mention out, type the plain text, then type "@Name" on its own.
const MENTION_RAW = flag('--mention');
// EVERY mention, not just the first. A scene with two or three characters needs
// one chip per character, and each has to be picked from the picker separately.
// DISTINCT, though: the prompt names the place in its own section, in the
// reminder line and in every scene, so a cast of three arrived as five "@" names
// and the same image was attached three times over. See MT.distinctMentions.
const MENTION_LIST = (typeof MENTION_RAW === 'string')
    ? MENTION_RAW.split(',').map(s => s.replace(/^@/, '').trim()).filter(Boolean)
    : (PROMPT ? [...PROMPT.matchAll(/@([A-Za-z0-9_.\-]+)/g)].map(m => m[1]) : []);
const MENTIONS = MT.distinctMentions(MENTION_LIST);

// Model choice in Agent Mode is PLAIN ENGLISH in the prompt - there is no menu.
// Confirmed live 2026-09-11: telling the agent "use veo3.1 low pirority to
// generate all clips" made it schedule every scene on
// "Veo 3.1 - Lite [Lower Priority]" - the very model the ingredients/extend path
// could NOT find in its extend menu (that path failed 12x with "Extend menu
// problem: undefined" because the plan does not offer it there).
const MODEL_RAW = flag('--model');
const MODEL_HINT = (typeof MODEL_RAW === 'string') ? MODEL_RAW : null;

const PROMPT_BASE = PROMPT
    // Keep the NAME as plain words where it belongs, and attach the chip at the
    // end. Dropping it entirely left "using in every scene", which reads badly.
    ? PROMPT.replace(/@([A-Za-z0-9_.\-]+)/g, '$1')
            .replace(/\s{2,}/g, ' ')
            .trim()
    : null;
const PROMPT_TEXT = (PROMPT_BASE && MODEL_HINT)
    ? `${PROMPT_BASE} Use ${MODEL_HINT} for all clips.`
    : PROMPT_BASE;
// Belt-and-braces policy pass: strip wording the video model refuses outright
// before it ever reaches the box. The writer already carries the rule; this
// catches a slip. Long prompts still paste, so the text is otherwise untouched.
const VIDEO_RESOLUTION = String(flag('--video-resolution', 'Flow') || 'Flow');
const SEND_TEXT = flag('--image-only',false) ? PROMPT_TEXT : PROMPT_TEXT == null ? null : require('./agent_video_contract').withSettings(W.sanitizeForPolicy(PROMPT_TEXT),{
    model:VIDEO_MODEL,resolution:VIDEO_RESOLUTION,seconds:Number(flag('--scene-seconds',8))||8,aspect:String(flag('--aspect','Flow')),
});
if (SEND_TEXT !== PROMPT_TEXT) log('Policy sanitizer adjusted the prompt before sending.');

// A long prompt must NOT be typed key by key - a 3000-character story at 45ms a
// character is 2+ minutes of keystrokes. Paste it in one shot instead. This is
// safe for the mention flow because the mention is typed separately in step 5b.
const LONG_PROMPT = !!(PROMPT_TEXT && PROMPT_TEXT.length > 400);
const CHECK_ONLY = !!flag('--check', false);
// Recovery mode for an interrupted Agent run. It never types or submits the
// story prompt; it only retries controls that are physically inside a failed
// media tile. Flow's conversation-level "Try again" repeats the whole request
// and creates duplicates, so that control must never be clicked here.
const RETRY_FAILED_ONLY = !!flag('--retry-failed-only', false);
const DO_SETTINGS= !!flag('--settings', false);
const NO_SUBMIT  = !!flag('--no-submit', false);
const AUTO_APPROVE = !!flag('--auto-approve', false);
const USE_PASTE  = !!flag('--paste', false);
const FLOW_CHARACTERS = !!flag('--flow-characters', false);
const WATCH_SECS = parseInt(flag('--watch', '240'), 10);
// Veo fails a clip now and then (most often "Audio generation failed"). After
// the first watch, click the Retry affordances and watch again - this many
// rounds - so a run does not hand back a film with holes in it. 0 disables.
const RETRY_ROUNDS = Math.max(0, parseInt(flag('--retry-rounds', '6'), 10));
const RETRY_WATCH = parseInt(flag('--retry-watch', '90'), 10);
// Expected clip count, read from the prompt ("Create N separate clips"). Used as
// a gate: a partial film must not be downloaded and joined as if it were whole.
let EXPECTED_CLIPS = (() => {
    const explicit = parseInt(flag('--expected', '0'), 10);
    if (Number.isInteger(explicit) && explicit > 0) return explicit;
    const m = String(PROMPT_TEXT || '').match(/create\s+(\d+)\s+separate\s+clips/i);
    return m ? parseInt(m[1], 10) : 0;
})();
const MANUAL_ADD_COUNT = Math.max(0, parseInt(flag('--manual-add-count', '0'), 10) || 0);
let manualBaselineFailures = 0;
// Flow voice asset name(s) to attach via the "+" (Add ingredients) menu.
// Repeatable: --voice Orus --voice Achernar. One for a narrator, two for a
// two-hander so each character gets their own.
const VOICES = (() => {
    const out = [];
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--voice' && argv[i + 1] && !argv[i + 1].startsWith('--')) out.push(String(argv[i + 1]).trim());
    }
    return out.filter(Boolean);
})();

// ---- character reference sheets --------------------------------------------
// A raw Image tile is what keeps the cast stable, and Flow only offers one if
// the sheet is already in the project's asset list. --refs puts them there
// automatically instead of leaving it as a manual upload step per project.
//
//   --refs <story.json>       read character_references out of a story package
//   --refs <dir>              upload every image in a folder
//   --refs a.jpg,b.jpg        upload named files
//   --no-upload-refs          never upload; only prefer Image tiles if present
const REFS_RAW    = flag('--refs');
const REFERENCE_FILES_JSON = flag('--reference-files-json');
const UPLOAD_REFS = !flag('--no-upload-refs', false);
const referenceCache=require('./reference_cache');
const REFERENCE_CACHE_FILE=path.join(__dirname,'logs','verified_reference_uploads.json');
const REFERENCE_SCOPE=CDP_URL+'|'+PROJECT_URL;
const referenceState=referenceCache.load(REFERENCE_CACHE_FILE);
const REFS = (() => {
    const out = [];
    if (typeof REFS_RAW !== 'string' && typeof REFERENCE_FILES_JSON !== 'string') return out;
    const files = typeof REFERENCE_FILES_JSON === 'string' ? JSON.parse(REFERENCE_FILES_JSON) : REFS_RAW.split(',').map(s => s.trim()).filter(Boolean);
    if(!Array.isArray(files) || files.some(p=>typeof p!=='string' || !p.trim()))throw Error('Invalid reference file list.');
    for (const p of files) {
        if (!fs.existsSync(p)) { out.push({ name: path.basename(p, path.extname(p)), file: null, asked: p }); continue; }
        if (fs.statSync(p).isDirectory()) {
            for (const f of fs.readdirSync(p)) {
                if (/\.(jpe?g|png|webp)$/i.test(f)) out.push({ name: path.basename(f, path.extname(f)), file: path.join(p, f) });
            }
        } else if (/\.json$/i.test(p)) {
            let story = null;
            try { story = JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) {
                out.push({ name: path.basename(p), file: null, asked: `${p} (unreadable: ${e.message})` });
                continue;
            }
            const storyDir = path.dirname(path.resolve(p));
            const table = story.character_references || {};
            const names = [...new Set([...Object.keys(table),
                                       ...Object.keys(story.character_descriptions || {})])];
            for (const n of names) out.push({ name: n, file: MT.resolveCharacterRef(table, n, storyDir) });
            // The film's one place rides in the same folder and is attached the
            // same way, but it is not a character, so it is not in the table
            // above. Without this the plate never reaches the project and the
            // @Place mention has nothing to bind to.
            const placeName = story.place && String(story.place.name || '').trim();
            if (placeName) out.push({ name: placeName, file: MT.resolveCharacterRef({}, placeName, storyDir) });
        } else if (/\.(jpe?g|png|webp)$/i.test(p)) {
            out.push({ name: path.basename(p, path.extname(p)), file: path.resolve(p) });
        }
    }
    return out;
})();

const RUN_ID = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const RUN_DIR = path.join(__dirname, 'logs', `agent_run_${RUN_ID}`);
let snapN = 0;

// ---- in-page snapshot ------------------------------------------------------
// Everything the caller needs to understand the current screen, collected in
// one round trip. `tail` is the most useful field for a chat surface: it is the
// literal end of the visible text, i.e. whatever the agent just said.
function snapshotFn() {
    const cls = (el) => (el.className && el.className.toString) ? el.className.toString() : '';
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const d = (el, depth) => {
        const r = el.getBoundingClientRect();
        const o = {
            tag: el.tagName.toLowerCase(),
            cls: cls(el).slice(0, 160),
            aria: el.getAttribute('aria-label'),
            role: el.getAttribute('role'),
            text: (el.innerText || el.textContent || '').trim().slice(0, 140),
            rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
        };
        if (depth) o.children = [...el.children].slice(0, 15).map(c => d(c, depth - 1));
        return o;
    };

    const chip = document.querySelector('flow-agent-mode-toggle-chip');
    const gen  = document.querySelector('button[aria-label="Start generation"]');
    const pm   = document.querySelector('flow-base-prompt-box .ProseMirror')
              || document.querySelector('.ProseMirror');

    const buttons = [...document.querySelectorAll('button')]
        .filter(vis)
        .map(b => ({
            aria: b.getAttribute('aria-label'),
            text: (b.innerText || '').trim().slice(0, 60),
            cls: cls(b).slice(0, 120),
            disabled: b.disabled || /mat-mdc-button-disabled/.test(cls(b)),
        }));

    // Chat / agent-reply shaped nodes. Empty until the first prompt is sent.
    const kw = /chat|message|conversation|turn|reply|response|agent-|assistant|storyboard|scene-card|plan/i;
    const chatish = [...document.querySelectorAll('*')]
        .filter(el => kw.test(cls(el)))
        .slice(0, 60)
        .map(el => d(el, 1));

    const videoEls = [...document.querySelectorAll('flow-video-tile')];
    const FAIL = /audio generation failed|failed to generate|generation failed|something went wrong|try a different prompt|you have not been charged/i;
    const BUSY = /generating|generation in progress|queued|processing|creating|(?:^|\n)\s*\d{1,2}%\s*(?:\n|$)/i;
    const failedVideos = videoEls.filter(t => FAIL.test(t.innerText || t.textContent || '')
        || !!t.querySelector('[class*=error-tile], button[aria-label="Retry"]'));
    // Empty scheduled tiles are not finished videos. Virtualized finished
    // tiles retain a thumbnail even while their video player is unmounted.
    const hasCompletedMedia = t => [...t.querySelectorAll('video, video source, img')].some(el => {
        const src = el.currentSrc || el.getAttribute('src') || el.getAttribute('poster') || '';
        return /^(?:https?:|blob:)/i.test(src) && !/\.svg(?:[?#]|$)|placeholder|loading/i.test(src);
    });
    const generatingVideos = videoEls.filter(t => !failedVideos.includes(t)
        && (BUSY.test(t.innerText || t.textContent || '') || !!t.querySelector('mat-progress-spinner, [role="progressbar"], [class*=spinner]')
            || !hasCompletedMedia(t)));
    const mediaTiles = {
        flow_video_tile: videoEls.length,
        ready_video_tile: Math.max(0, videoEls.length - failedVideos.length - generatingVideos.length),
        failed_video_tile: failedVideos.length,
        generating_video_tile: generatingVideos.length,
        agent_busy: buttons.some(b => !b.disabled && (/^stop(?: generation| generating)?$/i.test(b.aria || '')
            || /stop-button|stop-icon-button/.test(b.cls))),
        flow_image_tile: document.querySelectorAll('flow-image-tile').length,
        any_tile: [...document.querySelectorAll('*')].filter(el => /tile/i.test(cls(el)) && vis(el)).length,
    };

    const body = (document.body.innerText || '').replace(/\n{3,}/g, '\n\n');

    return {
        url: location.href,
        agentOn: !!(chip && /checked/.test(cls(chip)))
            || [...document.querySelectorAll('.agent-panel-prompt-box, .agent-panel-wrapper')]
                .some(vis),
        chipClass: chip ? cls(chip) : null,
        instructionsBtn: !!document.querySelector('button[aria-label="Agent instructions"]'),
        settingsBtn: !!document.querySelector('button[aria-label="Settings"]'),
        promptText: pm ? (pm.innerText || '').slice(0, 1200) : null,
        promptHTML: pm ? (pm.innerHTML || '').slice(0, 3000) : null,
        generateBtn: gen ? {
            exists: true,
            disabled: gen.disabled || /mat-mdc-button-disabled/.test(cls(gen)),
        } : { exists: false },
        overlays: [...document.querySelectorAll('.cdk-overlay-container')]
            .filter(el => el.children.length).map(el => d(el, 2)),
        buttons,
        chatish,
        conversationRows: [...document.querySelectorAll('.messages-list .message-row')]
            .map(el => ({ role: el.classList.contains('user-row') ? 'user' : 'agent',
                text: (el.innerText || '').trim(), error: !!el.querySelector('.chat-error-card') })),
        mediaTiles,
        tail: body.slice(-2000),
    };
}

// ---- failure affordances ---------------------------------------------------
let lastProjectScan = '';
async function readProjectSnapshot(page, full = true) {
    let snapshot = await page.evaluate(snapshotFn);
    // The DOM stops representing the full asset list once Flow virtualizes
    // older rows. Never interpret that viewport count as a missing clip.
    // Even a five/ten-clip batch is virtualized in Flow's single-column list.
    // Resume/completion decisions require the whole project, not viewport tiles.
    if (full && EXPECTED_CLIPS > 0 && !snapshot.mediaTiles.agent_busy) {
        const viewportCount = snapshot.mediaTiles.flow_video_tile;
        const project = await require('./agent_project_media').scanProjectMedia(page);
        snapshot = await page.evaluate(snapshotFn);
        snapshot.mediaTiles = { ...snapshot.mediaTiles, ...project, viewport_video_tile: viewportCount };
        const summary = `Full project scan: ready=${project.ready_video_tile}, failed=${project.failed_video_tile}, generating=${project.generating_video_tile}, total=${project.flow_video_tile} (viewport had ${viewportCount}).`;
        if (summary !== lastProjectScan) { log(summary); lastProjectScan = summary; }
    }
    if (MANUAL_ADD_COUNT && manualBaselineFailures) snapshot.mediaTiles.failed_video_tile = Math.max(0, snapshot.mediaTiles.failed_video_tile - manualBaselineFailures);
    return snapshot;
}
// A failed clip surfaces twice. In the agent conversation it is a card with a
// "Retry" button. In the media grid it is a tile that offers only "Reuse
// prompt". This reads both, without clicking anything.
function retryFn() {
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    // The specific Veo failure wording, NOT a bare /error/ - that appears in
    // unrelated UI and would make every page look broken.
    const FAIL = /audio generation failed|failed to generate|generation failed|something went wrong|try a different prompt/i;
    const scopes = [...document.querySelectorAll('flow-video-tile, [class*=error-tile], [class*=generation-error], [class*=media-error]')]
        .filter(vis).filter(el => FAIL.test(el.innerText || el.textContent || '')
            || !!el.querySelector('button[aria-label="Retry"], button.reuse-prompt-button, button[aria-label="Reuse prompt"]'));
    const failedText = scopes.some(el => FAIL.test(el.innerText || el.textContent || ''));
    const retryButtons = scopes.reduce((n, el) => n + [...el.querySelectorAll('button')]
        .filter(b => vis(b) && /^retry$/i.test((b.getAttribute('aria-label') || '').trim()) && !b.disabled).length, 0);
    // A failed media tile renders as an "error tile" holding a Reuse-prompt
    // button. That is the precise anchor: matching a generic ancestor (the
    // virtual-scroll container, a whole section) counts healthy tiles too.
    const reuseInError = [...document.querySelectorAll('[class*=error-tile]')]
        .filter(el => vis(el) && !!el.querySelector('button.reuse-prompt-button, button[aria-label="Reuse prompt"]'))
        .length;
    // A policy refusal reads very differently from a generation failure: the
    // model says it cannot help with that. Count it so the agent can re-ask
    // with a policy-safe wording instead of blindly clicking Retry.
    const refusedText = scopes.some(el => /policy|violat|community guidelines|not allowed|cannot (generate|create|help)|can't (generate|create|help)|unable to (generate|create)|against our|blocked by|safety/i.test(el.innerText || el.textContent || ''));
    return { failedText, retryButtons, reuseInError, refusedText };
}

// Click only a control owned by a failed MEDIA tile. Never click Flow's global
// conversation "Try again": that repeats the complete multi-clip request.
// Do one tile per pass so the prompt box cannot be overwritten by another tile.
async function clickFailures(page) {
    return await page.evaluate(() => {
        const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
        let retry = 0, reuse = 0;
        const FAIL = /audio generation failed|failed to generate|generation failed|something went wrong|try a different prompt|you have not been charged/i;
        const scopes = [...document.querySelectorAll('flow-video-tile, [class*=error-tile], [class*=generation-error], [class*=media-error]')]
            .filter(vis).filter(el => FAIL.test(el.innerText || el.textContent || '')
                || !!el.querySelector('button[aria-label="Retry"], button.reuse-prompt-button, button[aria-label="Reuse prompt"]'));
        const tile = scopes[0];
        if (tile) {
            const rb = [...tile.querySelectorAll('button')].find(b => vis(b)
                && /^retry$/i.test((b.getAttribute('aria-label') || '').trim()) && !b.disabled);
            if (rb) { rb.click(); retry = 1; }
            else {
                const b = tile.querySelector('button.reuse-prompt-button, button[aria-label="Reuse prompt"]');
                if (b && !b.disabled && vis(b)) { b.click(); reuse = 1; }
            }
        }
        return { retry, reuse };
    });
}
async function clickStart(page) {
    return await page.evaluate(() => {
        const b = document.querySelector('button[aria-label="Start generation"]');
        if (!b || b.disabled) return false;
        b.click();
        return true;
    });
}

// The playbook gotcha: the agent sometimes says it is "going to generate" but
// never renders an approval card, so the run just sits there. Send it a plain
// confirmation the way a human would.
// A policy refusal cannot be fixed by clicking Retry - the same words will be
// refused again. Re-ask in plain language for a policy-safe version, which is
// also the sanitizer's job on the story side.
async function policyNudge(page) {
    const box = await page.evaluate(() => {
        const pm = document.querySelector('flow-base-prompt-box .ProseMirror') || document.querySelector('.ProseMirror');
        if (!pm) return null;
        pm.focus();
        const r = pm.getBoundingClientRect();
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    });
    if (!box) return false;
    await page.mouse.click(box.x, box.y);
    await wait(400);
    await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
    await page.keyboard.press('Backspace');
    const msg = 'Regenerate only the clips that were refused for policy. Keep every other detail identical, but make the wording policy-safe: do not name or depict any real person, and remove any weeping, sobbing, blood, gore, wounds or weapons aimed at a person. Show only the visual action and keep the narration line.';
    await page.keyboard.type(msg, { delay: 12 });
    await wait(700);
    await page.keyboard.press('Enter');
    return true;
}

async function nudgeAgent(page) {    const box = await page.evaluate(() => {
        const pm = document.querySelector('flow-base-prompt-box .ProseMirror') || document.querySelector('.ProseMirror');
        if (!pm) return null;
        pm.focus();
        const r = pm.getBoundingClientRect();
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    });
    if (!box) return false;
    await page.mouse.click(box.x, box.y);
    await wait(400);
    await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
    await page.keyboard.press('Backspace');
    await page.keyboard.type('Yes, generate it now', { delay: 25 });
    await wait(600);
    await page.keyboard.press('Enter');
    return true;
}

// Attach a named voice from Flow's Voices library to the prompt box.
// The walk itself lives in flow_voice.js, because the extend engine attaches
// the same voice to every clip and two copies of this sequence would drift.
// Kept as a function with this exact name so every call site is unchanged.
async function attachVoice(page, name) {
    return attachVoiceShared(page, name, { log, wait });
}

// A short watch that also auto-approves, used between retry rounds.
async function sweepFor(page, secs, tag) {
    const APPROVE = /approve|confirm|proceed|go ahead|looks good|generate|continue|yes\b|create the|start/i;
    const t0 = Date.now();
    let lastTail = '';
    while ((Date.now() - t0) / 1000 < secs) {
        await wait(4000);
        const cur = await readProjectSnapshot(page);
        if (cur.tail !== lastTail) {
            lastTail = cur.tail;
            const fresh = cur.tail.split('\n').map(x => x.trim()).filter(Boolean).slice(-3);
            for (const line of fresh) log(`        | ${line.slice(0, 120)}`);
        }
        if (AUTO_APPROVE) {
            const cands = cur.buttons.filter(b => b.aria && APPROVE.test(b.aria) && !b.disabled &&
                !/try again|retry|regenerate/i.test(b.aria + ' ' + b.text) &&
                !/^(Settings|Agent instructions|Start generation|Start new session|New session|Home|Search|Favorite|Expand)$/i.test(b.aria));
            if (cands.length) {
                await page.evaluate((lbl) => {
                    const b = [...document.querySelectorAll('button')].find(x => x.getAttribute('aria-label') === lbl);
                    if (b) b.click();
                }, cands[0].aria);
                log(`        auto-clicked "${cands[0].aria}"`);
                await wait(5000);
            }
        }
    }
    // No snapshot here: `snap` lives in the run scope, not at module level, and
    // calling it from here crashed the retry pass with "snap is not defined".
    return await readProjectSnapshot(page);
}

async function retryFailedMediaOnly(page, snap, label = 'retry') {
    let retried = 0;
    for (let round = 1; round <= RETRY_ROUNDS; round++) {
        const cur = await readProjectSnapshot(page);
        const mt = cur.mediaTiles;
        const tally = EXPECTED_CLIPS > 0
            ? `ready=${mt.ready_video_tile}/${EXPECTED_CLIPS}, failed=${mt.failed_video_tile}, generating=${mt.generating_video_tile}`
            : `ready=${mt.ready_video_tile}, failed=${mt.failed_video_tile}, generating=${mt.generating_video_tile}`;
        const st = await page.evaluate(retryFn);

        // Once the project already has the requested number of completed
        // videos, retrying an additional failed attempt can only increase the
        // excess count. Let download + dialogue ordering choose one per scene.
        if (EXPECTED_CLIPS > 0 && mt.ready_video_tile >= EXPECTED_CLIPS && !mt.agent_busy && mt.generating_video_tile === 0) {
            log(`Round ${round}: ${tally}; enough completed clips already exist, so failed attempts are left untouched.`);
            if (mt.ready_video_tile > EXPECTED_CLIPS) log('  Duplicate count detected; retrying would create more clutter.');
            break;
        }

        if (!st.retryButtons && !st.reuseInError) {
            if (mt.generating_video_tile > 0 || mt.agent_busy) {
                log(`Round ${round}: ${tally}; waiting for active generations.`);
                await sweepFor(page, RETRY_WATCH, `${label}-${round}-waiting`);
                continue;
            }
            log(`Round ${round}: ${tally}; no failed media-tile retry control remains.`);
            break;
        }
        if (st.refusedText) {
            log(`Round ${round}: a failed media tile reports a policy refusal.`);
            log('  Safe retry stopped. Edit that one prompt manually; the full story will not be resubmitted.');
            break;
        }

        log(`Round ${round}: ${tally}; retrying ONE failed media tile only.`);
        const c = await clickFailures(page);
        retried += c.retry + c.reuse;
        if (!c.retry && !c.reuse) {
            log('  No media-scoped retry control was clickable. The conversation-level Try again was deliberately ignored.');
            break;
        }
        log(`  clicked inside failed tile: Retry=${c.retry}, Reuse prompt=${c.reuse}`);
        await wait(2500);
        if (c.reuse) {
            const started = await clickStart(page);
            log(`  Start generation: ${started ? 'clicked' : 'not clickable'}`);
            if (!started) break;
            await wait(2500);
        }
        await snap(`${label}-${round}`);
        await sweepFor(page, RETRY_WATCH, `${label}-${round}-after`);
    }
    return retried;
}

// ---- deep read of the "@" picker -------------------------------------------
// The first dump only went 2 levels into .cdk-overlay-container and returned a
// pane with no children, so the asset items were invisible to us. This goes all
// the way down and pulls out every clickable thing, so we can find the entry by
// name even when the markup is unfamiliar.
function pickerFn() {
    const cls = (el) => (el.className && el.className.toString) ? el.className.toString() : '';
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const depthOf = (el) => { let d = 0; for (let p = el; p; p = p.parentElement) d++; return d; };

    const root = document.querySelector('.cdk-overlay-container');
    if (!root || !root.children.length) return { open: false };

    const walk = (el, depth, out) => {
        if (depth < 0) return;
        const r = el.getBoundingClientRect();
        out.push({
            tag: el.tagName.toLowerCase(),
            cls: cls(el).slice(0, 140),
            aria: el.getAttribute('aria-label'),
            role: el.getAttribute('role'),
            text: (el.innerText || el.textContent || '').trim().slice(0, 120),
            rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
            visible: r.width > 0 && r.height > 0,
            depth,
        });
        for (const c of el.children) walk(c, depth - 1, out);
    };
    const tree = [];
    walk(root, 5, tree);

    const SELECTOR = 'button, [role="option"], [role="menuitem"], mat-option, li, ' +
                     '[class*="asset"], [class*="item"], [class*="card"], [class*="tile"], ' +
                     '[class*="character"], [class*="result"], [class*="thumb"]';
    const clickable = [...root.querySelectorAll(SELECTOR)]
        .filter(vis)
        .map(el => {
            const r = el.getBoundingClientRect();
            return {
                tag: el.tagName.toLowerCase(),
                cls: cls(el).slice(0, 140),
                aria: el.getAttribute('aria-label'),
                text: (el.innerText || el.textContent || '').trim().slice(0, 100),
                rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
                depth: depthOf(el),
                cx: Math.round(r.x + r.width / 2),
                cy: Math.round(r.y + r.height / 2),
            };
        })
        .filter(el => el.text || el.aria);

    return {
        open: true,
        paneCount: document.querySelectorAll('.cdk-overlay-pane').length,
        emptyText: /no assets found|no results|nothing found/i.test(root.innerText || ''),
        clickable,
        tree,
    };
}

// ---- reference-sheet upload -------------------------------------------------
// Flow attaches reference PIXELS only for a raw Image tile. A saved Character is
// a named entity the agent re-instantiates per clip, which is what drifts. So
// the sheet has to be in the project's asset list, and the picker's own
// "Upload media" entry is the way in.
//
// This runs BEFORE the prompt is typed, so the bare "@" it types to open the
// picker can simply be cleared afterwards without disturbing anything.
async function clearPromptBox(page, box) {
    // Ctrl+A is unreliable here: the ProseMirror editor does not reliably hold
    // focus after a mouse click, so a page-level select-all can miss it. Drive
    // the editor's own selection and delete commands instead.
    await page.mouse.click(box.x, box.y);
    await wait(250);
    const left = await page.evaluate(() => {
        const pm = document.querySelector('flow-base-prompt-box .ProseMirror')
                || document.querySelector('.ProseMirror');
        if (!pm) return -1;
        pm.focus();
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(pm);
        sel.removeAllRanges();
        sel.addRange(range);
        document.execCommand('delete', false, null);
        // Mention chips can survive a text delete; drop them directly.
        for (const chip of pm.querySelectorAll('.mention-chip')) chip.remove();
        pm.dispatchEvent(new InputEvent('input', { bubbles: true }));
        return (pm.innerText || '').trim().length;
    });
    if (left > 0) log(`   warning: prompt box still holds ${left} characters after clearing.`);
    await wait(350);
}

// Is there already a raw Image tile for this name in the project? Re-uploading
// on every run would pile up duplicate assets, so check before uploading.
// Returns the choice if an Image tile is already there, else null.
async function refImageAlreadyPresent(page, box, name) {
    await page.mouse.click(box.x, box.y);
    await wait(350);
    await page.keyboard.type(' @' + name, { delay: 0 });
    await page.waitForFunction(name=>{
        const key=s=>String(s||'').trim().replace(/\.(png|jpe?g|webp)$/i,'').toLowerCase();
        return [...document.querySelectorAll('.cdk-overlay-pane button.asset-item')].some(b=>b.getBoundingClientRect().width>0&&key(b.querySelector('.asset-title')?.textContent||b.textContent)===key(name))
            || /no assets found|no results|nothing found/i.test(document.querySelector('.cdk-overlay-container')?.innerText||'');
    },{timeout:4000,polling:100},name).catch(()=>{});
    await require('./reference_picker_images').selectImages(page,{log});
    const pk = await page.evaluate(pickerFn);
    const choice = MT.chooseMentionTile(pk.clickable || [], name);
    await page.keyboard.press('Escape');
    await wait(400);
    await clearPromptBox(page, box);
    return ((choice.reason === 'ok' && choice.kind === 'image') || (choice.reason==='no-type' && choice.inner && /\.(png|jpe?g|webp)$/i.test((choice.inner.text||'').trim()))) ? choice : null;
}

async function uploadRefThroughPicker(page, box, file) {
    await page.mouse.click(box.x, box.y);
    await wait(400);
    await page.keyboard.type(' @', { delay: 120 });
    await wait(2400);

    // The chooser can only be awaited once we know the click will cause it, so
    // start listening first and give up on the wait rather than hanging.
    const chooserP = page.waitForFileChooser({ timeout: 9000 }).catch(() => null);

    const clicked = await page.evaluate(() => {
        const root = document.querySelector('.cdk-overlay-container');
        if (!root) return false;
        const up = [...root.querySelectorAll('button, [role="menuitem"], a, li')]
            .find(x => /upload media/i.test((x.innerText || '') + ' ' +
                                           (x.getAttribute('aria-label') || '')));
        if (!up) return false;
        up.click();
        return true;
    });

    if (!clicked) {
        log('      no "Upload media" entry in the picker - skipped');
        await page.keyboard.press('Escape');
        await wait(400);
        await clearPromptBox(page, box);
        return false;
    }

    const chooser = await chooserP;
    if (chooser) {
        await chooser.accept([file]);
    } else {
        // Some builds render a hidden <input type=file> instead of a dialog.
        const input = await page.$('input[type="file"]');
        if (!input) {
            log('      no file chooser appeared - skipped');
            await page.keyboard.press('Escape');
            await wait(400);
            await clearPromptBox(page, box);
            return false;
        }
        await input.uploadFile(file);
    }

    // The upload is a round trip; give it room, then close the picker and clear
    // the "@" so the real prompt starts from an empty box.
    await wait(7000);
    await page.keyboard.press('Escape');
    await wait(500);
    await clearPromptBox(page, box);
    return true;
}

(async () => {
    fs.mkdirSync(RUN_DIR, { recursive: true });

    const browser = await puppeteer.connect({ browserURL: CDP_URL, defaultViewport: null });
    const { page, pages, flowTabs } = await selectAgentPage(browser, PROJECT_URL);
    // Prefer a tab that is actually IN a project over one sitting on the
    // Flow home page: the browser often carries both, and first-match
    // grabbed whichever loaded first - the home tab - and then failed the
    // project-id check below even though the project was open all along.
    if (!page) {
        console.error('No Flow tab found in the AUTOMATION browser. Open a Flow project there.');
        console.error('Open tabs:\n  ' + pages.map(p => p.url()).join('\n  '));
        await browser.disconnect();
        process.exit(1);
    }
    log(`Flow tab: ${page.url()}`);
    await page.bringToFront();
    if (flowTabs.length > 1) {
        log(`${flowTabs.length} Flow tabs open - using the one inside a project.`);
    }

    async function snap(label) {
        const data = await readProjectSnapshot(page, /^(baseline|final|safe-retry-final|recovery-no-media-confirmed|batch-completed)$/.test(label));
        const f = path.join(RUN_DIR, `${String(++snapN).padStart(2, '0')}_${label}.json`);
        fs.writeFileSync(f, JSON.stringify(data, null, 2));
        return data;
    }

    // ---- 1. Agent Mode must run on the project home, NOT in the editor -----
    // An explicit project wins: go straight to it, so one film per project is
    // deterministic rather than "wherever the browser was left".
    if (PROJECT_URL && page.url() !== PROJECT_URL) {
        log(`Opening this film's project: ${PROJECT_URL}`);
        await page.goto(PROJECT_URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
        await wait(5000);
    }
    const m = page.url().match(/\/project\/([a-zA-Z0-9_-]+)/);
    if (!m) {
        console.error(`Cannot find a project id in ${page.url()}`);
        console.error('Open a Flow project (https://flow.google.com/project/...) and retry.');
        await browser.disconnect();
        process.exit(1);
    }
    const projectId = m[1];
    const homeUrl = `https://flow.google.com/project/${projectId}`;

    if (/\/edit\//i.test(page.url()) || /\/scene\//i.test(page.url())) {
        log('Currently in the scene editor. Agent Mode lives on the project home.');
        log(`Navigating back to ${homeUrl}`);
        await page.goto(homeUrl, { waitUntil: 'domcontentloaded' });
        await wait(6000);
    }

    // ---- 2. Settle, then take a baseline -----------------------------------
    await wait(3000);
    let s = await snap('baseline');
    if (MANUAL_ADD_COUNT) {
        if (s.mediaTiles.agent_busy || s.mediaTiles.generating_video_tile > 0 || s.mediaTiles.project_scan_complete === false) {
            throw Error('Manual selection waits for the current project generation to finish. No selected prompt was submitted.');
        }
        manualBaselineFailures = s.mediaTiles.failed_video_tile;
        EXPECTED_CLIPS = s.mediaTiles.ready_video_tile + MANUAL_ADD_COUNT;
        s.mediaTiles.failed_video_tile = 0;
        log(`MANUAL SELECTION: adding ${MANUAL_ADD_COUNT} new clip(s) to ${s.mediaTiles.ready_video_tile} completed clips; original batch checkpoint ignored.`);
    }
    log(`Agent Mode is ${s.agentOn ? 'ON' : 'OFF'}`);
    log(`Prompt box   : ${s.promptText !== null ? 'found' : 'NOT FOUND'}`);
    log(`Submit button: ${s.generateBtn.exists ? (s.generateBtn.disabled ? 'present (disabled)' : 'present (ready)') : 'NOT FOUND'}`);
    log(`Instructions : ${s.instructionsBtn ? 'button present' : 'button not found'}`);
    log(`Media tiles  : video=${s.mediaTiles.flow_video_tile} image=${s.mediaTiles.flow_image_tile}`);

    if (CHECK_ONLY) {
        log(`--check only. Snapshots in ${RUN_DIR}`);
        await browser.disconnect();
        return;
    }

    // ---- 3. Turn the Agent chip ON if needed -------------------------------
    if (!s.agentOn) {
        log('Turning Agent Mode ON...');
        const ok = await page.evaluate(() => {
            const chip = document.querySelector('button.agent-mode-chip')
                      || document.querySelector('flow-agent-mode-toggle-chip button');
            if (!chip) return false;
            chip.click();
            return true;
        });
        if (!ok) { console.error('Agent chip not found - is the prompt box visible?'); await browser.disconnect(); process.exit(1); }
        await wait(2500);
        s = await snap('agent-on');
        log(`Agent Mode now ${s.agentOn ? 'ON' : 'STILL OFF (clicked, but class did not change)'}`);
    }

    if (!s.agentOn) throw Error('Agent Mode did not turn on. No generation submitted.');

    // Reconcile batches supplied manually while the local checkpoint was stale.
    // This returns to the orchestrator WITHOUT typing or clicking Generate.
    const submissionCheckpoint = flag('--submission-file', null);
    const requiredCheckpoint = flag('--require-ready', null);
    if (submissionCheckpoint && requiredCheckpoint !== null
        && s.mediaTiles.ready_video_tile > Number(requiredCheckpoint)) {
        const planFile = path.join(submissionCheckpoint.replace(/\.json\.submission\.json$/, ''), 'batches.json');
        if (fs.existsSync(planFile)) {
            const plan = JSON.parse(fs.readFileSync(planFile, 'utf8'));
            const intent = JSON.parse(fs.readFileSync(submissionCheckpoint, 'utf8'));
            if (plan.context.fingerprint === intent.fingerprint) {
                const verified = require('./agent_batch_reconcile').reconcileCompleted(s, plan,
                    Number(requiredCheckpoint), W.sanitizeForPolicy);
                if (verified) {
                    log(`Verified saved scene instructions in Flow for batches ${verified.verified.map(b => `${b.from}-${b.to}`).join(', ')}.`);
                    log(`BATCH_RECONCILED_READY:${verified.completed}`);
                    await browser.disconnect();
                    return;
                }
            }
        }
    }

    if (RETRY_FAILED_ONLY) {
        // An Agent request error is different from a failed video tile. Only
        // replay the exact pending request after two empty-media observations.
        const { failedBeforeMedia } = require('./agent_batch_recovery');
        if (failedBeforeMedia(s, SEND_TEXT)) {
            await wait(10000);
            s = await snap('recovery-no-media-confirmed');
            if (failedBeforeMedia(s, SEND_TEXT)) {
                log('BATCH_REQUEST_FAILED_BEFORE_MEDIA: exact pending request has an Agent error and no video tiles.');
                await browser.disconnect();
                process.exit(3);
            }
        }
        banner(`SAFE RETRY: FAILED MEDIA TILES ONLY${EXPECTED_CLIPS ? ` (expect ${EXPECTED_CLIPS})` : ''}`);
        log('The full story prompt will not be typed or submitted.');
        log('Flow conversation-level "Try again" is ignored because it repeats every clip.');
        const retried = await retryFailedMediaOnly(page, snap, 'safe-retry');
        const final = await snap('safe-retry-final');
        const mt = final.mediaTiles;
        log(`Safe retries : ${retried}`);
        log(`Clip state   : ready=${mt.ready_video_tile}, failed=${mt.failed_video_tile}, generating=${mt.generating_video_tile}, total=${mt.flow_video_tile}`);
        const duplicate = EXPECTED_CLIPS > 0 && mt.ready_video_tile > EXPECTED_CLIPS;
        const incomplete = mt.failed_video_tile > 0 || mt.generating_video_tile > 0
            || mt.agent_busy || mt.project_scan_complete === false || (EXPECTED_CLIPS > 0 && mt.ready_video_tile !== EXPECTED_CLIPS);
        if (duplicate) log('DUPLICATES DETECTED: ready clips exceed the story count. Download can map one clip per scene; automatic join stays blocked until the manifest is exact.');
        await browser.disconnect();
        if (incomplete) process.exit(2);
        return;
    }

    // Batch orchestrator supplies the exact completed count required before
    // adding another request. A reused project or uncertain interrupted run
    // must never receive the same scene batch a second time.
    const requiredReady = flag('--require-ready', null);
    if (requiredReady !== null) {
        const needed = Number(requiredReady);
        const deadline = Date.now() + Math.max(900, WATCH_SECS) * 1000;
        let confirmed = 0;
        while (Date.now() < deadline) {
            const mt = s.mediaTiles;
            if (mt.failed_video_tile > 0 || mt.ready_video_tile > needed || mt.flow_video_tile > needed) break;
            const complete = mt.ready_video_tile === needed && mt.generating_video_tile === 0 && !mt.agent_busy && mt.project_scan_complete !== false;
            confirmed = complete ? confirmed + 1 : 0;
            if (confirmed >= 2) break;
            if (!complete) log(`Waiting for previous batch: ready=${mt.ready_video_tile}/${needed}, generating=${mt.generating_video_tile}, Agent busy=${!!mt.agent_busy}. No new prompt submitted.`);
            await wait(4000);
            s = await readProjectSnapshot(page);
        }
        const mt = s.mediaTiles;
        if (confirmed < 2 || mt.ready_video_tile !== needed
            || mt.generating_video_tile > 0 || mt.failed_video_tile > 0 || mt.agent_busy || mt.project_scan_complete === false) {
            log(`BATCH STOP: expected ${requiredReady} completed clips and no pending failures; found ready=${mt.ready_video_tile}, failed=${mt.failed_video_tile}, generating=${mt.generating_video_tile}. No prompt submitted.`);
            await browser.disconnect();
            process.exit(2);
        }
    }

    // ---- 4. Optional: dump the settings menu -------------------------------
    // The "never ask for confirmation" toggle lives behind this button. We open
    // it only when asked, because it is a real state change.
    if (DO_SETTINGS) {
        if (MANUAL_ADD_COUNT > 0) throw Error('--settings only inspects settings and cannot generate a manual selection. Remove --settings; normal generation saves settings automatically.');
        log('Opening Agent settings menu...');
        await page.evaluate(() => {
            const b = [...document.querySelectorAll('button')]
                .find(x => /^settings$/i.test(x.getAttribute('aria-label') || '')
                        && /agent-action-button/.test((x.className || '').toString()));
            if (b) b.click();
        });
        await wait(2000);
        const menu = await snap('settings-menu-open');
        log(`Overlay panes now: ${menu.overlays.length}`);
        for (const ov of menu.overlays) {
            for (const c of (ov.children || [])) {
                log(`   ${c.tag}.${(c.cls || '').split(' ')[0]} :: ${(c.text || '').replace(/\n/g, ' | ').slice(0, 120)}`);
            }
        }
        log(`Settings snapshot in ${RUN_DIR}. Close the menu, or keep it open for the next step.`);
        await browser.disconnect();
        return;
    }

    // ---- 5. Type the Agent prompt -----------------------------------------
    if (!PROMPT) {
        if (FILE_BODY && FILE_BODY.startsWith('__MISSING__')) {
            console.error(`--file not found: ${FILE_BODY.slice('__MISSING__:'.length)}`);
        } else {
            console.error('No --prompt and no --file given. Nothing to do.');
            console.error('Short prompt : node agent_mode.js --prompt "Create 3 separate clips, one per scene, using @Mia in every scene, up to 8 seconds each" --model "veo3.1 low priority"');
            console.error('Full story   : node agent_mode.js --file story_prompt.txt --model "veo3.1 low priority" --no-submit');
        }
        await browser.disconnect();
        process.exit(1);
    }

    log('Focusing the prompt box...');
    const box = await page.evaluate(() => {
        const pm = document.querySelector('flow-base-prompt-box .ProseMirror')
                || document.querySelector('.ProseMirror');
        if (!pm) return null;
        pm.scrollIntoView({ block: 'center' });
        const r = pm.getBoundingClientRect();
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    });
    if (!box) { console.error('Prompt box not found.'); await browser.disconnect(); process.exit(1); }

    await page.mouse.click(box.x, box.y);
    await wait(600);
    await page.keyboard.down('Control');
    await page.keyboard.press('KeyA');
    await page.keyboard.up('Control');
    await wait(200);

    // ---- 4c. Reference sheets in, BEFORE anything is typed ----------------
    // Must happen first: it types a bare "@" to open the picker, and there is
    // nothing in the box yet to disturb. An Image tile cannot be picked if the
    // sheet was never uploaded to this project.
    if (REFS.length && !FLOW_CHARACTERS) {
        banner('REFERENCE IMAGES');
        log(`${REFS.length} reference image(s) declared.`);
        let ready = 0, missing = 0;
        for (const r of REFS) {
            if (!r.file) {
                missing++;
                log(`   MISSING  ${r.name}: no image found${r.asked ? ' (' + r.asked + ')' : ''}`);
                continue;
            }
            log(`   ${r.name}: ${path.basename(r.file)}`);
            if (!UPLOAD_REFS) { ready++; continue; }
            if(referenceCache.cached(referenceState,REFERENCE_SCOPE,r)){
                log('      verified reference reused; skipping the preliminary picker search');ready++;continue;
            }
            if(await page.evaluate(referenceCache.namedImagePresent,r.name)){
                log('      named Image already in project; attach once after prompt paste');ready++;continue;
            }

            // Skip the upload when a raw Image tile is already in the project.
            const already = await refImageAlreadyPresent(page, box, r.name);
            if (already) {
                log(`      already an Image tile - not uploading again`);
                ready++;
                continue;
            }

            const okUpload = await uploadRefThroughPicker(page, box, r.file);
            if (okUpload) ready++; else missing++;
        }
        log(`Uploaded/available: ${ready}   Missing: ${missing}`);
        if (flag('--upload-references-only', false) && missing) throw Error('Reference library upload incomplete. Retry to upload remaining references; no generation submitted.');
        if (missing) {
            log('A missing sheet means the picker can only offer that character as a');
            log('saved Character, which is the kind that drifts. Expect drift for it.');
        }
        if (!UPLOAD_REFS) log('--no-upload-refs: uploads skipped, using tiles already in the project.');
        await wait(1200);
    }

    if (flag('--upload-references-only', false)) {
        if (!REFS.length || REFS.some(r => !r.file)) throw Error('Reference library is incomplete. No generation submitted.');
        log('Reference library upload finished. All supplied references processed; no scene prompt pasted or generation submitted.');
        await browser.disconnect();
        return;
    }

    // ---- 5a. Plain prompt text FIRST --------------------------------------
    // No mention in this string - see the MENTION split at the top of the file.
    log(`Prompt body: ${PROMPT_TEXT.length} characters.`);
    if (USE_PASTE || LONG_PROMPT) {
        if (LONG_PROMPT && !USE_PASTE) log('Long prompt - pasting instead of typing (--paste is implied).');
        // One blob, one shot. Newlines are preserved so story structure reaches
        // the agent. This does NOT fire the "@" autocomplete, which is fine: the
        // mention is typed separately in step 5b, after this.
        const inserted = await page.evaluate((t) => {
            const pm = document.querySelector('flow-base-prompt-box .ProseMirror')
                    || document.querySelector('.ProseMirror');
            if (!pm) return 'no-editor';
            pm.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('insertText', false, t);
            return (pm.innerText || '').length;
        }, SEND_TEXT);
        if (inserted === 'no-editor') { console.error('Prompt box vanished before paste.'); await browser.disconnect(); process.exit(1); }
        log(`Pasted. Editor now holds ~${inserted} characters.`);
    } else {
        // Real keystrokes. Slower, but ProseMirror's input rules see every
        // character, so typing "@Mia" opens the mention picker like a human.
        // Typing is real keystrokes, and Flow's prompt box treats Enter as SEND.
        // Flatten any newline to a space rather than submitting on the first
        // line - the "one paragraph" rule from the playbook. (Long prompts go
        // through the clipboard paste path above, which is already safe.)
        const flat = SEND_TEXT.replace(/\r?\n+/g, ' ');
        if (flat !== SEND_TEXT) log('Flattened newlines to spaces for typing (Enter would submit early).');
        await page.keyboard.type(flat, { delay: 45 });
    }
    await wait(1800);

    s = await snap('prompt-text-typed');
    const integrity = require('./agent_prompt_integrity');
    const got = await integrity.readEditor(page);
    log(`Prompt text now: "${got.slice(0, 110)}${got.length > 110 ? ' ...' : ''}"`);
    log(`Editor reports ${got.length} characters (sent ${SEND_TEXT.length}).`);
    // ProseMirror can quietly swallow parts of a multi-line paste. If the counts
    // diverge badly, stop rather than submit a story the agent never received.
    integrity.assertPrompt(got, USE_PASTE || LONG_PROMPT ? SEND_TEXT : SEND_TEXT.replace(/\r?\n+/g, ' '));

    // ---- 5b. The mention(s), LAST -----------------------------------------
    if (MENTIONS.length) {
        log(`${MENTIONS.length} mention(s), typed last: ${MENTIONS.map(m => '@' + m).join(' ')}`);
        if (MENTION_LIST.length !== MENTIONS.length) {
            log(`   the prompt names ${MENTION_LIST.length} "@" references but only ${MENTIONS.length} distinct - each is attached once.`);
        }
        if (MENTIONS.length > 3 && !flag('--image-only',false)) {
            log(`WARNING: ${MENTIONS.length} characters is over the Veo 3.1 ceiling of 3`);
            log(`         reference images. Expect the agent to refuse or silently drop one.`);
        }

        for (let mi = 0; mi < MENTIONS.length; mi++) {
            const name = MENTIONS[mi];
            log(`[${mi + 1}/${MENTIONS.length}] attaching @${name}`);

            // Picker/settings can replace the editor or move focus to an asset.
            // Reacquire it and collapse the caret at its end before typing @.
            const focused=await page.evaluate(()=>{
                const pm=[...document.querySelectorAll('.ProseMirror[contenteditable="true"]')].find(e=>{
                    const r=e.getBoundingClientRect();return r.width>0&&r.height>0;
                });
                if(!pm)return false;
                pm.focus();const range=document.createRange();range.selectNodeContents(pm);range.collapse(false);
                const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);return true;
            });
            if(!focused)throw Error('Visible Agent composer unavailable before reference attachment. No generation submitted.');

            // A chip leaves a trailing space, so only the first mention needs one.
            await page.keyboard.type(mi === 0 ? ' @' : '@', { delay: 0 });
            await page.waitForFunction(()=>[...document.querySelectorAll('.cdk-overlay-pane .side-nav-list-item-title')].some(e=>e.getBoundingClientRect().width>0),{timeout:8000,polling:100});
            await snap(`mention${mi + 1}-open`);

            const requiredKind = FLOW_CHARACTERS && /^(Sarah|George)$/i.test(name) ? 'character' : null;
            if (requiredKind) {
                await require('./reference_picker_images').selectCategory(page, 'Characters', {log});
            } else {
                await require('./reference_picker_images').selectImages(page, {log});
            }
            await require('./reference_picker_images').focusReferenceSearch(page);
            // Type ONLY the name, so the picker filters on the name and nothing else.
            await page.keyboard.type(name, { delay: 0 });
            await page.waitForFunction(name=>{
                const key=s=>String(s||'').trim().replace(/\.(png|jpe?g|webp)$/i,'').toLowerCase();
                const rows=[...document.querySelectorAll('.cdk-overlay-pane button.asset-item')].filter(b=>b.getBoundingClientRect().width>0);
                // An exact name can already exist in the unfiltered list. Wait
                // until the search has actually filtered it before clicking;
                // otherwise Angular replaces the selected row during debounce.
                return rows.length>0&&rows.every(b=>key(b.querySelector('.asset-title')?.textContent||b.textContent).includes(key(name)))
                    &&rows.some(b=>key(b.querySelector('.asset-title')?.textContent||b.textContent)===key(name));
            },{timeout:8000,polling:100},name);

            s = await snap(`mention${mi + 1}-filtered`);
            const pk = await page.evaluate(pickerFn);
            fs.writeFileSync(
                path.join(RUN_DIR, `${String(snapN).padStart(2, '0')}_picker${mi + 1}-tree.json`),
                JSON.stringify(pk, null, 2));

            log(`   picker open=${pk.open} panes=${pk.paneCount} clickable=${(pk.clickable || []).length} saysEmpty=${pk.emptyText}`);
            if (mi === 0) {
                for (const c of (pk.clickable || []).slice(0, 20)) {
                    log(`      - ${c.tag} [${(c.cls || '').split(' ')[0]}] "${(c.text || c.aria || '').slice(0, 55)}"`);
                }
            }

            // Which tile? The old rule was "deepest node whose text matches the
            // name", which is blind to the tile's TYPE - and type is the whole
            // story: an Image tile keeps the cast stable, a Character tile does
            // not. chooseMentionTile ranks by type first, depth second.
            const choice = MT.chooseMentionTile(pk.clickable || [], name, {requiredKind});
            if (!requiredKind && choice.kind && choice.kind !== 'image') throw Error(`Reference ${name} matched a ${choice.kind}, not an image. No generation submitted.`);
            if(requiredKind && !choice.inner) throw Error(`Named Flow Character ${name} was not found. Create ${name} in Characters, add its reference image and assign its voice before running. No generation submitted.`);
            fs.writeFileSync(
                path.join(RUN_DIR, `${String(snapN).padStart(2, '0')}_mention${mi + 1}-choice.json`),
                JSON.stringify(choice, null, 2));
            log('   ' + MT.describeChoice(choice, name));

            const hit = choice.inner;
            if (hit) {
                log(`   clicking: ${hit.tag} "${(hit.text || hit.aria || '').slice(0, 50)}" at ${hit.cx},${hit.cy}`);
                const picker=require('./reference_picker_images');
                if(!await page.evaluate(picker.clickNamedAsset,name))throw Error(`Reference ${name}: one exact visible asset button was not found. No generation submitted.`);
                await picker.confirmSelection(page,{expected:mi+1,name,log});
                s = await snap(`mention${mi + 1}-picked`);

                // The snapshot's promptHTML is sliced to 3000 chars from the HEAD,
                // and mention chips are appended at the END - so counting chips in
                // it always reads 0 and proves nothing. Ask the live editor.
                const chipsNow = await page.evaluate(() => {
                    const pm = document.querySelector('flow-base-prompt-box .ProseMirror')
                            || document.querySelector('.ProseMirror');
                    return pm ? pm.querySelectorAll('.mention-chip').length : -1;
                });
                log(`   chips in the editor now: ${chipsNow} (expected ${mi + 1})`);
                if (chipsNow >= 0 && chipsNow < mi + 1) {
                    throw Error(`Attachment ${name} failed. No generation submitted. Retry this batch to attach all references.`);
                }
                const ref=REFS.find(r=>r.name.toLowerCase()===name.toLowerCase());
                if(ref&&ref.file){referenceCache.record(referenceState,REFERENCE_SCOPE,[ref]);fs.mkdirSync(path.dirname(REFERENCE_CACHE_FILE),{recursive:true});fs.writeFileSync(REFERENCE_CACHE_FILE,JSON.stringify(referenceState,null,2));}
            } else {
                throw Error(`Required reference ${name} was not found in this project. No generation submitted. Tree saved for inspection.`);
            }
        }

        s = await snap('mentions-final');
        // Ask the live editor, not the snapshot: promptHTML is head-sliced and
        // the chips live at the tail, so a snapshot count is always 0.
        const chips = await page.evaluate(() => {
            const pm = document.querySelector('flow-base-prompt-box .ProseMirror')
                    || document.querySelector('.ProseMirror');
            return pm ? pm.querySelectorAll('.mention-chip').length : -1;
        });
        log(`Mention chips in the prompt: ${chips} (expected ${MENTIONS.length})`);
        if (chips !== MENTIONS.length) throw Error('Required character/location chips are missing or duplicated. No generation submitted.');
    } else {
        log('No mention in the prompt - skipping the picker step.');
    }

    // ---- 5c. Voice asset(s) ------------------------------------------------
    // One voice for a narrator, two for a two-hander. Attached last so the
    // chips sit alongside the mentions and before the final submit.
    if (VOICES.length) {
        banner(`VOICE (${VOICES.join(', ')})`);
        for (const v of VOICES) await attachVoice(page, v);
    }

    s = await snap('prompt-final');
    log(`Final prompt: "${(s.promptText || '').slice(0, 140)}"`);
    log(`Submit button: ${s.generateBtn.exists ? (s.generateBtn.disabled ? 'STILL DISABLED' : 'READY') : 'NOT FOUND'}`);

    // Apply the GUI choices together before submitting any generation.
    if(FLOW_CHARACTERS && !/omni/i.test(VIDEO_MODEL || '')) throw Error('Flow Character voice mode requires an Omni Flash video model. Choose it in the GUI. No generation submitted.');
    try {
        await applyAgentSettings(page, {
            videoModel: VIDEO_MODEL,
            imageModel: flag('--image-model') || 'Nano Banana Pro',
            resolution: VIDEO_RESOLUTION,
            aspect: typeof flag('--aspect') === 'string' ? flag('--aspect') : 'Flow',
            log,
        });
    } catch(error) {
        await snap('agent-settings-failed');
        log(`Settings failure snapshot saved in ${RUN_DIR}`);
        throw error;
    }
    integrity.assertPrompt(await integrity.readEditor(page), SEND_TEXT, true);

    if (NO_SUBMIT) {
        log(`--no-submit: stopping here. Snapshots in ${RUN_DIR}`);
        await browser.disconnect();
        return;
    }

    // ---- 6. Submit ---------------------------------------------------------
    // An open mention picker must be dismissed first, or the click lands on it.
    const stillOpen = await page.evaluate(() => {
        const r = document.querySelector('.cdk-overlay-container');
        return !!(r && r.children.length);
    });
    if (stillOpen) {
        log('Picker still open - pressing Escape so the click reaches Generate.');
        await page.keyboard.press('Escape');
        await wait(800);
    }

    log('Clicking Start generation...');
    // A REAL mouse click at the button's centre - never el.click().
    //
    // el.click() fires a synthetic event with isTrusted:false and Flow's Angular
    // handler ignores it, so the prompt stays in the box while this step reports
    // "Submitted." and the run then watches a conversation that never started.
    // Measured live: el.click() leaves the prompt untouched for the full wait;
    // page.mouse.click() at the same coordinates clears the box within 7s. The
    // picker rows are clicked by coordinate for this same reason.
    const target = await page.evaluate(() => {
        const b = document.querySelector('button[aria-label="Start generation"]');
        if (!b) return { ok: false, why: 'missing' };
        if (b.disabled || /mat-mdc-button-disabled/.test((b.className || '').toString())) return { ok: false, why: 'disabled' };
        const r = b.getBoundingClientRect();
        if (!r.width || !r.height) return { ok: false, why: 'offscreen' };
        return { ok: true, cx: Math.round(r.x + r.width / 2), cy: Math.round(r.y + r.height / 2) };
    });
    if (!target.ok) {
        console.error(`Submit failed: ${target.why}`);
        console.error(`Snapshots in ${RUN_DIR} - check 03_prompt-typed.json (was the prompt accepted?)`);
        await browser.disconnect();
        process.exit(1);
    }
    // Persist uncertainty BEFORE the credit-spending click. Recovery can only
    // replay automatically when this point was never reached.
    const submissionFile = flag('--submission-file', null);
    if (submissionFile) {
        const intent = JSON.parse(fs.readFileSync(submissionFile, 'utf8'));
        intent.status = 'submitting';
        fs.writeFileSync(submissionFile + '.tmp', JSON.stringify(intent));
        fs.renameSync(submissionFile + '.tmp', submissionFile);
    }
    await page.mouse.click(target.cx, target.cy);
    log('Submitted.');

    // ---- 7. Watch the conversation ----------------------------------------
    // This is where the unknown lives. We poll, snapshot on every visible
    // change, and report approval-looking buttons instead of guessing at them.
    banner(`WATCHING AGENT RESPONSE (${WATCH_SECS}s)`);
    log(AUTO_APPROVE
        ? 'Auto-approve is ON - approval buttons will be clicked automatically.'
        : 'Auto-approve is OFF - if the agent asks for approval, CLICK IT YOURSELF.');
    log('Everything on screen is being recorded, so this run doubles as the probe.');

    const APPROVE = /approve|confirm|proceed|go ahead|looks good|generate|continue|yes\b|create the|start/i;
    const t0 = Date.now();
    let lastTail = '';
    let lastSnap = 0;
    let approvals = 0;
    let sawChat = false;
    let lastTailAt = 0;       // when the agent's text last changed
    let lastNudgeAt = -999;   // when we last sent a nudge
    let nudges = 0;
    const completedBatch = require('./agent_batch_completion').completionTracker(EXPECTED_CLIPS);

    while ((Date.now() - t0) / 1000 < WATCH_SECS) {
        await wait(4000);
        const cur = await readProjectSnapshot(page);
        const elapsed = Math.round((Date.now() - t0) / 1000);
        if (completedBatch(cur.mediaTiles)) {
            log(`[${elapsed}s] All ${EXPECTED_CLIPS} clips are completed, with no failed or active generations. Releasing the next batch automatically.`);
            await snap('batch-completed');
            break;
        }

        if (cur.chatish.length && !sawChat) {
            sawChat = true;
            log(`[${elapsed}s] Agent conversation appeared (${cur.chatish.length} nodes).`);
            await snap('chat-appeared');
        }

        if (cur.tail !== lastTail) {
            lastTail = cur.tail;
            lastTailAt = elapsed;
            const fresh = cur.tail.split('\n').map(x => x.trim()).filter(Boolean).slice(-4);
            log(`[${elapsed}s] screen changed. Last lines:`);
            for (const line of fresh) log(`        | ${line.slice(0, 130)}`);
        }

        // Periodic full snapshot so long silences still leave a trail.
        if (elapsed - lastSnap >= 30) {
            lastSnap = elapsed;
            await snap(`watch-${elapsed}s`);
            log(`[${elapsed}s] clips: video=${cur.mediaTiles.flow_video_tile} image=${cur.mediaTiles.flow_image_tile}`);
        }

        // Approval buttons the agent has put on screen.
        const cands = cur.buttons.filter(b =>
            b.aria && APPROVE.test(b.aria) && !b.disabled &&
            !/try again|retry|regenerate/i.test(b.aria + ' ' + b.text) &&
            !/^(Settings|Agent instructions|Start generation|Start new session|New session|Home|Search|Favorite|Expand)$/i.test(b.aria)
        );
        if (cands.length) {
            log(`[${elapsed}s] APPROVAL OPTIONS: ${cands.map(c => `"${c.aria}"`).join(', ')}`);
            if (AUTO_APPROVE) {
                const label = cands[0].aria;
                const done = await page.evaluate((lbl) => {
                    const b = [...document.querySelectorAll('button')]
                        .find(x => x.getAttribute('aria-label') === lbl);
                    if (!b) return false;
                    b.click();
                    return true;
                }, label);
                if (done) {
                    approvals++;
                    log(`[${elapsed}s] Auto-clicked "${label}" (approval #${approvals}).`);
                    await snap(`approved-${approvals}`);
                    await wait(6000);
                }
            } else {
                log('        auto-approve is OFF - click it in the browser window; recording continues.');
                await snap(`approval-offered-${elapsed}s`);
            }
        }

        // Playbook gotcha: the agent sometimes says it is going to generate but
        // never renders an approval card, so nothing ever starts. Nudge it.
        const asking = /going to generate|i will generate|i'll generate|about to generate|shall i|would you like me to|ready to generate|once you confirm|please confirm|let me know/i.test(cur.tail || '');
        const stuckFor = elapsed - lastTailAt;
        if (requiredReady === null && AUTO_APPROVE && !cands.length && asking && stuckFor > 12 && nudges < 4 && (elapsed - lastNudgeAt) > 30) {
            nudges++;
            lastNudgeAt = elapsed;
            if (await nudgeAgent(page)) {
                log(`[${elapsed}s] agent looked stalled - sent "Yes, generate it now" (nudge ${nudges}).`);
                await snap(`nudge-${nudges}`);
                await wait(4000);
            }
        }
    }

    // ---- 7b. Retry failed clips -------------------------------------------
    // Failures are usually transient ("Audio generation failed" is Veo-side).
    // Click the Retry affordances and watch again, a bounded number of rounds,
    // instead of handing back a short film.
    let retried = 0;
    if (RETRY_ROUNDS > 0) {
        banner(`CHECKING CLIPS${EXPECTED_CLIPS > 0 ? ` (expect ${EXPECTED_CLIPS})` : ''} - up to ${RETRY_ROUNDS} retry rounds`);
        retried = await retryFailedMediaOnly(page, snap, 'retry');
        log(`Retry pass done: ${retried} affordance(s) clicked.`);
    }

    // ---- 8. Report ---------------------------------------------------------
    const final = await snap('final');
    banner('AGENT RUN SUMMARY');
    log(`Project      : ${projectId}`);
    log(`Agent Mode   : ${final.agentOn ? 'ON' : 'OFF'}`);
    log(`Clips/images : ready=${final.mediaTiles.ready_video_tile} failed=${final.mediaTiles.failed_video_tile} generating=${final.mediaTiles.generating_video_tile} total-video=${final.mediaTiles.flow_video_tile} image=${final.mediaTiles.flow_image_tile}`);
    log(`Approvals    : ${approvals} auto-clicked`);
    log(`Retries      : ${retried} failed-clip affordance(s) clicked`);
    log(`Conversation : ${sawChat ? 'yes' : 'no chat nodes matched'}`);
    log(`Snapshots    : ${snapN} files in ${RUN_DIR}`);

    // The gate: do not let a partial film be downloaded and joined as if it were
    // whole. Video tiles are the clips (the reference sheets are images).
    let incomplete = false;
    if (EXPECTED_CLIPS > 0) {
        const have = final.mediaTiles.ready_video_tile;
        const failed = final.mediaTiles.failed_video_tile;
        const generating = final.mediaTiles.generating_video_tile;
        incomplete = have !== EXPECTED_CLIPS || failed > 0 || generating > 0 || final.mediaTiles.agent_busy || final.mediaTiles.project_scan_complete === false;
        const state = have > EXPECTED_CLIPS ? 'DUPLICATES' : (incomplete ? 'INCOMPLETE' : 'OK');
        log(`Clips ready  : ${have}/${EXPECTED_CLIPS}, failed=${failed}, generating=${generating}  [${state}]`);
        if (incomplete) {
            log('  Not every clip was produced, so download/join is SKIPPED - a partial');
            log('  film would look broken. Re-run to retry it, or raise --retry-rounds.');
        }
    }
    log('');
    log('Next: tell Claude the run is done. The snapshots show whether the agent');
    log('produced SEPARATE clips (needs ffmpeg concat) or one timeline (needs split).');

    await browser.disconnect();
    if (incomplete) process.exit(2);
})().catch(e => { console.error('AGENT RUN FAILED:', e.message); process.exit(1); });
