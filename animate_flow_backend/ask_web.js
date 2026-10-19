/**
 * The AI Studio transport: the same prompts, answered by a real browser.
 *
 * WHY THIS EXISTS. `write_story.js` makes two or three Gemini calls per film.
 * Through the API those calls run on the free tier, which is the smallest model
 * Google ships AND rate-limited per Cloud project, so a batch of films dies
 * part-way through with a 503 that is about capacity, not about the key. The
 * same person, signed into aistudio.google.com in a normal Chrome window, gets a
 * bigger model for nothing and never sees the 503. This module is the way in.
 *
 * WHY A SEPARATE CHROME. The Flow browser on CDP 9222 is busy for the length of
 * a run, and a story is written BEFORE that run starts. Driving one browser from
 * two places would have the story-writing step steal the tab the Flow step is
 * about to use. So: its own profile, its own port.
 *
 *     profile : %LOCALAPPDATA%\flow-profiles-aistudio
 *     port    : 9223  (override with AISTUDIO_CDP)
 *
 * That profile has to be signed into Google ONCE, by hand - a window opens on
 * the first call and stays open. `--status` says whether that has happened.
 *
 * WHAT IT DOES NOT DO. It does not touch the Flow browser, it does not read or
 * write any key, and it does not decide what to send: the caller hands it a
 * prompt and gets text back. `write_story.js` parses that text with the same
 * `parseJson` it uses for an API reply, because a chat window returns the answer
 * with a fence around it and `parseJson` already unwraps that.
 *
 * Run it by hand to check the plumbing:
 *     node ask_web.js --status
 *     node ask_web.js --ask "Reply with exactly: PONG"
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const puppeteer = require('puppeteer');

const PORT = Number(process.env.AISTUDIO_CDP || 9223);
const PROFILE_DIR = path.join(process.env.LOCALAPPDATA || os.homedir(), 'flow-profiles-aistudio');
const NEW_CHAT = 'https://aistudio.google.com/prompts/new_chat';
// A Pro answer to a 6 KB prompt that has to come back as several thousand tokens
// of JSON is minutes, not seconds. Ten is the ceiling, not the expectation.
const ANSWER_TIMEOUT_MS = Number(process.env.AISTUDIO_TIMEOUT_MS || 600000);
// How long to wait for the UI to acknowledge Enter before clicking something.
const SUBMIT_GRACE_MS = 20000;
// How long the sign-in redirect and the Angular boot are given on a cold tab.
const BOOT_MS = 30000;
// Attempts per prompt. AI Studio refuses a request now and then ("permission
// denied. Please try again") and answers the very same prompt on the next try,
// so one refusal is not a failure - three in a row is.
const WEB_TRIES = Number(process.env.AISTUDIO_TRIES || 3);
// How long a submitted prompt is given to show ANY sign of life - a Stop button,
// a new turn, an error - before the page is declared wedged and reloaded. Long,
// because a big prompt on the Pro model can think for a while before its first
// token; the wedge this catches showed nothing at all for far longer.
const WEDGE_MS = Number(process.env.AISTUDIO_WEDGE_MS || 120000);

const CHROME_EXE = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    path.join(process.env.LOCALAPPDATA || '.', 'Google', 'Chrome', 'Application', 'chrome.exe'),
].find(p => fs.existsSync(p));

// The composer, most specific first. AI Studio is an Angular app whose editor has
// been a textarea inside `ms-prompt-box` and, in other builds, a plain
// contenteditable - so the driver asks for a list and takes the first that is
// really there rather than betting on one selector.
const COMPOSERS = [
    'ms-prompt-box textarea',
    'textarea[placeholder]',
    'ms-prompt-box [contenteditable="true"]',
    '[role="textbox"]',
    'textarea',
    '[contenteditable="true"]',
];
// The submit control, for when Enter does nothing. Matched on aria-label so it
// survives the label text changing.
const SEND_BUTTONS = [
    'button[aria-label*="Run" i]',
    'button[aria-label*="Send" i]',
    'ms-run-button button',
];
// Present only while the model is working. The single most reliable signal that
// the answer is not finished - text alone cannot say that, because a long pause
// between two chunks looks exactly like the end.
const STOP_BUTTONS = [
    'button[aria-label*="Stop" i]',
    'ms-run-button button[aria-label*="Stop" i]',
];

// AI Studio refusing a request. It says "permission denied. Please try again",
// which is about as useful as the API's 503 and means the same thing: this
// attempt did not run. The text was caught on screen within one second of the
// submit and cleared itself about twenty seconds later, and the very same prompt
// sent again by hand answered normally - so it is transient, and the driver is
// expected to try again rather than to give up or to hand the caller half an
// answer.
const TOOL_LIMIT_RE = /too many tool calls|maximum (?:number of )?tool calls|tool call limit (?:reached|exceeded)/i;
const ERROR_RE = /Failed to generate content[^\n]*|permission denied[^\n]*|Something went wrong[^\n]*|An error occurred[^\n]*|too many tool calls[^\n]*|maximum (?:number of )?tool calls[^\n]*|tool call limit (?:reached|exceeded)[^\n]*/i;

let _browser = null;
// One prompt in the browser at a time. A batch writes one film after another, and
// two writers sharing a tab would type into each other's conversation.
let _queue = Promise.resolve();
// Reads that failed on the prompt being answered now. Reset per prompt, and used
// only to say how often the tab had to be rescued.
let _readState = { stuck: 0 };

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function log(msg) { process.stderr.write(`  [aistudio] ${msg}\n`); }

// Every step of a send can fail on a busy page, and a failure that does not say
// which step it was turns a one-line bug into an afternoon. `AISTUDIO_TRACE=1`
// prints each step before it runs, so a hang names itself.
const TRACE = process.env.AISTUDIO_TRACE === '1';
async function step(label, fn) {
    if (!TRACE) return fn();
    const t0 = Date.now();
    log(`${label} ...`);
    try {
        const r = await fn();
        log(`${label} ok (${Date.now() - t0}ms)`);
        return r;
    } catch (e) {
        log(`${label} FAILED after ${Date.now() - t0}ms: ${String(e.message).slice(0, 100)}`);
        throw e;
    }
}

// ── the browser ─────────────────────────────────────────────────────────────

async function cdpAlive() {
    try {
        const res = await fetch(`http://127.0.0.1:${PORT}/json/version`, { signal: AbortSignal.timeout(1500) });
        return res.ok;
    } catch { return false; }
}

/**
 * Make sure a Chrome with the AI Studio profile is up and answering on PORT.
 * Launching is the slow path and only happens once; after that every call finds
 * the port already alive and reuses the window the user may be looking at.
 */
async function ensureBrowser({ launch = true } = {}) {
    if (await cdpAlive()) return true;
    if (!launch) return false;
    if (!CHROME_EXE) throw new Error(
        `No chrome.exe found. Looked in:\n  ${CHROME_EXE}\nSet AISTUDIO_CDP if it is running elsewhere.`);
    fs.mkdirSync(path.join(PROFILE_DIR, 'Default'), { recursive: true });
    log(`starting Chrome on ${PORT} with ${PROFILE_DIR}`);
    spawn(CHROME_EXE, [
        `--remote-debugging-port=${PORT}`,
        `--user-data-dir=${PROFILE_DIR}`,
        '--profile-directory=Default',
        '--no-first-run',
        '--no-default-browser-check',
        // Same reason as the Flow browser: Google's pages behave differently
        // when the browser announces itself as automated.
        '--disable-blink-features=AutomationControlled',
        '--window-size=1600,1000',
        NEW_CHAT,
    ], { detached: true, stdio: 'ignore' }).unref();
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
        if (await cdpAlive()) return true;
        await sleep(1200);
    }
    throw new Error(`Chrome never answered on port ${PORT}. Is another program using it?`);
}

async function getBrowser() {
    if (_browser && _browser.connected) return _browser;
    await ensureBrowser();
    _browser = await puppeteer.connect({
        browserURL: `http://127.0.0.1:${PORT}`,
        defaultViewport: null,
        // A read of this page should take milliseconds. It is given a minute so
        // that a busy Angular render is waited out, and NO MORE: a real analysis
        // run had one read hang for fifteen minutes on a page that had stopped
        // answering, and the whole run was spent sitting on it. A read that fails
        // is now an event the driver can react to (see `read`), not a death.
        protocolTimeout: 60000,
    });
    _browser.on('disconnected', () => { _browser = null; });
    return _browser;
}

/**
 * The AI Studio tab, brought to the front.
 *
 * Front matters: a background tab is throttled, and AI Studio's stream can stall
 * behind a hidden tab. It also means the user can watch the story being written,
 * which is the whole point of doing it in a browser.
 */
async function getPage() {
    const browser = await getBrowser();
    const pages = await browser.pages();
    let page = pages.find(p => /aistudio\.google\.com/.test(p.url()));
    if (!page) {
        // Once, on the way in. After this the page is never reloaded behind a
        // prompt's back - see askWebOnce for why that matters.
        page = pages.find(p => /accounts\.google\.com/.test(p.url())) || pages[0];
        if (!page) page = await browser.newPage();
        log('no AI Studio tab open - opening one');
        await page.goto(NEW_CHAT, { waitUntil: 'domcontentloaded', timeout: 90000 }).catch(() => {});
    }
    await page.bringToFront();
    return page;
}

/** True when the page is Google's sign-in rather than AI Studio. */
function isSignInUrl(url) { return /accounts\.google\.com|\/v3\/signin/.test(String(url)); }

const SIGNED_OUT =
    `The AI Studio browser is not signed into Google.\n` +
    `A Chrome window using this profile is open (or was just opened):\n` +
    `  ${PROFILE_DIR}\n` +
    `Sign in there once - it is remembered after that - and run this again.`;

// ── reading the page ────────────────────────────────────────────────────────

/**
 * What the conversation looks like right now: the model's newest answer, how
 * many answers are on screen, and whether the model is still working.
 *
 * ONLY MODEL TURNS. A turn's own container says who wrote it - `model` or the
 * user - and both carry their text in the same kind of chunk. Reading "the last
 * chunk on the page" therefore reads back the prompt we just typed, which is
 * exactly what a first version of this did: it returned
 * "Reply with exactly one word: PONG" as the model's answer, four seconds in,
 * while the real answer had not started.
 *
 * The count is here for the same reason. AI Studio does not always clear the
 * screen for a new chat, so "there is text down there" cannot mean "this is the
 * answer" - the caller records the count before it sends and waits for it to
 * change.
 *
 * A chunk inside the thinking panel is skipped: thinking is not the answer, and
 * handing `parseJson` a page of prose about the JSON is worse than waiting.
 */
const SNAPSHOT = `(() => {
    const running = ${JSON.stringify(STOP_BUTTONS)}.some(s => document.querySelector(s));
    const answers = Array.from(document.querySelectorAll('ms-chat-turn'))
        // A turn that holds another turn is a wrapper, not a message.
        .filter(t => !t.querySelector('ms-chat-turn'))
        .filter(t => {
            const c = t.querySelector('.chat-turn-container');
            return !!c && c.classList.contains('model');
        })
        .map(t => {
            let nodes = Array.from(t.querySelectorAll('pre code, pre'));
            nodes = nodes.filter(e => !nodes.some(other => other !== e && other.contains(e)));
            if (!nodes.length) nodes = Array.from(t.querySelectorAll('ms-text-chunk'));
            if (!nodes.length) nodes = Array.from(t.querySelectorAll('ms-prompt-chunk'));
            return nodes
                .filter(e => !e.closest('ms-thought-chunk, [class*="think" i]'))
                .map(e => (e.innerText || '').trim())
                .filter(Boolean)
                .join('\\n\\n');
        })
        .filter(Boolean);
    const body = document.body.innerText;
    const err = (body.match(new RegExp(${JSON.stringify(ERROR_RE.source)}, 'i')) || [''])[0];
    return {
        running,
        count: answers.length,
        text: answers.length ? answers[answers.length - 1] : '',
        boxLen: (() => {
            const b = document.querySelector('ms-prompt-box textarea') || document.querySelector('textarea');
            return b ? String(b.value || '').length : null;
        })(),
        error: err.replace(/\\s+/g, ' ').trim().slice(0, 120),
        url: location.href,
    };
})()`;

function snapshot(page) { return page.evaluate(SNAPSHOT); }

/** Is this snapshot an answer that was not on screen when we submitted? */
function isFresh(s, base) {
    return !!s.text && (s.count > base.count || s.text !== base.text);
}

/**
 * Read the page, and survive it being busy.
 *
 * This page is an Angular app rendering a stream that can be thousands of tokens
 * of JSON. Reads normally take milliseconds; a read that fails means the renderer
 * is blocked, and the answer to that is to wait and ask again, not to abandon a
 * film that is still being written.
 *
 * When several reads in a row fail, the tab is reloaded. The conversation lives
 * on the server, so a reload brings it back - including an answer that was
 * finished while the page was stuck. (This is a RELOAD AFTER a submit, which is
 * fine. The reload that gets refused is the one before it: see askWebOnce.)
 */
async function read(page) {
    for (let i = 1; i <= 3; i++) {
        try { return await snapshot(page); }
        catch (e) {
            if (i === 3) break;
            await sleep(1500 * i);
        }
    }
    _readState.stuck++;
    log(`the page stopped answering a read - reloading it (${_readState.stuck})`);
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
    const until = Date.now() + 30000;
    while (Date.now() < until) {
        try { return await snapshot(page); } catch (e) { await sleep(2000); }
    }
    throw new Error('the AI Studio tab stopped answering and did not come back after a reload. ' +
                    'Close that window and run again - the story so far is still in the chat.');
}

/**
 * An evaluate that reports failure instead of throwing it.
 *
 * Every read of this page goes through CDP, and any one of them can fail on a
 * page that is momentarily busy. Two real runs died on a single
 * "Runtime.callFunctionOn timed out" that neither retried nor said which step it
 * was - so no step is allowed to be fatal on its own any more.
 */
async function safeEval(page, fn, arg) {
    for (let i = 1; i <= 2; i++) {
        try { return { ok: true, value: await page.evaluate(fn, arg) }; }
        catch (e) {
            if (i === 2) return { ok: false, error: e.message };
            await sleep(1000);
        }
    }
}

/** The composer that is actually on this page, or null. */
async function findComposer(page) {
    for (const sel of COMPOSERS) {
        const el = await page.$(sel).catch(() => null);
        if (!el) continue;
        const usable = await safeEval(page, (s) => {
            const e = document.querySelector(s);
            if (!e) return false;
            const r = e.getBoundingClientRect();
            return r.width > 40 && r.height > 8;
        }, sel);
        // A read that failed is "not yet", not "no composer": the boot loop asks
        // again in a second, and a page that never answers ends in the same error
        // with a delay rather than without one.
        if (usable.ok && usable.value) return sel;
    }
    return null;
}

/** What the page says the model is. Reported, never changed behind the user. */
async function readModel(page) {
    return page.evaluate(() => {
        const el = document.querySelector('ms-model-selector, [class*="model-selector" i], [class*="model-picker" i]');
        const t = el ? (el.innerText || '').trim().split('\\n')[0] : '';
        return t.slice(0, 60);
    }).catch(() => '');
}

/**
 * Wait for a refusal that is still on screen to go away.
 *
 * It clears itself after about twenty seconds, and the toast is plain text in
 * the body - so a retry that does not wait for it would read the LAST attempt's
 * error as this attempt's answer and refuse in six seconds flat, three times.
 */
async function waitErrorClear(page, ms = 45000) {
    const until = Date.now() + ms;
    let first = true;
    while (Date.now() < until) {
        const s = await read(page);
        if (!s.error) return true;
        if (first) { log(`a refusal is still on screen ("${s.error}") - letting it clear`); first = false; }
        await sleep(1500);
    }
    return false;
}

/**
 * Ask the app itself for a new chat, by clicking its own New chat control.
 *
 * A batch wants each film written without the one before it in the model's
 * context. Reloading the page is what gets refused (see askWebOnce), so the
 * fresh chat has to be the app's own idea.
 */
async function startNewChat(page) {
    const hit = await page.evaluate(() => {
        const want = /^(new chat|start new chat|new prompt|create new chat)\s*$/i;
        const nodes = Array.from(document.querySelectorAll('button, a, [role="button"], [role="menuitem"]'));
        const el = nodes.find(n => want.test((n.innerText || '').trim()) ||
                                  want.test(n.getAttribute('aria-label') || ''));
        if (!el) return null;
        el.click();
        return (el.innerText || el.getAttribute('aria-label') || '').trim() || 'control';
    }).catch(() => null);
    if (!hit) { log('no New chat control found; refusing to reuse the previous video conversation'); return false; }
    log(`clicked "${hit}" for a fresh chat`);
    const until = Date.now() + 20000;
    while (Date.now() < until) {
        const s = await read(page);
        if (s.count === 0 && s.boxLen === 0) return true;
        await sleep(1000);
    }
    return false;
}

// ── one prompt ──────────────────────────────────────────────────────────────

/**
 * Put the prompt in the box and send it.
 *
 * `Input.insertText` and not `page.type`: a real prompt here is several thousand
 * characters, and typing them one keypress at a time at any safe delay is
 * minutes of wall clock per call. insertText goes through the same browser input
 * pipeline in one go, so the editor sees a normal insertion and the framework's
 * change detection fires.
 *
 * It is then verified by reading the box back. When insertion silently does
 * nothing - which is what happens when the editor is not really focused - the
 * fallback writes the value directly and dispatches the input event the editor
 * listens for. A prompt that did not go in has to fail here, loudly, and not
 * surface ten minutes later as "the model returned nothing".
 */
const BOX_LEN = (s) => {
    const e = document.querySelector(s);
    return e ? String(e.value !== undefined ? e.value : e.innerText || '').length : -1;
};

/**
 * How much text is sitting in the composer, or null if it could not be read.
 *
 * null is a real answer and it is not the same as zero: a page that will not
 * tell us how much it is holding must not be treated as an empty composer, or
 * the next step would submit nothing and report success.
 */
async function boxLen(page, sel) {
    for (let i = 1; i <= 3; i++) {
        const r = await safeEval(page, BOX_LEN, sel);
        if (r.ok && r.value >= 0) return r.value;
        if (i < 3) await sleep(1500);
    }
    return null;
}

/**
 * Put the cursor in the composer, without Puppeteer's mouse.
 *
 * `ElementHandle.click()` is not a click, it is a negotiation: it scrolls the
 * element into view, waits for its box to hold still across animation frames,
 * and waits again if it finds something lying on top of it - and on this page
 * that negotiation can outlast the entire run. Traced, it was the single step
 * that hung: every other step of a send answered in 4-13ms while
 * "click the composer ..." never printed a result and the whole call died on
 * `Runtime.callFunctionOn timed out`. The same page, clicked a minute earlier by
 * a probe, had answered in 72ms, so it is the waiting, not the page.
 *
 * What the composer actually needs is the CURSOR, because `Input.insertText`
 * types into whatever holds focus. So: focus it directly, click it through the
 * DOM if focus does not take, and only then fall back to one real mouse click at
 * a point computed here - a single shot with no waiting loop behind it.
 *
 * Returns whether the composer ended up focused. It is not fatal if it did not:
 * the prompt is read back out of the box before it is sent, so a composer that
 * never received the text is caught there, with the real character count in the
 * message, instead of being reported as an answer that never came.
 */
async function focusComposer(page, sel) {
    const r = await safeEval(page, (s) => {
        const e = document.querySelector(s);
        if (!e) return 'gone';
        e.focus();
        if (document.activeElement === e) return 'focused';
        // A framework editor often only takes focus from its own click handler.
        try { e.click(); } catch (err) { /* keep going */ }
        e.focus();
        if (document.activeElement === e) return 'focused';
        const b = e.getBoundingClientRect();
        // Just inside the top edge: the middle of a growing textarea is a moving
        // target, its first line is not.
        return (b.width > 4 && b.height > 4)
            ? { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + Math.min(b.height / 2, 12)) }
            : 'nope';
    }, sel);

    if (r.ok && r.value === 'focused') return true;
    if (r.ok && r.value && typeof r.value === 'object') {
        await page.mouse.click(r.value.x, r.value.y).catch(() => {});
        await sleep(200);
        const again = await safeEval(page, (s) => document.activeElement === document.querySelector(s), sel);
        if (again.ok && again.value) return true;
    }
    return false;
}

/**
 * Write the whole prompt into the composer in one assignment.
 *
 * The native setter, not `e.value = text`: a framework-bound textarea ignores a
 * plain assignment, and this is the assignment that makes Angular's own change
 * detection fire, which is what turns the Run button on.
 *
 * `execCommand('insertText')` is the other way in, for the case where the
 * composer is a contenteditable rather than a textarea.
 */
function writeValue(page, sel, text) {
    return safeEval(page, (s, t) => {
        const e = document.querySelector(s);
        if (!e) return -1;
        if ('value' in e) {
            const proto = Object.getPrototypeOf(e);
            const setter = Object.getOwnPropertyDescriptor(proto, 'value');
            if (setter && setter.set) setter.set.call(e, t); else e.value = t;
            e.dispatchEvent(new Event('input', { bubbles: true }));
            e.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
            e.focus();
            document.execCommand('insertText', false, t);
        }
        return 0;
    }, sel, text);
}

// The composer is a rich editor that re-renders as text arrives, so typing into
// it costs more the longer the prompt is: 5,040 characters took 11.7 seconds, and
// a 22,394-character story prompt took 33. On top of the time it is not even
// reliable at that size - that same 22K prompt emptied the box, created no turn
// and answered nothing, three runs in a row. A story prompt for a 19-clip film is
// 22K by nature, so the big ones need a different way in.
//
// That way is the one a person uses: Ctrl+V. `Input.insertText` feeds the editor
// its internal typing pipeline; a paste is handled as one block by the editor and
// by the framework behind it, which is why pasting a whole prompt by hand has
// always worked here. The OS clipboard is used because the shortcut reads the
// real one - and it is put back afterwards, since it is the user's clipboard.
const TYPE_LIMIT = 8000;

function psLiteral(s) { return `'${String(s).replace(/'/g, "''")}'`; }

/** The Windows clipboard, through PowerShell - the same thing Ctrl+C puts there. */
function clipboard(args) {
    const script = `$ErrorActionPreference='Stop'; for($attempt=0;$attempt -lt 8;$attempt++){try{ ${args}; exit 0 }catch{if($attempt -eq 7){Write-Error $_; exit 1}; Start-Sleep -Milliseconds 250}}`;
    const r = spawnSync('powershell.exe', ['-STA', '-NoProfile', '-NonInteractive', '-Command', script],
                        { encoding: 'utf8', timeout: 30000 });
    if (r.error) throw r.error;
    if (r.status !== 0) throw new Error(String(r.stderr || '').trim() || `powershell exited ${r.status}`);
    return String(r.stdout || '');
}

/**
 * Paste the prompt in, the way a person would.
 *
 * The text goes to a temp file first: a 22K string on a PowerShell command line
 * is a quoting accident waiting to happen, and `-EncodedCommand` has its own
 * limits. The file is written as UTF-8 without a BOM - with one, the first
 * character of every prompt would arrive as a stray glyph.
 */
async function pastePrompt(page, prompt, sel) {
    const tmp = path.join(os.tmpdir(), `aistudio_prompt_${process.pid}.txt`);
    const keep = tmp + '.saved';
    fs.writeFileSync(tmp, prompt, 'utf8');

    // The clipboard is the user's, not ours. Put back what was there - from a
    // file, because a 22K clipboard read through a command line is the same
    // quoting problem in reverse.
    let saved = false;
    try {
        const was = clipboard('Get-Clipboard -Raw');
        if (was && was.trim()) { fs.writeFileSync(keep, was, 'utf8'); saved = true; }
    } catch (e) { /* nothing on it, or locked: nothing to restore */ }

    try {
        clipboard(`Set-Clipboard -Value ([IO.File]::ReadAllText(${psLiteral(tmp)}, ` +
                  `[Text.Encoding]::UTF8))`);
        await sleep(300);
        await focusComposer(page, sel);
        await page.keyboard.down('Control');
        await page.keyboard.press('KeyV');
        await page.keyboard.up('Control');
        await sleep(800);
    } finally {
        try { fs.unlinkSync(tmp); } catch (e) { /* gone already */ }
        if (saved) {
            try {
                clipboard(`Set-Clipboard -Value ([IO.File]::ReadAllText(${psLiteral(keep)}, ` +
                          `[Text.Encoding]::UTF8))`);
            } catch (e) { /* the clipboard is not worth failing a film over */ }
            try { fs.unlinkSync(keep); } catch (e) { /* gone already */ }
        }
    }
}

async function submitPrompt(page, prompt, sel) {
    const el = await step('find the composer element', () => page.$(sel));
    if (!el) throw new Error(`the AI Studio composer (${sel}) went away before the prompt ` +
                             `could be typed into it`);
    const focused = await step('focus the composer', () => focusComposer(page, sel));
    if (!focused) log('the composer would not take focus - typing anyway and checking the box');
    await sleep(300);

    let got = null;
    if (prompt.length >= TYPE_LIMIT) {
        try {
            // AI Studio converts a large Ctrl+V into an inline media attachment,
            // leaving the textarea empty. Insert plain text without clipboard.
            const client = await step('open plain-text input session', () => page.createCDPSession());
            try {
                await page.keyboard.down('Control');
                await page.keyboard.press('KeyA');
                await page.keyboard.up('Control');
                await page.keyboard.press('Backspace');
                await step(`insert ${prompt.length} characters as plain text`, () => client.send('Input.insertText', { text: prompt }));
                await sleep(600);
            } finally { await client.detach().catch(() => {}); }
        } catch (e) {
            log(`plain-text input failed; retrying editor input: ${String(e.message).split('\n')[0]}`);
            await focusComposer(page, sel);
            await page.keyboard.down('Control');
            await page.keyboard.press('KeyA');
            await page.keyboard.up('Control');
            await page.keyboard.press('Backspace');
        }
        got = await boxLen(page, sel);
        if (got === null || got < prompt.length * 0.9) {
            log(`the paste left ${got === null ? 'an unreadable box' : `${got} of ` +
                `${prompt.length} characters`} - typing it in instead`);
        }
    }

    if (got === null || got < prompt.length * 0.9) {
        const client = await step('open a CDP session', () => page.createCDPSession());
        try {
            await focusComposer(page, sel);
            await page.keyboard.down('Control');
            await page.keyboard.press('KeyA');
            await page.keyboard.up('Control');
            await page.keyboard.press('Backspace');
            await step(`insert ${prompt.length} characters`, () => client.send('Input.insertText', { text: prompt }));
        } finally { await client.detach().catch(() => {}); }
        await sleep(600);
        got = await step('read the box back', () => boxLen(page, sel));
    }
    if (got === null) {
        throw new Error('the AI Studio composer would not say how much text it is holding ' +
                        '(the page stopped answering) - retrying with a fresh go');
    }
    if (got < prompt.length * 0.9) {
        log(`the box took ${got} of ${prompt.length} characters - inserting directly`);
        const w = await step('write the value directly', () => writeValue(page, sel, prompt));
        if (!w.ok) {
            throw new Error('the AI Studio composer stopped answering while the prompt was ' +
                            'being written into it - retrying with a fresh go');
        }
        await sleep(600);
        const again = await step('read the box back again', () => boxLen(page, sel));
        if (again === null || again < prompt.length * 0.9) {
            throw new Error(`the prompt would not go into the AI Studio composer ` +
                            `(${again === null ? 'it could not be read back' : `${again} of ` +
                             `${prompt.length} characters landed`})`);
        }
    }

    // CTRL+ENTER, not Enter. AI Studio's Run button carries the class
    // `ctrl-enter-submits` and prints the shortcut on its face (Run / Ctrl / ⏎);
    // a bare Enter only breaks the line. This cost a real probe run: the prompt
    // sat in a full composer looking submitted while nothing was ever sent.
    //
    // Whether it worked is read from the BOX, not from the page. An accepted
    // prompt empties the composer in the same instant (watched second by second:
    // 33 characters in, 0 out, one second later). Waiting instead for a Stop
    // button or the first words of an answer is what made an earlier version take
    // twenty seconds to notice a submit that had already happened twenty seconds
    // earlier.
    await page.keyboard.down('Control');
    await page.keyboard.press('Enter');
    await page.keyboard.up('Control');
    if (await step('Ctrl+Enter', () => sent(page, prompt))) return;

    // A build with the shortcut off still has the Run button. Each candidate is
    // given its own chance and checked before the next is tried, because the
    // first match on the page can be a disabled copy of the button in a panel
    // that is not open - and clicking that one looks exactly like a click that
    // worked.
    for (const b of SEND_BUTTONS) {
        const btn = await page.$(b);
        if (!btn) continue;
        log(`Ctrl+Enter did not empty the box - trying ${b}`);
        // DOM click first, one real mouse click second - and never Puppeteer's
        // ElementHandle.click, for the reason in focusComposer.
        const dom = await safeEval(page, (s) => {
            const e = document.querySelector(s);
            if (!e) return null;
            e.click();
            const r = e.getBoundingClientRect();
            return (r.width > 4 && r.height > 4)
                ? { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) } : null;
        }, b);
        if (dom.ok && dom.value) {
            await sleep(500);
            if (await sent(page, prompt)) return;
            await page.mouse.click(dom.value.x, dom.value.y).catch(() => {});
        }
        if (await sent(page, prompt)) return;
    }
    throw new Error('the prompt was typed into AI Studio but never left the composer ' +
                    '(the box still holds it after Ctrl+Enter and the send button)');
}

/**
 * Did the prompt actually go? The composer emptying is the signal.
 *
 * A refusal also empties it - AI Studio takes the prompt and then fails - so this
 * says "it was sent", not "it was answered". That is the question being asked
 * here; whether an answer came back is `waitForAnswer`'s.
 */
async function sent(page, prompt) {
    const until = Date.now() + SUBMIT_GRACE_MS;
    while (Date.now() < until) {
        const s = await read(page);
        if (s.boxLen !== null && s.boxLen < prompt.length * 0.1) return true;
        if (s.running) return true;
        await sleep(500);
    }
    return false;
}

/**
 * Wait for the stream to finish and return the answer text.
 *
 * "Finished" is the Stop button going away AND the text holding still for two
 * polls. The button alone is not enough: between the click on Run and the button
 * appearing there is a moment where nothing is running and the text is still the
 * previous turn's. Two agreeing polls span roughly four seconds of silence,
 * which a stream that is genuinely still writing does not produce.
 *
 * `base` is the conversation as it was before the prompt was sent. Nothing that
 * was already on screen counts as the answer.
 *
 * Never throws for a refusal. A refusal is a normal outcome of talking to AI
 * Studio and the caller decides whether to try again; only a timeout is an
 * error, because that is the case where the driver itself is stuck.
 */
async function waitForAnswer(page, base) {
    const deadline = Date.now() + ANSWER_TIMEOUT_MS;
    let last = '', stable = 0, sawRunning = false, sawAnswer = false, refused = 0;
    const startedAt = Date.now();
    while (Date.now() < deadline) {
        const s = await read(page);
        if (s.running) sawRunning = true;
        if (isFresh(s, base)) sawAnswer = true;
        if (isFresh(s, base) && !s.running && TOOL_LIMIT_RE.test(s.text) && !s.text.includes('{')) {
            return { ok: false, error: s.text.slice(0, 200) };
        }
        if (isFresh(s, base) && !s.running && require('./aistudio_response').completeAnswer(s.text)) {
            if (s.text === last) {
                if (++stable >= 2) return { ok: true, text: s.text };
            } else { last = s.text; stable = 0; }
            refused = 0;
        } else {
            last = ''; stable = 0;
            // The refusal is given a few seconds to be followed by an answer
            // before it is believed. It is not, in practice - but treating a
            // toast as the final word and throwing away an answer that was
            // already on its way would be worse than waiting three polls.
            if (s.error) {
                if (++refused >= 3) return { ok: false, error: s.error };
            } else refused = 0;
        }

        // THE WEDGE. Seen after a very large prompt was typed into the composer:
        // the box emptied (so the prompt went), no turn was ever created, nothing
        // ever started, and no error was shown - and from then on EVERY prompt in
        // that conversation did the same, including a 33-character one, until the
        // tab was reloaded. The client was stuck, not the account.
        //
        // A reload is the cure and it is safe here: the conversation lives on the
        // server and comes back with it. It is reported as a failure so the
        // caller's retry sends the prompt again, into a tab that works.
        if (!sawRunning && !sawAnswer && !s.error && Date.now() - startedAt > WEDGE_MS) {
            log(`the prompt was accepted but nothing has started after ` +
                `${Math.round(WEDGE_MS / 1000)}s - reloading the stuck tab`);
            await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
            await sleep(5000);
            return { ok: false, error: 'the page stopped responding to prompts and was reloaded' };
        }
        await sleep(2000);
    }
    throw new Error(
        `AI Studio did not finish within ${Math.round(ANSWER_TIMEOUT_MS / 60000)} minute(s)` +
        (sawRunning ? ' - it was still writing when the wait ran out.' : ' - it never started writing.'));
}

/**
 * One prompt, one answer. Serialised: callers may fire concurrently but the
 * browser sees one at a time.
 *
 * A refusal is retried here, not by the caller, for the same reason the API path
 * rotates keys on a 503: the failure is the server's and the next attempt
 * usually answers. Each attempt starts a fresh chat, which also clears the
 * refusal off the screen - otherwise the next attempt's very first poll would
 * find the last attempt's error message and give up on it.
 */
function askWeb(prompt, opts = {}) {
    const run = () => askWebWithRetries(prompt, opts);
    const next = _queue.then(run, run);
    _queue = next.then(() => {}, () => {});
    return next;
}

/**
 * A refusal from the server, and a page that stops answering, are the same kind
 * of thing here: transient, not the caller's fault, and normally cured by asking
 * again. Both are retried. Being signed out is neither, so it is passed straight
 * up rather than repeated three times.
 */
async function askWebWithRetries(prompt, opts = {}) {
    const tries = Math.max(1, Number(opts.tries || WEB_TRIES));
    let lastError = '';
    for (let attempt = 1; attempt <= tries; attempt++) {
        let r;
        try {
            const retryPrompt = TOOL_LIMIT_RE.test(lastError)
                ? prompt + '\n\nRECOVERY FROM TOOL LIMIT: Use observations of this source already available in this chat to finish the requested JSON. Do not repeat searches or video retrieval. If the source was never accessible, state that clearly instead of inventing its contents.'
                : prompt;
            r = await askWebOnce(retryPrompt, opts);
        } catch (e) {
            if (/not signed into Google/i.test(e.message)) throw e;
            r = { ok: false, error: e.message };
        }
        if (r.ok) return r.text;
        lastError = r.error;
        if (attempt < tries) {
            const wait = 15000 * attempt;
            log(`AI Studio request failed ("${r.error}") - attempt ${attempt + 1} of ${tries} in ${wait / 1000}s`);
            await sleep(wait);
        }
    }
    throw new Error(`AI Studio refused this prompt ${tries} time(s) in a row: ${lastError}\n` +
                    `It usually answers on a retry. If it keeps refusing, open the AI Studio ` +
                    `window and send one message by hand to check the account is still fine.`);
}

async function askWebOnce(prompt, opts = {}) {
    const page = await step('attach to the AI Studio tab', () => getPage());
    // DO NOT RELOAD THE PAGE BEFORE A PROMPT. This is the whole reason the first
    // version of this file kept getting "Failed to generate content: permission
    // denied. Please try again" while the same prompt, pasted by hand into the
    // same window, answered normally.
    //
    // Measured, not guessed: with a `goto(/prompts/new_chat)` before the submit,
    // a one-line prompt ("Reply with exactly one word: PONG") was refused every
    // single time, within one second of Ctrl+Enter. With the page left alone and
    // the prompt put into the conversation that is already open, the same
    // keystrokes returned a full five-scene breakdown of a YouTube short with the
    // model's own citations attached. A refusal that arrives in one second is not
    // a busy server - it is this session being turned away, and a freshly
    // reloaded chat is what turns it away.
    //
    // So the page is opened once, and after that every prompt is a turn in the
    // conversation that is already on screen. `newChat: true` asks the app itself
    // for a new chat (its own New chat control, a real click) rather than
    // reloading - which is what a batch wants between films.
    if (opts.newChat === true) {
        const fresh = await step('start a fresh chat', () => startNewChat(page));
        if (!fresh) throw new Error('A fresh AI Studio chat could not be confirmed. No new video prompt was submitted; open a blank New chat and retry.');
    }
    _readState = { stuck: 0 };
    await step('wait for any old refusal to clear', () => waitErrorClear(page));
    const boot = Date.now() + BOOT_MS;
    let sel = null;
    while (Date.now() < boot) {
        if (isSignInUrl(page.url())) throw new Error(SIGNED_OUT);
        sel = await findComposer(page);
        if (sel) break;
        await sleep(1000);
    }
    if (!sel) {
        if (isSignInUrl(page.url())) throw new Error(SIGNED_OUT);
        const body = await page.evaluate(() => document.body.innerText.slice(0, 400)).catch(() => '');
        throw new Error(`no composer on the AI Studio page (${page.url()}).\n` +
                        `The page says: ${body.replace(/\s+/g, ' ').slice(0, 200)}`);
    }
    const model = await readModel(page);
    // The conversation as it stands before we send. A new chat is empty on every
    // run so far, but this is what stops a leftover answer from being handed back
    // as the answer to a prompt that has not even been written yet.
    const base = await step('read the conversation as it stands', () => read(page));
    if (base.count) log(`${base.count} earlier answer(s) still on screen - waiting for a new one`);
    log(`composer: ${sel}${model ? `   model: ${model}` : ''}   prompt: ${prompt.length} chars`);
    await submitPrompt(page, prompt, sel);
    const r = await step('wait for the answer', () => waitForAnswer(page, base));
    if (r.ok) log(`answer: ${r.text.length} chars`);
    return r;
}

// ── what the GUI and the CLI ask ────────────────────────────────────────────

/**
 * Is the browser up, and is it signed in? Used for the "AI Studio" side of the
 * toggle, so a user who has not signed in yet is told that before a batch starts
 * rather than after the first film has failed.
 *
 * `launch: false` - a status check must never open a window on its own.
 */
async function webStatus({ launch = false } = {}) {
    const out = { port: PORT, profile: PROFILE_DIR, up: false, signedIn: false, composer: false, model: '' };
    try {
        out.up = await ensureBrowser({ launch });
        if (!out.up) return out;
        const page = await getPage();
        out.signedIn = !isSignInUrl(page.url());
        if (out.signedIn) {
            const sel = await findComposer(page);
            out.composer = !!sel;
            if (sel) out.model = await readModel(page);
        }
    } catch (e) {
        out.error = e.message;
    }
    return out;
}

function close() {
    if (_browser && _browser.connected) { try { _browser.disconnect(); } catch {} }
    _browser = null;
}

module.exports = {
    askWeb, webStatus, close,
    ensureBrowser, getPage, getBrowser, read, snapshot,
    SIGNED_OUT, PORT, PROFILE_DIR,
    COMPOSERS, SEND_BUTTONS, STOP_BUTTONS, ANSWER_TIMEOUT_MS, TOOL_LIMIT_RE, ERROR_RE,
};

// ── by hand ─────────────────────────────────────────────────────────────────

if (require.main === module) {
    const argv = process.argv.slice(2);
    const val = (n) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : null; };
    (async () => {
        if (argv.includes('--status')) {
            const s = await webStatus({ launch: argv.includes('--launch') });
            console.log(JSON.stringify(s, null, 2));
            if (!s.up) console.log('\nThe browser is not running. Add --launch to start it.');
            else if (!s.signedIn) console.log('\n' + SIGNED_OUT);
            else if (!s.composer) console.log('\nSigned in, but no composer was found on the page.');
            close();
            return;
        }
        // Salvage: print whatever the model last said, without asking anything.
        // A call that was answered but whose answer then failed to parse (or a
        // process that died mid-run) has already been paid for - the answer is
        // sitting in the chat and this reads it back out.
        if (argv.includes('--last')) {
            const s = await read(await getPage());
            if (val('--out')) {
                fs.writeFileSync(path.resolve(val('--out')), s.text, 'utf8');
                console.log(`${s.text.length} characters written to ${path.resolve(val('--out'))}`);
            } else {
                process.stdout.write(s.text);
            }
            close();
            return;
        }
        const ask = val('--ask') || (val('--file') ? fs.readFileSync(val('--file'), 'utf8') : null);
        if (!ask) {
            console.log('Usage:\n' +
                        '  node ask_web.js --status [--launch]   is the browser up and signed in?\n' +
                        '  node ask_web.js --ask "..."           one prompt, one answer\n' +
                        '  node ask_web.js --file prompt.txt     same, the prompt read from a file\n' +
                        '                      [--new-chat]      click New chat first (one film per chat)\n' +
                        '                      [--tries N]       attempts before giving up (default 3)\n' +
                        '  node ask_web.js --last [--out f.txt]  print the model\'s newest answer, asking nothing\n' +
                        '\nBy default the prompt is added to the conversation already open. Reloading\n' +
                        'the page before a prompt is what gets refused as "permission denied".');
            return;
        }
        const opt = { newChat: argv.includes('--new-chat') };
        if (val('--tries')) opt.tries = Number(val('--tries'));
        const text = await askWeb(ask, opt);
        console.log('\n--- answer ---\n' + text);
        close();
    })().catch((e) => { console.error('\n' + e.message); process.exit(1); });
}
