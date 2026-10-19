#!/usr/bin/env node
/**
 * REFS FOR A SCENE - which reference images a clip needs, and how to tell they landed
 * ==================================================================================
 * WHY THIS EXISTS. The engine used to decide what to attach from the story's
 * own `character_references` map, matching the picker on the local file's
 * basename. Measured on stories/the_price_of_obligation, that lost two things:
 *
 * 1. THE PLACE WAS NEVER ATTACHED. Its `character_references` holds exactly two
 *    entries - godwin and tari - and no place. The place IS a real ref
 *    (refs.json: kind "place", the bedroom plate), and the story's own sheets
 *    file says why it matters: "This is the ONE place this film happens in.
 *    Every clip is shot here, with the same furniture and the same light."
 *    Iterating character_references cannot see it, so the room was never handed
 *    to the model and each clip re-invented it.
 *
 * 2. THE FILES IT NAMED DO NOT EXIST. The story records
 *    "./character_refs/godwin.jpg" and "./character_refs/tari.jpg", and
 *    stories/the_price_of_obligation/character_refs/ IS EMPTY. So the upload
 *    step resolved nothing and logged a warning per name while the run carried
 *    on. The only reason any ingredient was attached at all is that the tiles
 *    had been made in the Flow project by hand - which is exactly the manual
 *    step generate_refs.js automates for Agent Mode, and what the Scenes route
 *    now uses it for too.
 *
 * So refs come from the story's refs.json when it has one - the same file the
 * ref generator reads, so both routes agree on the cast AND the place - with
 * the sheets file and the story's map as fallbacks.
 *
 * MATCHING. A tile's on-screen name is not the local filename: the generator
 * RENAMES each tile to the ref's own simple name ("Godwin"), while the story
 * records a path ("character_refs/godwin.jpg"). Matching one exact spelling is
 * how a ref goes missing with nobody noticing, so candidates are tried from
 * most specific to least and compared on a key that ignores case, spaces,
 * punctuation and underscores.
 *
 * VERIFYING. Whether a tick actually became an ingredient is READ BACK off the
 * prompt box, never assumed from the fact that a click was dispatched. That is
 * the fix for "extending only adds one @img, sometimes the male, sometimes the
 * female": the old code counted a click it could not observe and then moved on.
 *
 * THE CAP IS THREE. The story's sheets file states it: "the video model accepts
 * at most 3 reference images, and the place plate takes one of those slots - so
 * a cast of 2 or 3 is the ceiling." refsForScene reports an over-cap request
 * rather than silently dropping one.
 *
 * No browser, no network, no story file needed - see test_refs_for_scene.js.
 */

const fs = require('fs');
const path = require('path');

const MAX_INGREDIENTS = 3;

// Case, spaces, punctuation and underscores all disappear, so "Godwin",
// "godwin", "godwin.jpg" and "Godwin_Reference_Sheet" can be compared.
function refKey(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function isPlace(ref) {
    return /place|set|location|room/i.test(String((ref && ref.kind) || ''));
}

// ── reading the refs a story declares ───────────────────────────────────────

// refs.json is { refs: [...] } - or a bare array in files written by hand.
function readRefsFile(file) {
    const db = JSON.parse(fs.readFileSync(file, 'utf8'));
    const refs = Array.isArray(db) ? db : (db.refs || []);
    let story = null;
    try {
        const folder = path.dirname(file);
        const stories = fs.readdirSync(folder).filter(name => /_story\.json$/i.test(name));
        if (stories.length === 1) story = JSON.parse(fs.readFileSync(path.join(folder, stories[0]), 'utf8'));
    } catch {}
    return refs.filter(r => r && r.name && String(r.prompt || '').trim())
        .map(r => ({
            name: String(r.name).trim(),
            file: r.file ? String(r.file) : '',
            kind: isPlace(r) ? 'place' : 'character',
            prompt: isPlace(r) && require('./location_style').isRelationship(story)
                ? require('./location_style').locationPrompt(story, {description: story.place?.description || r.prompt, prompt:r.prompt})
                : String(r.prompt).trim(),
        }));
}

// Older stories have no refs.json - their character_sheets.txt is regular:
// "=== NAME ===   (human)", "save as: character_refs/<file>", and the line
// after "-- image prompt --" is the prompt. The "(human)"/"PLACE" marker on the
// heading is what says whether it is a character or the place.
function parseSheetsTxt(txt) {
    const refs = [];
    for (const part of String(txt || '').split(/^===\s*/m).slice(1)) {
        const close = part.indexOf('===');
        if (close < 0) continue;
        const head = part.slice(0, close).trim();
        const body = part.slice(close + 3);
        const save = body.match(/save as:\s*([^\r\n]+)/i);
        const prompt = body.match(/-- image prompt --\s*[\r\n]+([^\r\n]+)/i);
        if (!save || !prompt) continue;
        // "=== PLACE - BEDROOM ===" -> the name is BEDROOM, not the whole
        // heading, so the tile the generator renames is named the same way the
        // story's refs.json names it.
        const place = /^place\b/i.test(head);
        const name = (place ? head.replace(/^place\s*[-:]\s*/i, '') : head.replace(/\(.*?\)\s*$/, ''))
            .replace(/[-–—]\s*$/, '').trim();
        if (!name) continue;
        refs.push({
            name,
            file: save[1].trim(),
            kind: place ? 'place' : 'character',
            prompt: prompt[1].trim(),
        });
    }
    return refs;
}

// Everything the story declares, from the best source it has.
//   refs.json          - the file generate_refs.js reads; has the place
//   character_sheets.txt - older stories; has the place too
//   story's map        - last resort, and it has NO place (see the header)
function loadStoryRefs(jsonFilePath, story) {
    const p = path.resolve(jsonFilePath);
    // Accept the story file, the story's folder, or anything inside it - the
    // refs live beside the story and callers hold different ends of that path.
    const dir = (fs.existsSync(p) && fs.statSync(p).isDirectory()) ? p : path.dirname(p);
    const refsJson = path.join(dir, 'refs.json');
    if (fs.existsSync(refsJson)) {
        try {
            const refs = readRefsFile(refsJson);
            if (refs.length) return { refs, source: 'refs.json' };
        } catch (e) {
            return { refs: [], source: `refs.json unreadable (${e.message})` };
        }
    }
    const sheets = path.join(dir, 'character_sheets.txt');
    if (fs.existsSync(sheets)) {
        const refs = parseSheetsTxt(fs.readFileSync(sheets, 'utf8'));
        if (refs.length) return { refs, source: 'character_sheets.txt' };
    }
    const map = (story && (story.character_references || story.characterReferences)) || {};
    const refs = Object.entries(map).filter(([, v]) => v)
        .map(([name, file]) => ({ name, file: String(file), kind: 'character', prompt: '' }));
    return { refs, source: refs.length ? 'the story\'s character_references (no place in it)' : 'nothing' };
}

// ── matching a ref to a tile ────────────────────────────────────────────────

// Every spelling this ref could be on screen under, most specific first: the
// name the generator renames the tile to, then the file it was saved as.
//
// Spellings are deduplicated on their KEY, so "Godwin" and "godwin" collapse
// into one entry - which is correct, because every comparison here is made on
// the key. The story's map only adds anything for a ref declared WITHOUT a file
// (a hand-written refs.json), where the sheet it was saved as is the one thing
// that could be on screen instead.
function refAliases(ref, characterReferences) {
    const out = [];
    const seen = new Set();
    const push = (s) => {
        const t = String(s || '').trim();
        const k = refKey(t);
        if (!k || seen.has(k)) return;
        seen.add(k);
        out.push(t);
    };
    push(ref.name);
    const stem = ref.file ? path.basename(String(ref.file)).replace(/\.[^.]+$/, '') : '';
    if (stem) {
        push(stem);
        push(path.basename(String(ref.file)));
    } else {
        for (const [k, v] of Object.entries(characterReferences || {})) {
            if (refKey(k) !== refKey(ref.name)) continue;
            push(k);
            if (v) push(path.basename(String(v)).replace(/\.[^.]+$/, ''));
        }
    }
    return out;
}

// The refs one scene needs: its own cast, plus the place it happens in.
//
// The place is unconditional on purpose - a scene is always somewhere, and the
// story declares exactly one. The cast is the scene's own list when it has one
// (so a scene that drops a character does not get them forced back in), and the
// whole cast when it does not. Every character the scene NAMES is reported if no
// ref matches it, rather than quietly attaching fewer.
function refsForScene(scene, refs, characterReferences) {
    const all = (Array.isArray(refs) ? refs : []).filter(r => r && r.name);
    const cast = all.filter(r => !isPlace(r));
    const places = all.filter(isPlace);
    const named = (((scene && scene.characters) || []).map(refKey)).filter(Boolean);

    let picked;
    if (named.length) {
        picked = [];
        for (const n of named) {
            const hit = cast.find(r => refKey(r.name) === n)
                || cast.find(r => refAliases(r, characterReferences).some(a => refKey(a) === n));
            if (hit && !picked.includes(hit)) picked.push(hit);
        }
    } else {
        picked = cast.slice();
    }
    const missingCast = named.filter(n => !picked.some(r => refKey(r.name) === n));
    const wanted = picked.concat(places);
    return {
        refs: wanted,
        missingCast,
        overCap: wanted.length > MAX_INGREDIENTS,
        names: wanted.map(r => r.name),
    };
}

// ── reading back what actually landed ───────────────────────────────────────

// An attached ingredient shows up in the prompt box as an @mention. Prose that
// merely NAMES a character ("Godwin sits on the edge of the bed") is not an
// attachment, so a bare substring test would report a ref as attached when
// nothing was - which is the failure being fixed here. Match the @ only.
//
// Any separator is allowed between the alias's own characters, so "@Godwin",
// "@godwin_reference_sheet" and "@Godwin Reference Sheet" all match the alias
// "Godwin".
function mentionRe(alias) {
    const chars = String(alias).replace(/[^A-Za-z0-9]/g, '').split('');
    if (!chars.length) return null;
    const esc = (c) => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('@[^\\S\\n]*' + chars.map(esc).join('[^A-Za-z0-9]{0,4}'), 'i');
}

// Did this ref land? `chips` are the texts of the ingredient chips found in the
// prompt box (some builds render a mention as a chip element with no @ in its
// innerText), `text` is the box's plain text for the @mentions.
function refLanded(ref, { text, chips } = {}, characterReferences) {
    const aliases = refAliases(ref, characterReferences);
    for (const c of chips || []) {
        const ck = refKey(c);
        if (ck.length < 3) continue;
        // A chip can only BE an ingredient, never prose, so a containment test
        // is safe here where it would not be on the box's text.
        if (aliases.some(a => { const ak = refKey(a); return ak.length >= 3 && (ck === ak || ck.includes(ak) || ak.includes(ck)); })) {
            return true;
        }
    }
    for (const a of aliases) {
        const re = mentionRe(a);
        if (re && re.test(String(text || ''))) return true;
    }
    return false;
}

// Which of these refs are NOT yet in the prompt box.
function missingRefs(refs, box, characterReferences) {
    return (refs || []).filter(r => !refLanded(r, box, characterReferences));
}

module.exports = {
    MAX_INGREDIENTS, refKey, isPlace, readRefsFile, parseSheetsTxt, loadStoryRefs,
    refAliases, refsForScene, mentionRe, refLanded, missingRefs,
};
