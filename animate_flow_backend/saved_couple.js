const fs = require('fs');
const path = require('path');

function loadSavedCouple(mode, settings) {
    if (!settings) {
        const file = path.join(__dirname, 'gui_settings.json');
        settings = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
    }
    const enabled = mode === 'writer' ? settings.agent_saved_couple || settings.ing_saved_couple
        : settings[mode === 'ingredients' ? 'ing_saved_couple' : 'agent_saved_couple'];
    if (!enabled) return null;
    return ['Sarah', 'George'].map(name => {
        const key = name.toLowerCase();
        const file = String(settings[`couple_${key}_file`] || '').trim();
        if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()
            || !/\.(png|jpe?g|webp)$/i.test(file)) throw Error(`Saved couple: choose a valid ${name} reference image (PNG, JPG or WebP).`);
        return { name, type: 'human', gender: name === 'Sarah' ? 'female' : 'male',
            reference: path.resolve(file), localFile: path.resolve(file),
            description: String(settings[`couple_${key}_description`] || '').trim()
                || `Same ${name} throughout: the adult ${name === 'Sarah' ? 'woman' : 'man'} in the supplied reference sheet. Match that image exactly: same face, age, hair, skin tone, body proportions, clothing, colours and accessories. Never redesign or replace this character.`,
            sheet_prompt: '' };
    });
}

function applySavedRefs(refs, couple) {
    if (!couple) return refs;
    const characters = refs.filter(r => r.kind !== 'place');
    if (characters.some(r => !couple.some(c => c.name.toLowerCase() === String(r.name).toLowerCase()))) {
        throw Error('Saved couple requires a Sarah/George story. Rewrite this story with a relationship preset and the saved couple enabled.');
    }
    const result = refs.map(r => {
        const c = couple.find(c => c.name.toLowerCase() === String(r.name).toLowerCase());
        return c ? { ...r, localFile: c.localFile, prompt: c.description } : r;
    });
    for (const c of couple) if (!result.some(r => r.name.toLowerCase() === c.name.toLowerCase())) {
        result.push({ name: c.name, kind: 'character', file: c.localFile, localFile: c.localFile, prompt: c.description });
    }
    return result.sort((a, b) => Number(!a.localFile) - Number(!b.localFile));
}

function applyIngredientsReferenceMode(engine, couple) {
    engine.savedCouple = couple;
    if (!couple || engine.opts.exportOnly) return;
    if (engine.resumeExisting) {
        engine.genRefs = false;
        engine.opts.genRefs = false;
        return;
    }
    engine.skipRefs = false;
    engine.genRefs = true;
    engine.refsOnClip1 = true;
    Object.assign(engine.opts, { skipRefs: false, genRefs: true, refsOnClip1: true });
}

function bindSavedStory(storyFile, couple) {
    if (!couple) return;
    const story = JSON.parse(fs.readFileSync(storyFile, 'utf8'));
    const names = Object.keys(story.character_descriptions || {});
    if (!couple.every(c => names.some(n => n.toLowerCase() === c.name.toLowerCase()))) {
        throw Error('Saved couple needs both Sarah and George in the story. Write it using a relationship preset with the saved couple enabled.');
    }
    if (names.some(n => !couple.some(c => c.name.toLowerCase() === n.toLowerCase()))) {
        throw Error('Saved couple requires a Sarah/George story. Rewrite the story with the saved couple enabled first.');
    }
    const aliases = new Map();
    for (const c of couple) {
        const key = names.find(n => n.toLowerCase() === c.name.toLowerCase());
        if (!key) continue;
        aliases.set(story.character_descriptions[key], c.description);
        story.character_descriptions[key] = c.description;
        story.character_references = story.character_references || {};
        story.character_references[key] = c.localFile;
    }
    // Remove stale invented appearance blocks from prompts already written.
    for (const scene of story.scenes || []) for (const key of ['veo3_prompt', 'narrative_context']) {
        if (typeof scene[key] !== 'string') continue;
        for (const [old, fresh] of aliases) if (old) scene[key] = scene[key].split(old).join(fresh);
    }
    const next = JSON.stringify(story, null, 2) + '\n';
    if (next !== fs.readFileSync(storyFile, 'utf8')) {
        const backup = storyFile + '.before-saved-couple';
        if (!fs.existsSync(backup)) fs.copyFileSync(storyFile, backup);
        fs.writeFileSync(storyFile, next);
    }
    const refsFile = path.join(path.dirname(storyFile), 'refs.json');
    const prior = fs.existsSync(refsFile) ? JSON.parse(fs.readFileSync(refsFile, 'utf8')) : { refs: [] };
    const refs = applySavedRefs(Array.isArray(prior) ? prior : prior.refs || [], couple);
    if (fs.existsSync(refsFile) && !fs.existsSync(refsFile + '.before-saved-couple')) fs.copyFileSync(refsFile, refsFile + '.before-saved-couple');
    fs.writeFileSync(refsFile, JSON.stringify({ refs }, null, 2) + '\n');
    // The sheet is displayed to users and may be copied into Agent instructions.
    // Keep it aligned with the JSON, which is the prompt converter's source.
    const sheetsFile = path.join(path.dirname(storyFile), 'character_sheets.txt');
    if (fs.existsSync(sheetsFile)) {
        const before = fs.readFileSync(sheetsFile, 'utf8');
        let after = before;
        for (const c of couple) {
            const heading = new RegExp(`(=== ${c.name.toUpperCase()} ===[^\\n]*\\n)([\\s\\S]*?)(?=\\n=== |$)`);
            after = after.replace(heading, (_, title) => title
                + `Saved reference: ${c.localFile}\nUse this existing image sheet.\n\n-- image prompt --\n${c.description}\n\n`
                + `-- identity text (must match this exactly in the story JSON) --\n${c.description}\n`);
        }
        if (after !== before) fs.writeFileSync(sheetsFile, after);
    }
}
module.exports = { loadSavedCouple, applySavedRefs, bindSavedStory, applyIngredientsReferenceMode };
