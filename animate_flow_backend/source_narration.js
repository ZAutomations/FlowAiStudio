function clips(cm) { return Array.isArray(cm?.clips) ? cm.clips : Array.isArray(cm?.segments) ? cm.segments : []; }
function lines(cm) {
    return clips(cm).flatMap(c => Array.isArray(c.source_narration) ? c.source_narration
        : typeof c.source_narration === 'string' ? [{ line: c.source_narration }] : []);
}
function hasNarration(cm) {
    return clips(cm).length > 0 && clips(cm).every(c => Array.isArray(c.source_narration) || typeof c.source_narration === 'string')
        && lines(cm).some(d => String(d.line || '').trim());
}
function viewerScenario(line) {
    const unquoted = String(line || '').replace(/"[^"\n]*"|“[^”\n]*”/g, '');
    return /\b(?:you|your|yours|yourself)\b/i.test(unquoted);
}
function instructions(p, cm) {
    if (!p.preserve_source_narration) return '';
    const transcript = lines(cm).map(d => `${d.t || ''} ${d.line || ''}`.trim()).join('\n');
    return `DOCUMENTARY SOURCE CONTRACT (overrides generic retention and second-person writing):
Retell what actually happened to the source's people, in the source's presentation
order, with the same opening, facts, causes, uncertainty and complete ending.
Use light, simple-English rewording. Keep each sentence's meaning and narrative
function; do not replace the account with a new plot, philosophical metaphor,
survival advice or an imagined "you are there" scenario. Report the event using
he/she/they, the passengers, the captain or the named subject. Do not repeatedly
address the viewer as you/your. Preserve source tense. No invented suspense,
extra hook, moral speech, numbers or technical details.
${p.extra_cta_clip ? 'Complete the entire original ending, THEN append the preset\'s one separate extra CTA clip. Only that extra clip may address the viewer; it must add no story facts.' : 'Do not append a CTA or additional ending.'}
Map EVERY source passage to consecutive outline beats; repartition into the
requested clip count without losing the ending. If the duration is too short
to include the complete account at an intelligible pace, report that conflict
instead of silently compressing or omitting sections. Do not stretch a short
source with imagined details. Each clip's two or three internal shots must show
the events actually narrated in that clip. Follow observed source shot progression
where available, rendered with the selected preset's visual treatment.
${transcript ? `COMPLETE SOURCE NARRATION (preserve meaning and order):\n${transcript}`
    : 'Only an event summary is available. Preserve those facts; do not claim this is a complete transcription or invent missing source sentences.'}`;
}
module.exports = { lines, hasNarration, instructions, viewerScenario };
