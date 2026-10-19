// Project URLs used when restarting the clip phase in an existing project.
function normalizeProjectUrl(value) {
    try {
        const url = new URL(String(value || '').trim());
        if (url.protocol !== 'https:' || url.username || url.password || url.port) throw Error();
        const match = url.hostname === 'flow.google.com'
            ? url.pathname.match(/^\/project\/([a-zA-Z0-9_-]+)(?:\/.*)?$/)
            : url.hostname === 'labs.google'
                ? url.pathname.match(/^\/fx\/(?:[a-z]{2}\/)?tools\/flow\/project\/([a-zA-Z0-9_-]+)(?:\/.*)?$/)
                : null;
        if (match) return `https://flow.google.com/project/${match[1]}`;
    } catch (_) { /* report one actionable error for every invalid URL */ }
    throw new Error('Paste a Flow project URL, such as https://flow.google.com/project/<project-id>.');
}

async function selectAgentPage(browser, projectUrl) {
    const pages = await browser.pages();
    const flowTabs = pages.filter(p => {
        try { return new URL(p.url()).hostname === 'flow.google.com'; } catch (_) { return false; }
    });
    // After a reboot there may be no Flow tab. A supplied project URL gives us
    // a destination, so create a tab for that URL instead of rejecting the run.
    const page = (projectUrl && flowTabs.find(p => p.url() === projectUrl))
        || flowTabs.find(p => /\/project\//i.test(p.url()))
        || flowTabs[0]
        || (projectUrl ? await browser.newPage() : null);
    return { page, pages, flowTabs };
}

module.exports = { normalizeProjectUrl, selectAgentPage };
