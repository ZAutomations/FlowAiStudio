const { audioMix } = require('./dialogue_speakers');
const { withBrightLocation } = require('./location_style');

function supportsShotPlan(story, scene) {
    const names = Object.keys(story?.character_descriptions || {}).map(n => n.toLowerCase());
    return story?.narration_scope === 'dialogue' && names.includes('sarah') && names.includes('george') && !!scene?.dialogue?.length;
}
function occupiedPlace(text) {
    return String(text || '')
        .replace(/\b(?:the (?:space|room|setting) is |an? )?empty of people\b[, ]*/gi, '')
        .replace(/\bno people(?: or animals)?\b[,. ]*/gi, '')
        .replace(/\bempty (kitchen|bedroom|room|garden|location|setting|sitting room)\b/gi, '$1')
        .replace(/\b(?:straight-on wide view|wide two-shot at eye level)\b/gi, '');
}
function dialogueBlocking(text) {
    return String(text || '')
        .replace(/,\s*(?:typing|slowly preparing|preparing|washing|looking down|staring at)[^.]*\./gi, '.')
        .trim();
}
function anchor(story, name) {
    const description = story.character_descriptions[name.toLowerCase()] || story.character_descriptions[name] || '';
    const clothes = description.match(/\b(?:he|she) wears\s+([^.!?]+)/i)?.[1];
    return `${name}, the ${name === 'George' ? 'man' : 'woman'}${clothes ? ' wearing ' + clothes.replace(/\s+that remains unchanged.*/i, '') : ''}`;
}
function shotPlan(story, scene, { extend = false } = {}) {
    const simple = require('./simple_dialogue_prompt').plan(story, scene, {extend});
    if (simple) return simple;
    if (!supportsShotPlan(story, scene)) return null;
    const turns = scene.dialogue.map(d => {
        const speaker = /^george$/i.test(String(d.speaker).trim()) ? 'George' : /^sarah$/i.test(String(d.speaker).trim()) ? 'Sarah' : null;
        if (!speaker || !String(d.line || '').trim()) throw Error('Cannot build dialogue shots: missing line or unknown speaker.');
        return { speaker, line: String(d.line) };
    });
    const first = turns[0].speaker;
    const place = occupiedPlace(story.place?.description || 'Use the established location.');
    const blocking = dialogueBlocking(story.blocking);
    const visual = withBrightLocation(story, [
        extend ? 'Continue from the preceding final frame with the same people, clothing, setting and physical positions.' : 'Establish the same two reference characters in their fixed location.',
        place, blocking,
        require('./relationship_composition').COMPOSITION,
        'Both characters are present. They pause other activities and face each other for this conversation. Preserve the 180-degree axis and their physical screen sides.',
        `Before the first word, frame ${anchor(story, first)} in a clear medium close-up. ${first} delivers the first line.`,
        'Use shot/reverse-shot coverage in the exact order below. During each line only the active speaker has a clearly visible mouth; the listener is outside the frame or seen from behind. Do not show the listener speaking or delivering an off-screen reply.',
        'Change to the next speaker at the turn boundary, not halfway through a line. Gentle push-ins may accompany the close-ups. After the final line, return to the established two-person framing for the final half-second. Keep the dialogue within this one clip; these shots are not extra clips.'
    ].filter(Boolean).join(' '));
    const audio = audioMix() + 'DIALOGUE SHOTS — perform once in this order, with no overlapping voices:\n' + turns.map((d,i) => {
        const gender = d.speaker === 'George' ? 'male' : 'female';
        return `SHOT ${i+1}: Close-up of ${anchor(story,d.speaker)}. Visible speaking face: ${d.speaker}. ${d.speaker} says in a natural ${gender} voice: "${d.line}"${i < turns.length-1 ? '\nFinish the final word and pause 0.30 seconds before the next speaker starts.' : ''}`;
    }).join('\n');
    return { visual, audio, prompt: `[SHOT] ${visual}\n[LOOK] ${story.style || 'Match the reference characters and location.'}\n[AUDIO] ${audio}` };
}
module.exports = { supportsShotPlan, shotPlan, occupiedPlace, dialogueBlocking };
