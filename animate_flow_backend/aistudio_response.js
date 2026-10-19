// A briefly stable "{" or unfinished JSON must not be treated as a finished
// answer when AI Studio's Stop control is absent or temporarily unmounted.
function completeAnswer(raw) {
    const text = String(raw || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '').trim();
    if (!text) return false;
    if (!/^[{\[]/.test(text)) return true;
    let quoted = false, escaped = false;
    const stack = [];
    for (const char of text) {
        if (quoted) {
            if (escaped) escaped = false;
            else if (char === '\\') escaped = true;
            else if (char === '"') quoted = false;
        } else if (char === '"') quoted = true;
        else if (char === '{' || char === '[') stack.push(char);
        else if (char === '}' || char === ']') {
            if (stack.pop() !== (char === '}' ? '{' : '[')) return false;
        }
    }
    return !quoted && stack.length === 0;
}
module.exports = { completeAnswer };
