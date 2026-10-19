// Installed in the page: follow the tile ancestors rather than one Flow CSS class.
function installGridScroller() {
    window.__veoGridScroller = () => {
        const tiles = [...document.querySelectorAll('flow-video-tile, flow-image-tile')];
        const votes = new Map();
        for (const tile of tiles) {
            for (let el = tile.parentElement; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0 || el.clientHeight < 80 || el.scrollHeight <= el.clientHeight + 2) continue;
                if (!/(auto|scroll|overlay)/.test(getComputedStyle(el).overflowY)) continue;
                votes.set(el, (votes.get(el) || 0) + 1);
                break;
            }
        }
        return [...votes].sort((a, b) => b[1] - a[1])[0]?.[0] || null;
    };
}
function gridMetrics() {
    const s = window.__veoGridScroller?.();
    return { top: s ? s.scrollTop : window.scrollY, client: s ? s.clientHeight : window.innerHeight,
        scroll: s ? s.scrollHeight : Math.max(document.documentElement.scrollHeight, document.body.scrollHeight),
        tag: s ? `${s.tagName}.${String(s.className || '')}` : 'window' };
}
function scrollGrid(y) {
    const s = window.__veoGridScroller?.();
    if (s) { s.scrollTop = y; s.dispatchEvent(new Event('scroll', { bubbles: true })); }
    else window.scrollTo(0, y);
}
// Flow's CDK grid can listen on an outer scroll host while a nested container
// also accepts scrollTop. Wheel input follows Chrome's actual scroll chain and
// triggers loading/virtualization on the same host used by a person.
async function wheelGrid(page, delta) {
    const point = await page.evaluate(() => {
        const tiles = [...document.querySelectorAll('flow-video-tile, flow-image-tile')];
        const tile = tiles.find(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 160 && r.top < innerHeight - 80; });
        const rect = tile?.getBoundingClientRect();
        if (rect) return { x: Math.max(10, Math.min(innerWidth - 10, rect.left + rect.width / 2)), y: Math.max(180, Math.min(innerHeight - 100, rect.top + rect.height / 2)) };
        const s = window.__veoGridScroller?.();
        const r = s?.getBoundingClientRect();
        return { x: r ? Math.max(20, Math.min(innerWidth - 20, r.left + Math.min(r.width / 2, 300))) : innerWidth / 2,
            y: Math.max(180, Math.min(innerHeight - 100, r ? r.top + r.height / 2 : innerHeight / 2)) };
    });
    await page.mouse.move(point.x, point.y);
    await page.mouse.wheel({ deltaY: delta });
}
// Playback-load Retry reloads existing media, never a generation-failure retry.
function retryVideoLoadErrors() {
    let clicked = 0;
    for (const button of document.querySelectorAll('button')) {
        if (!/^retry$/i.test(button.getAttribute('aria-label') || button.innerText || '')) continue;
        let parent = button.parentElement;
        for (let depth = 0; parent && depth < 6; depth++, parent = parent.parentElement) {
            const text = parent.innerText || parent.textContent || '';
            if (/generation failed|failed to generate|not been charged/i.test(text)) break;
            if (/the video failed to load\.?/i.test(text)) {
                const rect = parent.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && !button.disabled) { button.click(); clicked++; }
                break;
            }
        }
    }
    return clicked;
}
module.exports = { installGridScroller, gridMetrics, scrollGrid, wheelGrid, retryVideoLoadErrors };
