// Inventory the whole Flow project, including pages unmounted by its virtual grid.
function projectFrame() {
    const scroller = window.__veoGridScroller?.() || null;
    const bounds = scroller ? scroller.getBoundingClientRect() : { x: 0, y: 0 };
    const top = scroller ? scroller.scrollTop : window.scrollY;
    const left = scroller ? scroller.scrollLeft : window.scrollX;
    const tiles = [...document.querySelectorAll('flow-video-tile, flow-image-tile')].map(tile => {
        const rect = tile.getBoundingClientRect();
        const text = tile.innerText || tile.textContent || '';
        const sources = [...tile.querySelectorAll('video, video source, img')]
            .map(el => el.currentSrc || el.getAttribute('src') || el.getAttribute('poster') || '')
            .filter(src => /^(https?:|blob:)/i.test(src) && !/\.svg(?:[?#]|$)|placeholder|loading/i.test(src));
        const failed = /audio generation failed|failed to generate|generation failed|something went wrong|try a different prompt|you have not been charged/i.test(text)
            || !!tile.querySelector('[class*=error-tile], button[aria-label="Retry"]');
        const busy = !failed && (!sources.length || /generating|generation in progress|queued|processing|creating|(?:^|\n)\s*\d{1,2}%\s*(?:\n|$)/i.test(text)
            || !!tile.querySelector('mat-progress-spinner, [role="progressbar"], [class*=spinner]'));
        return { video: tile.tagName.toLowerCase() === 'flow-video-tile', failed, busy,
            id: (sources.join(' ').match(/\/(?:video|image|asb)\/([^=?/#\s]+)/) || [])[1] || '',
            x: Math.round(left + rect.x - bounds.x), y: Math.round(top + rect.y - bounds.y), h: rect.height };
    });
    return { scrollable: !!scroller || Math.max(document.documentElement.scrollHeight, document.body.scrollHeight) > window.innerHeight,
        top, client: scroller ? scroller.clientHeight : window.innerHeight,
        height: scroller ? scroller.scrollHeight : Math.max(document.documentElement.scrollHeight, document.body.scrollHeight), tiles };
}

async function scanProjectMedia(page, options = {}) {
    const wait = options.wait || (ms => new Promise(resolve => setTimeout(resolve, ms)));
    const { installGridScroller, scrollGrid, wheelGrid, retryVideoLoadErrors } = require('./flow_grid_scroll');
    await page.evaluate(installGridScroller);
    const first = await page.evaluate(projectFrame);
    const records = [];
    const merge = frame => {
        for (const tile of frame.tiles) {
            const index = records.findIndex(old => (old.id && tile.id && old.id === tile.id && old.video === tile.video)
                || (old.video === tile.video && Math.abs(old.x - tile.x) < 12 && Math.abs(old.y - tile.y) < 12));
            if (index < 0) records.push(tile); else records[index] = tile;
        }
    };
    const scroll = async top => page.evaluate(scrollGrid, top);
    merge(first);
    let exhaustive = !first.scrollable;
    if (first.scrollable) {
        try {
            await scroll(0);
            await wheelGrid(page, -100000);
            await wait(700);
            let quiet = 0;
            let loadRetries = 0;
            let walked = false, clamped = 0;
            for (let round = 0; round < 300; round++) {
                if (loadRetries < 3 && await page.evaluate(retryVideoLoadErrors)) { loadRetries++; await wait(1200); }
                const frame = await page.evaluate(projectFrame);
                merge(frame);
                const before = records.length;
                const bottom = Math.max(0, frame.height - frame.client);
                const target = Math.min(bottom, frame.top + Math.max(100, frame.client * 0.75));
                await wheelGrid(page, Math.max(100, Math.floor(frame.client * 0.75)));
                for (let poll = 0; poll < (target >= bottom - 2 ? 12 : 1); poll++) {
                    await wait(750);
                    merge(await page.evaluate(projectFrame));
                    if (records.length > before) break;
                }
                const after = await page.evaluate(projectFrame);
                if (after.top > frame.top + 2) walked = true;
                const atEnd = after.top >= after.height - after.client - 2;
                quiet = records.length === before && atEnd ? quiet + 1 : 0;
                if (!atEnd && target > frame.top + 2 && after.top <= frame.top + 2) {
                    if (walked && ++clamped >= 2) { exhaustive = true; break; }
                    if (!walked) break;
                    await wait(1000); continue;
                }
                clamped = 0;
                if (quiet >= 2) { exhaustive = true; break; }
            }
        } finally { await scroll(first.top); }
    }
    const videos = records.filter(tile => tile.video);
    return { flow_video_tile: videos.length,
        ready_video_tile: videos.filter(tile => !tile.failed && !tile.busy).length,
        failed_video_tile: videos.filter(tile => tile.failed).length,
        generating_video_tile: videos.filter(tile => !tile.failed && tile.busy).length,
        flow_image_tile: records.length - videos.length, project_scan_complete: exhaustive };
}
module.exports = { scanProjectMedia, projectFrame };
