#!/usr/bin/env node
/**
 * FLOW PROJECT SETUP  (the Agent Mode pre-step)
 * =============================================
 * Agent Mode runs inside a Flow PROJECT, and until now making that project was
 * the one manual step: click New project, leave the browser on it, then run the
 * agent. This script does that step, so a batch can give every film its own
 * fresh project - which also keeps each film's clips alone in their own grid,
 * instead of piling every film into one project where the downloader could mix
 * them up.
 *
 * FIRST RUN IS A PROBE. Flow's home screen has not been recorded in this repo,
 * so run `--probe` once with Flow open, send the dump, and the "New project"
 * selector gets pinned. Until then the create step matches a button by its
 * visible text/aria-label.
 *
 * Usage:
 *   node project_setup.js --probe              # dump the home screen, change nothing
 *   node project_setup.js                      # create a project, print its URL
 *   node project_setup.js --no-create          # just report the current project URL
 *   node project_setup.js --instructions f.txt # also paste Agent Instructions (best effort)
 *
 * Prints, for the caller to parse:
 *   project_url: https://flow.google.com/project/<id>
 *   project_id : <id>
 *
 * Flags:
 *   --cdp N          CDP port (default 9222)
 *   --probe          inspect and dump only; create nothing
 *   --no-create      do not click anything; just report the current project
 *   --timeout N      seconds to wait for the new project URL (default 60)
 *   --instructions F paste the contents of file F into the Agent Instructions panel
 */

const puppeteer = require('puppeteer');
const fs = require('fs');

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
function ts() { return new Date().toTimeString().slice(0, 8); }
function log(msg) { console.log(`[${ts()}] ${msg}`); }
function banner(msg) { console.log(`\n${'='.repeat(70)}\n${msg}\n${'='.repeat(70)}`); }

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
const PROBE = !!flag('--probe', false);
const NO_CREATE = !!flag('--no-create', false);
const TIMEOUT = num('--timeout', 60) * 1000;
const INSTRUCTIONS_FILE = typeof flag('--instructions') === 'string' ? flag('--instructions') : '';

// The words a New-project control tends to use. Deliberately broad, because the
// first live probe may reveal Flow's exact wording.
const NEW_PROJECT_RX = /new project|create project|start a project|blank project|new video|create video|create\b|compose|new\b/i;

// ── pure helpers (exported for the tests) ------------------------------------
function projectIdFromUrl(url) {
    const m = String(url || '').match(/\/project\/([0-9a-f-]{8,})/i);
    return m ? m[1] : '';
}

// Pick the most likely New-project control from a list of {label, area, visible}.
// Biggest visible match wins, because the real button is a large call to action
// and the matching crumbs ("Create" inside a menu) are small.
function chooseNewProject(candidates) {
    const good = (candidates || []).filter((c) => c && c.visible !== false && NEW_PROJECT_RX.test(c.label || ''));
    if (!good.length) return null;
    good.sort((a, b) => (b.area || 0) - (a.area || 0));
    return good[0].label;
}

// ── page helpers -------------------------------------------------------------
async function flowPage(browser) {
    const pages = await browser.pages();
    return pages.find((p) => /flow\.google\.com/i.test(p.url() || '')) || null;
}

async function goHome(page) {
    if (!/^https:\/\/flow\.google\.com\/?($|\?)/i.test(page.url() || '')) {
        log('Going to the Flow project grid...');
        await page.goto('https://flow.google.com/', { waitUntil: 'domcontentloaded', timeout: 120000 });
    }
    await wait(4000);
}

async function listControls(page) {
    return await page.evaluate(() => {
        const out = [];
        const els = document.querySelectorAll('button, a, [role="button"], [role="menuitem"], [class*=project]');
        for (const el of els) {
            const r = el.getBoundingClientRect();
            const text = (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 70);
            const aria = el.getAttribute('aria-label') || '';
            if (!text && !aria) continue;
            out.push({
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute('role') || '',
                aria,
                text,
                area: Math.round(r.width * r.height),
                visible: r.width > 2 && r.height > 2,
            });
        }
        return out;
    });
}

async function clickNewProject(page) {
    const label = await page.evaluate((src) => {
        const rx = new RegExp(src, 'i');
        const els = document.querySelectorAll('button, a, [role="button"], [role="menuitem"]');
        const good = [];
        for (const el of els) {
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            const label = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || ''))
                .replace(/\s+/g, ' ').trim();
            if (!label || !rx.test(label)) continue;
            good.push({ el, label, area: r.width * r.height });
        }
        if (!good.length) return null;
        good.sort((a, b) => b.area - a.area);
        const pick = good[0];
        pick.el.scrollIntoView({ block: 'center' });
        pick.el.click();
        return pick.label;
    }, NEW_PROJECT_RX.source);
    return label;
}

async function waitForProjectUrl(browser, timeoutMs, excluded = new Set()) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        for (const p of await browser.pages()) {
            const id = projectIdFromUrl(p.url());
            if (id && !excluded.has(id)) return { page: p, url: `https://flow.google.com/project/${id}`, id };
        }
        await wait(1200);
    }
    return null;
}

// Best-effort: open the Agent Instructions panel (the spark button) and paste a
// block. The panel has not been probed, so a failure is a warning, not an exit.
async function setInstructions(page, text) {
    try {
        const opened = await page.evaluate(() => {
            const rx = /agent instructions|instructions/i;
            const el = [...document.querySelectorAll('button, [role="button"]')]
                .find((b) => rx.test(((b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')).trim()));
            if (!el) return false;
            el.click();
            return true;
        });
        if (!opened) { log('  (Agent Instructions button not found - skipping)'); return false; }
        await wait(1500);
        const typed = await page.evaluate((body) => {
            const box = document.querySelector('.ProseMirror, [contenteditable="true"], textarea');
            if (!box) return false;
            box.focus();
            if (box.tagName === 'TEXTAREA') {
                box.value = body;
                box.dispatchEvent(new Event('input', { bubbles: true }));
            } else {
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, body);
            }
            return true;
        }, text);
        if (!typed) { log('  (no instructions input found - skipping)'); return false; }
        await wait(800);
        await page.keyboard.press('Escape');
        return true;
    } catch (e) {
        log(`  (instructions step skipped: ${e.message.slice(0, 60)})`);
        return false;
    }
}

async function renameProject(page, title) {
    title = String(title || '').trim();
    if (!title) throw Error('Story title is required to rename the new Flow project.');
    const visible = el => !!(el.getBoundingClientRect().width && el.getBoundingClientRect().height);
    // Scope to the project menu: never open an asset or global settings menu.
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(el =>
        /more options for the project/i.test(el.getAttribute('aria-label') || '') && el.getBoundingClientRect().width), {timeout: 30000});
    const menu = await page.$('button[aria-label="More options for the project"]');
    if (!menu) throw Error('Project options button not found; rename stopped.');
    await menu.click();
    await page.waitForFunction(() => [...document.querySelectorAll('[role="menuitem"],button,.label')].some(el =>
        el.textContent.trim() === 'Rename' && el.getBoundingClientRect().width), {timeout: 10000});
    await page.evaluate(() => {
        const el = [...document.querySelectorAll('[role="menuitem"],button,.label')].find(el =>
            el.textContent.trim() === 'Rename' && el.getBoundingClientRect().width);
        el.click();
    });
    const input = await page.waitForFunction(() => {
        const dialog = document.querySelector('[role="dialog"],mat-dialog-container');
        const fields = [...(dialog || document).querySelectorAll('input:not([type="hidden"]),textarea')]
            .filter(el => el.getBoundingClientRect().width && !/search/i.test(el.getAttribute('placeholder') || ''));
        return fields.find(el => el === document.activeElement) || (dialog && fields[0]) || false;
    }, {timeout: 10000});
    await input.asElement().click({clickCount: 3});
    await page.keyboard.down('Control'); await page.keyboard.press('A'); await page.keyboard.up('Control');
    await page.keyboard.insertText(title);
    await page.keyboard.press('Enter');
    // Verify committed header text, not merely the text entered in a dialog.
    await page.waitForFunction(expected => {
        const dialog = document.querySelector('[role="dialog"],mat-dialog-container');
        if (dialog && dialog.getBoundingClientRect().width) return false;
        return [...document.querySelectorAll('h1,h2,[role="heading"],nav input,header input,nav [title],header [title]')]
            .some(el => el.getBoundingClientRect().width && (el.value || el.textContent || el.title || '').trim() === expected);
    }, {timeout: 15000}, title);
    console.log('project_renamed: true');
    log('Flow project renamed to story title: ' + title);
}

if (require.main === module) (async () => {
    let browser;
    try {
        browser = await puppeteer.connect({
            browserURL: `http://127.0.0.1:${CDP_PORT}`, defaultViewport: null,
        });
    } catch (e) {
        console.error(`Could not connect to Chrome on CDP port ${CDP_PORT}.`);
        console.error('Start the automation browser first (START_CHROME_CDP.bat / the GUI), then retry.');
        process.exit(1);
    }

    const resumeUrl = flag('--project-url');
    if (resumeUrl && !/^https:\/\/flow\.google\.com\/project\/[a-zA-Z0-9-]+$/.test(resumeUrl)) throw Error('Invalid project URL.');
    if (resumeUrl) {
        let target = (await browser.pages()).find(p => p.url().split('?')[0] === resumeUrl);
        if (!target) { target = await browser.newPage(); await target.goto(resumeUrl, {waitUntil: 'domcontentloaded', timeout: 60000}); }
        console.log('project_url: ' + resumeUrl);
        await renameProject(target, flag('--title'));
        await browser.disconnect();
        return;
    }
    let page = process.argv.includes('--new-tab') ? await browser.newPage() : await flowPage(browser);
    if (!page) {
        log('No Flow tab found - opening one.');
        page = await browser.newPage();
        await page.goto('https://flow.google.com/', { waitUntil: 'domcontentloaded', timeout: 120000 });
    }

    if (PROBE) {
        await goHome(page);
        const controls = await listControls(page);
        banner('FLOW HOME - clickable / project affordances');
        console.log(`URL  : ${page.url()}`);
        for (const c of controls.filter((x) => x.visible).slice(0, 120)) {
            console.log(`  [${c.tag}${c.role ? ' role=' + c.role : ''}] aria="${c.aria}" "${c.text}"  (${c.area}px)`);
        }
        const guess = chooseNewProject(controls);
        console.log(`\nBest New-project guess: ${guess ? `"${guess}"` : '(none matched the text patterns)'}`);
        console.log('Send this dump back, and the selector gets pinned in project_setup.js.');
        await browser.disconnect();
        return;
    }

    if (NO_CREATE) {
        const id = projectIdFromUrl(page.url());
        if (!id) { console.error(`No project id in the current tab: ${page.url()}`); await browser.disconnect(); process.exit(2); }
        console.log(`project_url: https://flow.google.com/project/${id}`);
        console.log(`project_id : ${id}`);
        await browser.disconnect();
        return;
    }

    // ---- create -------------------------------------------------------------
    const existingProjects = new Set((await browser.pages()).map(p => projectIdFromUrl(p.url())).filter(Boolean));
    await goHome(page);
    const label = await clickNewProject(page);
    if (!label) {
        console.error('Could not find a New project / Create control on the Flow home.');
        console.error('Run:  node project_setup.js --probe   and send the dump so the selector can be pinned.');
        await browser.disconnect();
        process.exit(2);
    }
    log(`Clicked: "${label}"`);

    const found = await waitForProjectUrl(browser, TIMEOUT, existingProjects);
    if (!found) {
        console.error(`Timed out after ${TIMEOUT / 1000}s waiting for a project URL.`);
        await browser.disconnect();
        process.exit(3);
    }
    page = found.page;
    console.log(`project_url: ${found.url}`);
    if (flag('--title')) await renameProject(page, flag('--title'));

    if (INSTRUCTIONS_FILE) {
        let text = '';
        try { text = fs.readFileSync(INSTRUCTIONS_FILE, 'utf8').trim(); }
        catch (e) { console.error(`Could not read --instructions ${INSTRUCTIONS_FILE}: ${e.message}`); }
        if (text) {
            log('Pasting Agent Instructions...');
            await setInstructions(page, text);
        }
    }

    await wait(1000);
    console.log(`project_url: ${found.url}`);
    console.log(`project_id : ${found.id}`);
    await browser.disconnect();
})().catch((e) => { console.error('FAILED: ' + (e && e.message)); process.exit(1); });

async function createProject(browser, page) {
    const existing = new Set((await browser.pages()).map(p => projectIdFromUrl(p.url())).filter(Boolean));
    await goHome(page);
    if (!await clickNewProject(page)) throw Error('Could not find New project on the Flow home page.');
    const found = await waitForProjectUrl(browser, 60000, existing);
    if (!found) throw Error('Timed out waiting for the new Flow project.');
    return found;
}
module.exports = { projectIdFromUrl, chooseNewProject, NEW_PROJECT_RX, createProject, renameProject };
