// The compact Flow controls used ONLY for reference sheets. The film's video
// model still belongs to agent_mode.js and its generation-default settings.
const IMAGE_MODEL = 'Nano Banana Pro';
const IMAGE_RATIO = '16:9';
const ACTIVITY_WAIT_MS = 120000;
const ACTIVITY_RETRIES = 2;
const ACTIVITY_BLOCKED = 'UNUSUAL_ACTIVITY_BLOCKED';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

// Runs inside the page. Match the stable labels supplied by Flow, not Angular's
// numbered IDs. Ignore hidden copies and icon ligatures such as crop_16_9.
function compactControls(action) {
    const visible = el => {
        if (!el) return false;
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
    };
    const text = el => {
        if (!el) return '';
        const copy = el.cloneNode(true);
        copy.querySelectorAll('mat-icon').forEach(i => i.remove());
        return (copy.textContent || '').replace(/\s+/g, ' ').trim();
    };
    const key = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
    const radios = [...document.querySelectorAll('button[role="radio"]')].filter(visible);
    const label = el => text(el.querySelector('.toggle-text') || el);
    const image = radios.find(el => /^image$/i.test(label(el)));
    const panel = image && image.closest('.cdk-overlay-pane');
    const scope = panel || document;
    const ratio = [...scope.querySelectorAll('button[role="radio"]')]
        .find(el => visible(el) && label(el) === '16:9');
    const picker = [...scope.querySelectorAll('button[aria-label="Select model family"]')].find(visible);
    const summary = [...document.querySelectorAll('.settings-summary')].find(visible);
    if (action === 'state') return {
        image: !!image && image.getAttribute('aria-checked') === 'true',
        ratio: !!ratio && ratio.getAttribute('aria-checked') === 'true',
        model: text(picker),
        summary: text(summary),
        summaryLandscape: !!summary && [...summary.querySelectorAll('mat-icon')]
            .some(i => (i.textContent || '').trim() === 'crop_16_9'),
        open: !!image,
    };
    let target;
    if (action === 'open') target = summary && (summary.closest('button, [role="button"]') || summary);
    if (action === 'image') target = image;
    if (action === 'ratio') target = ratio;
    if (action === 'model') target = picker;
    if (action === 'pro') {
        target = [...document.querySelectorAll('.cdk-overlay-pane span.label, [role="menuitem"], [role="option"]')]
            .find(el => visible(el) && !el.closest('button[aria-label="Select model family"]')
                && key(text(el)) === 'nanobananapro');
        if (target) target = target.closest('button, [role="menuitem"], [role="option"]') || target;
    }
    if (!visible(target) || target.disabled || target.getAttribute('aria-disabled') === 'true') return null;
    const r = target.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}

async function configureReferenceImages(page, say = () => {}) {
    const state = () => page.evaluate(compactControls, 'state');
    const until = async (check, message) => {
        for (let n = 0; n < 40; n++) {
            if (await check()) return;
            await sleep(200);
        }
        throw new Error(`Reference image settings: ${message}. Nothing submitted.`);
    };
    const click = async action => {
        let point;
        await until(async () => !!(point = await page.evaluate(compactControls, action)), `cannot find ${action} control`);
        await page.mouse.click(point.x, point.y);
    };
    // A fresh project's composer can remount just after Agent is turned off.
    // Re-open if that remount discarded the first click, before touching Image.
    for (let attempt = 0; attempt < 3 && !(await state()).open; attempt++) {
        await click('open');
        await sleep(1000);
    }
    await click('image');
    await until(async () => (await state()).image, 'Image mode did not become selected');
    await click('ratio');
    await until(async () => (await state()).ratio, '16:9 did not become selected');
    await click('model');
    await click('pro');
    await until(async () => {
        const s = await state();
        return s.image && s.ratio && s.model.toLowerCase().replace(/[^a-z0-9]/g, '') === 'nanobananapro';
    }, 'Image / 16:9 / Nano Banana Pro could not be verified');
    // This compact popover applies immediately; it has no full-drawer Save.
    // Escape closes the compact menu on the current Flow layout. Do not click
    // the summary again here: on some builds that immediately reopens the menu
    // and leaves the next prompt insertion behind its popover.
    await page.keyboard.press('Escape');
    await sleep(500);
    await until(async () => {
        const s = await state();
        return /nano\s+banana\s+pro/i.test(s.summary) && s.summaryLandscape;
    }, 'settings summary did not confirm Nano Banana Pro and 16:9');
    say('Reference settings verified: Image / 16:9 / Nano Banana Pro.');
}

// A failed tile can have More options too. Count only completed image media,
// and remember existing assets/errors so a retry cannot rename an older tile.
function referenceState() {
    const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
    };
    const memory = window.__veoReferenceWatch || (window.__veoReferenceWatch = { ids: new WeakMap(), next: 0 });
    const id = el => {
        if (!memory.ids.has(el)) memory.ids.set(el, String(++memory.next));
        return memory.ids.get(el);
    };
    const more = [...document.querySelectorAll('button[aria-label="More options"]')]
        .filter(b => !b.closest('.header-right-container, .header-desktop-main-row') && b.closest('[class*=hover-overlay]'));
    const images = [], videos = [];
    const tiles = [...document.querySelectorAll('flow-image-tile, flow-video-tile')];
    // Older builds use an unlabelled wrapper around the per-asset menu.
    if (!tiles.length) for (const b of more) {
        let root = b.closest('[class*=hover-overlay]');
        for (let n = 0; n < 6 && root && !root.querySelector('img, video'); n++) root = root.parentElement;
        if (root && !tiles.includes(root)) tiles.push(root);
    }
    for (const tile of tiles) {
        const button = tile.querySelector('button[aria-label="More options"]');
        if (tile.tagName.toLowerCase() === 'flow-video-tile' || tile.querySelector('video')) {
            videos.push(id(tile));
            continue;
        }
        const image = [...tile.querySelectorAll('img')].find(im => im.complete && im.naturalWidth > 0);
        if (image && button && !tile.querySelector('[role="progressbar"], [class*=error-tile]')) {
            images.push({ key: image.currentSrc || image.src || id(tile), tileIndex: more.indexOf(button) });
        }
    }
    const errors = [];
    for (const el of document.querySelectorAll('[class*=error-tile], [role="alert"], [role="dialog"], mat-dialog-container, .mat-mdc-snack-bar-container')) {
        if (!visible(el)) continue;
        const text = [el.innerText || '', ...[...el.querySelectorAll('[title], [aria-label]')]
            .map(n => n.getAttribute('title') || n.getAttribute('aria-label') || '')].join(' ').trim();
        if (/unusual\s+activity|failed|something went wrong|usage limit/i.test(text)) errors.push({ key: id(el) + ':' + text, text });
    }
    // Some builds render the message directly on the page rather than a card.
    // Count occurrences so an old warning is not mistaken for a new failure.
    const activityCount = ((document.body.innerText || '').match(/unusual\s+activity/gi) || []).length;
    return { images, videos, errors, activityCount };
}

async function waitForReferenceImage(page, before, seconds, opts = {}) {
    const pause = opts.sleep || sleep;
    const now = opts.now || Date.now;
    const end = now() + seconds * 1000;
    const oldImages = new Set(before.images.map(x => x.key));
    const oldVideos = new Set(before.videos);
    const oldErrors = new Set(before.errors.map(x => x.key));
    let activityCount = before.activityCount;
    do {
        const state = await page.evaluate(referenceState);
        const errors = state.errors.filter(e => !oldErrors.has(e.key));
        const unusual = errors.find(e => /unusual\s+activity/i.test(e.text));
        if (unusual || state.activityCount > activityCount) return { ok: false, unusual: true, why: unusual ? unusual.text : 'We noticed unusual activity.' };
        // If a toast disappears then comes back with identical text, it is new.
        for (const key of oldErrors) if (!state.errors.some(e => e.key === key)) oldErrors.delete(key);
        activityCount = Math.min(activityCount, state.activityCount);
        if (errors.length) return { ok: false, why: errors[0].text };
        if (state.videos.some(k => !oldVideos.has(k))) return { ok: false, why: 'Flow created a video tile during reference image generation.' };
        const image = state.images.find(x => !oldImages.has(x.key) && x.tileIndex >= 0);
        if (image) return { ok: true, tileIndex: image.tileIndex };
        if (now() >= end) break;
        await pause(Math.min(3000, Math.max(0, end - now())));
    } while (now() <= end);
    return { ok: false, why: `No completed reference image after ${seconds}s.` };
}

// Google's guidance for this exact message is to wait a couple of minutes.
// Two retries, each after a full 120s pause; no account or browser switching.
async function withActivityWait(attempt, opts = {}) {
    const say = opts.log || (() => {}), pause = opts.sleep || sleep;
    for (let n = 0; n <= ACTIVITY_RETRIES; n++) {
        const result = await attempt(n);
        if (result.ok || !result.unusual) return result;
        if (n === ACTIVITY_RETRIES) {
            say(`${ACTIVITY_BLOCKED}: still blocked after ${ACTIVITY_RETRIES} retries. Stopping generation; try manually later and check VPN/proxy settings or contact Flow support.`);
            return { ...result, blocked: true };
        }
        say(`WAIT MODE: Flow reported unusual activity. Retrying this reference in 120 seconds (${n + 1}/${ACTIVITY_RETRIES}).`);
        for (let remaining = ACTIVITY_WAIT_MS; remaining > 0; remaining -= 30000) {
            await pause(Math.min(30000, remaining));
            if (remaining > 30000) say(`WAIT MODE: ${(remaining - 30000) / 1000} seconds remaining.`);
        }
    }
}

function referenceTimeoutMs(count, waitSeconds) {
    // Each sheet can take three complete attempts plus two cooldowns and UI
    // verification/renaming. The MCP process must not kill a legitimate wait.
    return 120000 + Math.max(1, count) * ((ACTIVITY_RETRIES + 1) * (waitSeconds * 1000 + 60000) + ACTIVITY_RETRIES * ACTIVITY_WAIT_MS);
}

module.exports = {
    IMAGE_MODEL, IMAGE_RATIO, ACTIVITY_WAIT_MS, ACTIVITY_RETRIES, ACTIVITY_BLOCKED,
    compactControls, configureReferenceImages, referenceState, waitForReferenceImage,
    withActivityWait, referenceTimeoutMs,
};
