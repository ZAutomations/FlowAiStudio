const { replaceNames } = require('./couple_names');

function sourceSpeakerMap(source, cast, preset) {
    const turns = source.flatMap(c => c.source_dialogue || []);
    const speakers = [...new Set(turns.map(d => String(d.speaker || 'Person').trim()))];
    const fixed = preset.fixed_couple_names;
    if (fixed && preset.require_source_speaker_gender && !turns.length) throw Error('Video analysis contains no attributed dialogue. Reanalyse the source video before writing.');
    const result = new Map();
    for (const who of speakers) {
        const key = who.toLowerCase();
        const observed = turns.filter(d => String(d.speaker || 'Person').trim() === who)
            .map(d => String(d.gender || d.speaker_gender || '').toLowerCase()).filter(Boolean);
        const known = [...new Set(observed.filter(g => ['female', 'male'].includes(g)))];
        if (fixed && preset.require_source_speaker_gender && observed.some(g => !['female', 'male'].includes(g))) {
            throw Error(`Source speaker ${who} has unknown gender. Review that turn instead of guessing.`);
        }
        if (known.length > 1) throw Error(`Source speaker ${who} changes gender between turns; review the transcript.`);
        const canonical = /^(female|woman|wife|girl|sarah)$/i.test(who) ? 'female'
            : /^(male|man|husband|boy|george)$/i.test(who) ? 'male' : null;
        if (fixed && (known[0] || canonical)) {
            if (canonical && known[0] && canonical !== known[0]) throw Error(`Conflicting identity for source speaker ${who}.`);
            result.set(who, fixed[known[0] || canonical]);
            continue;
        }
        if (fixed && preset.require_source_speaker_gender) {
            throw Error(`Cannot identify whether source speaker ${who} is female or male. Reanalyse the video with speaker genders, or label transcript turns Female: / Male:. No speaker order will be guessed.`);
        }
        const character = cast.find(c => [c.name, ...(c.source_names || []), c.source_name]
            .some(name => name && String(name).toLowerCase() === key));
        if (character) { result.set(who, character.name); continue; }
        const turn = turns.find(d => String(d.speaker || 'Person').trim() === who);
        const gender = String(turn?.gender || turn?.speaker_gender || who).toLowerCase();
        if (fixed && /\b(female|woman|wife|girl)\b/.test(gender)) result.set(who, fixed.female);
        else if (fixed && /\b(male|man|husband|boy)\b/.test(gender)) result.set(who, fixed.male);
    }
    const available = fixed
        ? [preset.unlabelled_first_speaker || fixed.female, fixed.male, fixed.female]
        : cast.map(c => c.name);
    for (const who of speakers) if (!result.has(who)) {
        const unused = available.find(name => ![...result.values()].includes(name));
        result.set(who, unused || who);
    }
    return result;
}

function alignUnlabelledTranscript(preset, scenes, detail) {
    if (preset.require_source_speaker_gender && require('./relationship_transcript').hasPastedTranscript(detail)) {
        const turns = labelledTranscriptTurns(detail);
        const generated = scenes.flatMap(s => s.dialogue || []);
        if (generated.length !== turns.length) throw Error(`Transcript has ${turns.length} labelled turns; story has ${generated.length}. Review turn coverage before writing; speaker ownership cannot be guessed.`);
        let index = 0;
        return scenes.map(s => ({ ...s, dialogue: (s.dialogue || []).map(d => {
            const turn = turns[index++];
            const words = text => String(text).toLowerCase().match(/[a-z0-9']+/g) || [];
            const a = words(turn.line), b = words(d.line);
            const row = Array(b.length + 1).fill(0);
            for (const word of a) {
                let previous = 0;
                for (let j = 1; j <= b.length; j++) {
                    const old = row[j];
                    row[j] = word === b[j - 1] ? previous + 1 : Math.max(row[j], row[j - 1]);
                    previous = old;
                }
            }
            const faithful = row[b.length] >= Math.ceil(a.length * .7) && b.length <= Math.ceil(a.length * 1.2);
            return { ...d, speaker: turn.speaker, line: faithful ? d.line : turn.line };
        }) }));
    }
    return scenes;
}

function labelledTranscriptTurns(detail) {
    let text = String(detail || '').replace(/\[(?:music|applause|sound|silence)\]/gi, '');
    text = text.replace(/^(?:title|transcript|source dialogue|video transcript):[^\n]*\n/gi, '');
    const pieces = text.includes('>>') ? text.split('>>') : text.split(/\r?\n/);
    const turns = [];
    for (const piece of pieces) {
        const value = piece.trim();
        if (!value) continue;
        const match = value.match(/^(Female|Male|Woman|Man|Wife|Husband|Sarah|George)\s*:\s*([\s\S]+)$/i);
        if (!match) throw Error('Transcript speaker is missing. Label EVERY turn Female: or Male: (Sarah: / George: also work). Text alone cannot reliably identify who spoke. No API request or generation should run until labels are supplied.');
        turns.push({ speaker: /^(female|woman|wife|sarah)$/i.test(match[1]) ? 'Sarah' : 'George', line: match[2].trim() });
    }
    if (!turns.length) throw Error('No labelled dialogue found.');
    return turns;
}

function audioMix() {
    return 'AUDIO MIX: Clear speech at normal indoor conversational volume, consistent from the first word in every clip. Calm, respectful and emotionally honest delivery; no shouting, angry acting, raised voices or whispering. Keep music and ambience quiet under speech; no volume fade-in. Finish every final word, then leave a 0.30-second quiet pause before the next person speaks. No overlapping dialogue or interruptions.\n';
}
function speakerLock(preset) {
    const names = preset.fixed_couple_names;
    const mix = audioMix();
    if (!names) return preset.narration_scope === 'dialogue' ? mix : '';
    return mix + `SPEAKER LOCK: ${names.female} is the female reference character and uses her own female voice. `
        + `${names.male} is the male reference character and uses his own male voice. `
        + 'Each speaks ONLY the lines labelled with their own name, in the exact listed order. '
        + 'Only the named speaker moves their lips during that turn; the listener keeps their mouth closed. Never exchange their lines or voices.\n';
}
function formatDialogueTurn(turn) {
    const name = String(turn.speaker || '').trim();
    const gender = /^sarah$/i.test(name) ? 'female' : /^george$/i.test(name) ? 'male' : null;
    if (!gender) return `${name} (on screen, speaking): "${turn.line}"`;
    const listener = gender === 'female' ? 'George' : 'Sarah';
    return `${name} (${gender} reference character, ${gender} voice; only ${name} speaks and moves their lips, ${listener} listens with mouth closed): "${turn.line}"`;
}
// Rebuild audio from structured turns rather than retaining stale model prose.
function dialogueAudio(story, scene) {
    if (story?.narration_scope !== 'dialogue' || !scene?.dialogue?.length) return null;
    const names = Object.keys(story.character_descriptions || {}).map(n => n.toLowerCase());
    if (!names.includes('sarah') || !names.includes('george')) return null;
    for (const turn of scene.dialogue) if (!/^(sarah|george)$/i.test(String(turn.speaker).trim())) throw Error(`Unknown couple dialogue speaker: ${turn.speaker}`);
    return speakerLock({ fixed_couple_names: { female: 'Sarah', male: 'George' } })
        + scene.dialogue.map(formatDialogueTurn).join('\n');
}
function withDialogueAudio(story, scene, prompt) {
    const audio = dialogueAudio(story, scene);
    if (!audio) return String(prompt || '');
    return String(prompt || '').split(/\n\[AUDIO\]/)[0] + '\n[AUDIO] ' + audio;
}
module.exports = { sourceSpeakerMap, alignUnlabelledTranscript, speakerLock, labelledTranscriptTurns, audioMix, formatDialogueTurn, dialogueAudio, withDialogueAudio };
