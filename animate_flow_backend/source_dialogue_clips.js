// Retiming changes clip boundaries, never dialogue words or speaker ownership.
function regroup(cm, count, seconds = 8) {
    const source = Array.isArray(cm.clips) ? cm.clips : [];
    const words = source.flatMap(c => (c.source_dialogue || []).flatMap(d =>
        String(d.line || '').trim().split(/\s+/).filter(Boolean).map(word => ({ word, turn: d }))));
    if (!words.length) return cm;
    count = Math.max(1, Math.min(words.length, Math.round(count)));
    const target = words.length / count;
    const dp = Array.from({ length: count + 1 }, () => new Map());
    dp[0].set(0, { cost: 0 });
    for (let k = 1; k <= count; k++) {
        for (const [start, prev] of dp[k - 1]) {
            const max = Math.min(words.length - (count - k), start + Math.ceil(target + 6));
            for (let end = start + 1; end <= max; end++) {
                if (k === count && end !== words.length) continue;
                const boundary = end === words.length || words[end - 1].turn !== words[end].turn;
                const sentence = /[.!?]["']?$/.test(words[end - 1].word);
                const cost = prev.cost + (end - start - target) ** 2 + (boundary ? 0 : sentence ? 2 : 500);
                if (!dp[k].has(end) || cost < dp[k].get(end).cost) dp[k].set(end, { cost, start });
            }
        }
    }
    if (!dp[count].has(words.length)) throw Error('Cannot regroup source dialogue without dropping words.');
    const ranges = []; let end = words.length;
    for (let k = count; k; k--) { const start = dp[k].get(end).start; ranges.unshift([start, end]); end = start; }
    const time = n => `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`;
    const clips = ranges.map(([a, b], i) => {
        const turns = [];
        for (const token of words.slice(a, b)) {
            if (!turns.length || turns.at(-1).original !== token.turn) turns.push({ original: token.turn, words: [] });
            turns.at(-1).words.push(token.word);
        }
        return { index: i + 1, t_start: time(i * seconds), t_end: time((i + 1) * seconds),
            places: [...new Set(source.flatMap(c => c.places || []))],
            points: turns.map(t => t.words.join(' ')),
            visual: 'Sarah and George converse naturally in one bright, clear domestic room. Show the current speaker and the listening reaction.',
            source_dialogue: turns.map(t => ({ ...t.original, line: t.words.join(' ') })) };
    });
    return { ...cm, clips, dialogue_retiming: { original_groups: source.length, clips: count, words: words.length } };
}
module.exports = { regroup };
