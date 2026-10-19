// Snapshots deliberately abbreviate text. Read the actual editor for validation.
function normalize(text) { return String(text || '').replace(/\s+/g, ' ').trim(); }
function assertPrompt(actual, expected, attached = false) {
    const got = normalize(actual), wanted = normalize(expected);
    if (!wanted || (attached ? !got.startsWith(wanted) : got !== wanted)) {
        throw Error(`Agent prompt differs from the prepared text (${got.length}/${wanted.length} normalized characters). No generation submitted.`);
    }
    return String(actual).length;
}
async function readEditor(page) {
    return page.evaluate(() => {
        const pm = document.querySelector('flow-base-prompt-box .ProseMirror') || document.querySelector('.ProseMirror');
        return pm ? pm.innerText || '' : '';
    });
}
module.exports = { assertPrompt, readEditor };
