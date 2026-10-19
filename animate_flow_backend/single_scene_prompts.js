const fs = require('fs');
const path = require('path');

function promptForScene(story, index, options = {}) {
    const scene = story.scenes[index];
    if (!scene) throw Error(`Story has no scene ${index + 1}.`);
    const ratio = options.aspect || story.aspect_ratio;
    const aspect = /^(flow|auto)$/i.test(ratio || '') ? null : ratio;
    const seconds = Number(options.seconds || story.scene_seconds) || 8;
    const request = `Generate ONE standalone clip for story scene ${index + 1} only. Do not generate other scenes or repeat the full story. Use the existing named references in this project.\n`;
    const simple = require('./simple_dialogue_prompt').agent(story, { from: index + 1, to: index + 1, aspect, seconds, native: !!options.native });
    if (simple) return request + '\n' + simple;
    const keys = scene.characters?.length ? scene.characters : Object.keys(story.character_descriptions || {});
    const names = keys.map(key => {
        const text = String(key);
        return text.charAt(0).toUpperCase() + text.slice(1);
    });
    const refs = [...names, story.place?.name].filter(Boolean);
    const audio = scene.dialogue?.length
        ? 'No narrator. Only the labelled character speaks; the other listens. Calm, respectful tone at normal volume. Finish each line, pause 0.30 seconds, then begin the next voice. No overlap.\n' + scene.dialogue.map(d => `${d.speaker}: "${d.line}"`).join('\n')
        : scene.script_line ? `Narrator only (${story.narrator_voice || 'the established narrator voice'}${story.flow_voice ? '; Flow voice ' + story.flow_voice : ''}). Read exactly: "${scene.script_line}". All visible people remain silent.`
        : `No narration. ${scene.sound_context || 'Natural room tone only; no invented dialogue.'}`;
    return [request, `Scene ${index + 1} - ${scene._scene_title || 'Untitled'}`,
        `FORMAT: ${aspect || 'Use the aspect ratio selected in Flow settings.'}; ${seconds} seconds; ONE output clip.`,
        `STYLE: ${story.style || ''}`,
        /Zack D/i.test(story.niche || '') ? require('./zack_shot_contract').DIRECTION : '',
        `REFERENCES: ${refs.map(n => '@' + n).join(', ') || '(none)'}`,
        story.single_speaker_advice && story.voice_direction ? `VOICE DELIVERY: ${story.voice_direction}` : '',
        ...names.map(n => `IDENTITY ${n}: ${story.character_descriptions?.[n.toLowerCase()] || story.character_descriptions?.[n] || 'Match the named reference.'}`),
        story.place ? `LOCATION: ${story.place.name}. ${story.place.description || ''}` : '',
        story.blocking ? `POSITIONS: ${story.blocking}` : '',
        `VISUAL: ${scene.narrative_context || ''}`, `AUDIO: ${audio}`,
        'Do not rewrite the spoken lines, add narration, captions or additional clips. Keep character identity, clothing and location consistent.'
    ].filter(Boolean).join('\n\n') + '\n';
}

function writeSingleScenePrompts(dir, story, options = {}) {
    const folder = path.join(dir, 'clip_prompts');
    fs.mkdirSync(folder, { recursive: true });
    const combined = ['INDIVIDUAL CLIP PROMPTS — ' + story.title,
        'Each section below is a complete standalone prompt. Copy only ONE section into the same Flow project.',
        'Use Ctrl+F to find CLIP 007, for example. Story scene numbers are not downloaded MP4 filenames.',
        'Make sure the named character and location reference images already exist in the project. Set the video model and ratio in Flow before generating.',
        'For an Ingredients Extend continuation, use the continuation prompt in extend_prompts.json instead; these files request separate replacement clips.', ''];
    const index = [];
    for (let i = 0; i < (story.scenes || []).length; i++) {
        const number = String(i + 1).padStart(3, '0');
        const file = `clip_${number}.txt`;
        const text = promptForScene(story, i, options);
        fs.writeFileSync(path.join(folder, file), text, 'utf8');
        index.push(`${number} | ${story.scenes[i]._scene_title || 'Untitled'} | ${file}`);
        combined.push(`================ BEGIN CLIP ${number} ================`, text.trim(), `================ END CLIP ${number} ==================`, '');
    }
    fs.writeFileSync(path.join(folder, 'INDEX.txt'), index.join('\n') + '\n');
    const all = path.join(dir, 'ALL_CLIP_PROMPTS.txt');
    fs.writeFileSync(all, combined.join('\n'), 'utf8');
    return { folder, all, count: index.length };
}
module.exports = { promptForScene, writeSingleScenePrompts };
