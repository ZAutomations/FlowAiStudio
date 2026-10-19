const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const RI = require('./reference_image_step');

async function findUploadButton(page) {
    const handle = await page.evaluateHandle(() => {
        const visible = el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
        return [...document.querySelectorAll('button, [role="menuitem"]')].find(el => {
            if (!visible(el)) return false;
            const label = el.querySelector('.label, .upload-text');
            const text = (label?.textContent || el.innerText || '').trim();
            return /^(?:upload|upload media)$/i.test(text);
        }) || null;
    });
    const button = handle.asElement();
    if (!button) await handle.dispose();
    return button;
}

async function openUploadChooser(page, log = () => {}) {
    return openAcknowledgedUploadChooser(page, log);
}

async function openAcknowledgedUploadChooser(page, log) {
    // Puppeteer's waitForFileChooser starts asynchronous interception setup.
    // Await Chrome's ACK explicitly before any Upload click can open the dialog.
    const client = await page.target().createCDPSession();
    let event = null, ended = false;
    const opened = data => { event = data; };
    client.on('Page.fileChooserOpened', opened);
    const cleanup = async () => {
        if (ended) return;
        ended = true;
        client.off('Page.fileChooserOpened', opened);
        await client.send('Page.setInterceptFileChooserDialog', { enabled: false }).catch(() => {});
        await client.detach().catch(() => {});
    };
    try {
        await page.bringToFront();
        await client.send('Page.enable');
        await client.send('Page.setInterceptFileChooserDialog', { enabled: true });
        log('Chrome upload chooser interception confirmed.');
        await page.waitForFunction(() => {
            const visible = el => {
                const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0;
            };
            const buttons = [...document.querySelectorAll('button')];
            const hasUpload = buttons.some(el => visible(el) && /^(upload|upload media)$/i.test(
                (el.querySelector('.label, .upload-text')?.textContent || el.innerText || '').trim()));
            return ![...document.querySelectorAll('flow-loading-page')].some(visible)
                && (hasUpload || [...document.querySelectorAll('button[aria-label="Add media menu"], button[aria-label="Add ingredients to the prompt box"]')].some(visible));
        }, { timeout: 90000 });
        const deadline = Date.now() + 30000;
        let clickedAt = 0, menuOpenedAt = 0;
        while (!event && Date.now() < deadline) {
            if (Date.now() - clickedAt >= 1500) {
                const action = await page.evaluate(usePromptMenu => {
                    const visible = el => {
                        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                        return el.isConnected && r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                    };
                    const buttons = [...document.querySelectorAll('button, [role="menuitem"]')];
                    const upload = buttons.find(el => visible(el) && /^(upload|upload media)$/i.test(
                        (el.querySelector('.label, .upload-text')?.textContent || el.innerText || '').trim()));
                    if (upload) { upload.click(); return 'upload'; }
                    const labels = usePromptMenu ? ['Add ingredients to the prompt box']
                        : ['Add media menu', 'Add ingredients to the prompt box'];
                    const add = labels.map(label => buttons.find(el => visible(el) && el.getAttribute('aria-label') === label)).find(Boolean);
                    if (add && add.getAttribute('aria-expanded') !== 'true') { add.click(); return 'menu'; }
                    return 'waiting';
                }, menuOpenedAt > 0 && Date.now() - menuOpenedAt > 5000);
                if (action === 'menu' && !menuOpenedAt) menuOpenedAt = Date.now();
                if (action === 'upload') {
                    clickedAt = Date.now();
                    await new Promise(r => setTimeout(r, 600));
                    if (!event) {
                        const fresh = await findUploadButton(page);
                        if (fresh) {
                            try {
                                const point = await fresh.evaluate(el => {
                                    const r = el.getBoundingClientRect();
                                    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
                                });
                                await page.mouse.click(point.x, point.y);
                            }
                            catch (e) { if (!/detached|not clickable|not an Element/i.test(e.message)) throw e; }
                            finally { await fresh.dispose(); }
                        }
                    }
                }
            }
            if (!event) await new Promise(r => setTimeout(r, 150));
        }
        if (!event?.backendNodeId) throw Error('Upload did not open a file-input chooser after Chrome interception was confirmed.');
        log('Upload file chooser opened.');
        const node = event.backendNodeId;
        return {
            isMultiple: () => event.mode === 'selectMultiple',
            accept: async files => {
                try { await client.send('DOM.setFileInputFiles', { backendNodeId: node, files }); }
                finally { await cleanup(); }
            },
            cancel: async () => {
                try { await client.send('DOM.setFileInputFiles', { backendNodeId: node, files: [] }); }
                finally { await cleanup(); }
            },
        };
    } catch (e) { await cleanup(); throw e; }
}

async function uploadSavedReference(page, ref, log = () => {}, deps = {}) {
    const GR = require('./generate_refs');
    const project = page.url().match(/\/project\/([^/?#]+)/)?.[1];
    if (!project) throw Error('Open a Flow project before uploading saved references.');
    await page.bringToFront();
    await page.waitForFunction(() => ![...document.querySelectorAll('flow-loading-page')].some(el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0;
    }), { timeout: 90000 });
    const hash = crypto.createHash('sha256').update(fs.readFileSync(ref.localFile)).digest('hex');
    const marker = path.join(__dirname, 'logs', 'saved_couple_uploads', project + '.json');
    let state = {};
    if (fs.existsSync(marker)) state = JSON.parse(fs.readFileSync(marker, 'utf8'));
    const present = await page.evaluate(name => [...document.querySelectorAll('flow-image-tile')]
        .some(t => (t.querySelector('.footer-title')?.textContent || t.textContent || '').trim().toLowerCase() === name.toLowerCase()), ref.name);
    if (state[ref.name] === hash && present) return { ok: true, reused: true };
    const off = await GR.setAgent(page, false);
    if (!off.ok) throw Error(`Could not disable Agent Mode before uploading ${ref.name}: ${off.why}`);
    const before = await page.evaluate(RI.referenceState);
    // A previous attempt may have uploaded successfully before its menu/rename
    // step failed. Flow deduplicates that file, so waiting for a NEW tile would
    // never complete. Recover the uniquely named original upload instead.
    const recover = !state[ref.name] ? await page.evaluate(filename => {
        const matches = [...document.querySelectorAll('flow-image-tile')].filter(tile => {
            const title = tile.querySelector('.footer-title')?.textContent?.trim();
            const image = tile.querySelector('img');
            return title === filename && image?.complete && image.naturalWidth > 0;
        });
        if (matches.length !== 1) return -1;
        const more = [...document.querySelectorAll('button[aria-label="More options"]')]
            .filter(b => !b.closest('.header-right-container, .header-desktop-main-row') && b.closest('[class*=hover-overlay]'));
        return more.indexOf(matches[0].querySelector('button[aria-label="More options"]'));
    }, path.basename(ref.localFile)) : -1;
    if (recover >= 0) {
        log(`Recovering already uploaded ${path.basename(ref.localFile)}; renaming to ${ref.name}...`);
        const renamed = await (deps.rename || GR.renameNewest)(page, ref.name, recover);
        if (!renamed.ok) return renamed;
        fs.mkdirSync(path.dirname(marker), { recursive: true });
        state[ref.name] = hash;
        fs.writeFileSync(marker, JSON.stringify(state, null, 2));
        return { ok: true, reused: true };
    }
    log(`Opening + > Upload for saved ${ref.name} sheet...`);
    let fileChooser;
    try { fileChooser = await openUploadChooser(page, log); }
    catch (e) { return { ok: false, why: `Upload file chooser failed: ${e.message}` }; }
    await fileChooser.accept([ref.localFile]);
    log(`Selected ${path.basename(ref.localFile)}; waiting for the uploaded image...`);
    const waitImage = deps.waitImage || RI.waitForReferenceImage;
    const image = await waitImage(page, before, 120);
    if (!image.ok) return image;
    const rename = await (deps.rename || GR.renameNewest)(page, ref.name, image.tileIndex);
    if (!rename.ok) return rename;
    fs.mkdirSync(path.dirname(marker), { recursive: true });
    state[ref.name] = hash;
    fs.writeFileSync(marker, JSON.stringify(state, null, 2));
    log(`Uploaded saved ${ref.name} sheet and verified its tile name.`);
    return { ok: true };
}
module.exports = { uploadSavedReference, openUploadChooser };
