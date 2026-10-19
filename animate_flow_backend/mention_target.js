// mention_target.js - which tile in Flow's "@" picker should we click?
//
// Why this is its own module: the choice is the whole ballgame for character
// consistency, and it is a pure function of the picker's DOM dump - so it can be
// tested without a browser.
//
// Background (measured, not guessed - see logs/agent_run_*/04_picker1-tree.json):
//
//   2026-09-12  picker offered  "EVELYN.jpg Image"      -> clips were consistent
//   2026-09-13  picker offered  "evelyn Character"      -> clips drifted
//   2026-09-15  picker offered  "tara Character"        -> clips drifted
//
// A raw Image is handed to the model as reference PIXELS. A saved Flow Character
// is a named entity the agent re-instantiates for each of the N independent clip
// generations, so the face is re-derived every clip and drifts. The old code
// clicked "the deepest node whose text matches the name", which is blind to that
// difference: when both an Image and a Character exist, it clicked whichever
// happened to sit deeper in the DOM.
//
// So: rank tiles by TYPE first, and only then by DOM depth.

'use strict';

// The picker's left-hand category rail. These are navigation, not assets, and
// they match a name search ("Images" matches nothing useful but is clickable).
const NAV_LABELS = new Set(['all', 'images', 'videos', 'voices', 'characters', 'avatars', 'uploads']);

// Chrome inside the picker that is not an asset. Flow prefixes these with the
// material icon's ligature ("upload Upload media", "play_arrow"), so match the
// phrase at the END of the text rather than the whole string.
const ACTION_RE = /(^|\s)(add to prompt|undo|view in trash|dismiss|upload media|play_arrow|no_sound|search)$/i;

// Lower is better. This ordering IS the fix: an Image beats a Character.
const KIND_RANK = { image: 0, character: 1, avatar: 2, video: 3, voice: 4 };

function normText(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
}

function escapeRe(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// "EVELYN.jpg Image" -> 'image';  "tara Character" -> 'character';  else null.
function tileKind(text) {
    const t = normText(text);
    if (!t) return null;
    // No extension required. The picker labels a tile with the asset's name as
    // Flow knows it, and an image the user uploaded by hand is named "elena",
    // not "elena_reference_sheet.jpg" - so "elena Image" is the common case and
    // an extension-only test classified it as unknown, which silently skipped
    // the kind ranking below and fell back to the deepest node. The plural
    // "Images" of the category rail is filtered by isNavCategory, the same way
    // "Characters" is kept out of the character test.
    if (/\bimage$/i.test(t)) return 'image';
    if (/\bcharacter$/i.test(t)) return 'character';
    if (/\bavatar$/i.test(t)) return 'avatar';
    if (/\bvideo$/i.test(t)) return 'video';
    if (/\bvoice$/i.test(t)) return 'voice';
    return null;
}

// "dashboard All" and "accessibility_new Characters" are the category rail.
// The plural spellings are deliberate: the rail says "Characters"/"Images", the
// asset tiles say "Character"/"Image", so a plural match means navigation.
function isNavCategory(text) {
    const t = normText(text);
    if (!t) return false;
    if (/\.(jpe?g|png|webp|gif)/i.test(t)) return false;
    const last = t.split(' ').pop().toLowerCase();
    return NAV_LABELS.has(last);
}

function isAction(text) {
    return ACTION_RE.test(normText(text));
}

function contains(node, rect) {
    const r = node && node.rect;
    if (!r || !rect) return false;
    const pad = 2;
    return r.x >= rect.x - pad && r.y >= rect.y - pad &&
           r.x + r.w <= rect.x + rect.w + pad &&
           r.y + r.h <= rect.y + rect.h + pad;
}

// candidates: the `clickable` array from pickerFn - each {tag,text,aria,depth,rect,cx,cy}
// name:       the character name as typed after "@"
//
// Returns { tile, inner, kind, reason } - `inner` is what to click (falls back to
// `tile`), `tile` is the asset node that decided the kind. reason is for logging:
//   'ok'            a typed asset tile matched
//   'no-type'       matched something, but nothing said Image/Character/Video
//   'no-match'      nothing matched at all
function chooseMentionTile(candidates, name, {requiredKind=null} = {}) {
    // Reference identifiers are whole names. DSPMalik must never select
    // DSPMalikOffice, even if that tile is deeper/newer in the search results.
    const re = new RegExp('(^|[^A-Za-z0-9_-])'+escapeRe(name)+'(?=$|[^A-Za-z0-9_-])', 'i');

    const matched = (candidates || []).filter(c => {
        const t = normText(c.text || c.aria);
        if (!t || t.length >= 80) return false;
        if (isAction(t) || isNavCategory(t)) return false;
        return re.test(t);
    });

    if (!matched.length) return { tile: null, inner: null, kind: null, reason: 'no-match' };

    const typed = matched.filter(c => {
        const kind=tileKind(c.text||c.aria);
        if(!requiredKind)return !!kind;
        if(kind!==requiredKind)return false;
        const base=normText(c.text||c.aria).replace(/\s+(image|character|avatar|video|voice)$/i,'').replace(/\.(jpg|jpeg|png|webp)$/i,'').trim();
        return base.toLowerCase()===String(name).trim().toLowerCase();
    });
    if(requiredKind && !typed.length)return {tile:null,inner:null,kind:null,reason:'required-type-missing'};
    if (!typed.length) {
        // Nothing advertised a type - keep the old behaviour rather than
        // refusing to attach. The caller logs this so it is visible.
        const inner = matched.slice().sort((a, b) => b.depth - a.depth)[0];
        return { tile: null, inner, kind: null, reason: 'no-type' };
    }

    typed.sort((a, b) => {
        const ka = KIND_RANK[tileKind(a.text || a.aria)];
        const kb = KIND_RANK[tileKind(b.text || b.aria)];
        if (ka !== kb) return ka - kb;          // an Image beats a Character
        return b.depth - a.depth;               // same kind: tightest node wins
    });
    const tile = typed[0];

    // Click the innermost node inside the winning tile, so the click lands on
    // the tile's own label and not on a neighbouring menu button. The old code
    // picked this node directly; now it is chosen within the tile we ranked.
    const inner = matched
        .filter(c => c !== tile && contains(c, tile.rect))
        .sort((a, b) => b.depth - a.depth)[0] || tile;

    return { tile, inner, kind: tileKind(tile.text || tile.aria), reason: 'ok' };
}

// A one-line summary for the run log, so a bad attachment is obvious in the
// transcript rather than only in the saved tree.
function describeChoice(choice, name) {
    if (!choice || !choice.inner) return `@${name}: nothing matched`;
    const label = normText(choice.inner.text || choice.inner.aria).slice(0, 50);
    const kind = choice.kind ? choice.kind.toUpperCase() : 'UNKNOWN TYPE';
    let note = '';
    if (choice.kind === 'character') {
        note = '  (named Flow Character; may include its assigned voice)';
    } else if (choice.kind === 'image') {
        note = '  (raw image - the good kind)';
    } else if (choice.reason === 'no-type') {
        note = '  <-- tile type unknown, picked by depth as before.';
    }
    return `@${name}: ${kind} "${label}"${note}`;
}

// ---- the mention LIST, before any picker is opened --------------------------
// ONE chip per reference, however many times the prompt names it.
//
// The agent prompt is prose, and it names the same reference more than once on
// purpose - the writer marks the place "@Bedroom" in the PLACE section, again in
// the reminder line ("every clip is in the same place as the @Bedroom reference
// image") and again in each scene's own line. Two characters plus a place then
// arrived as five "@" names, and every one of them became its own trip through
// the picker: the same Bedroom tile clicked three times, three identical chips in
// the prompt, and the "over Veo's three-reference ceiling" warning firing on a
// cast of three.
//
// A chip binds a reference to the WHOLE prompt, so a second copy of the same
// chip cannot mean anything the first one did not - the scene text is what says
// where the reference applies. Order is the prompt's own (the place first, then
// the cast as introduced), so the chips in the box read in the order the story
// reads, and the first spelling of a name wins.
function distinctMentions(names) {
    const seen = new Set();
    const out = [];
    for (const raw of (names || [])) {
        const name = normText(raw);
        if (!name) continue;
        const key = name.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(name);
    }
    return out;
}

// ---- reference-sheet lookup -------------------------------------------------
// The story JSON records refs as `./character_refs/<key>.jpg`, but a sheet can
// be saved under a different extension or casing (TARA.png, Singhania.webp), and
// the older `<key>_reference_sheet.jpg` naming still exists in old stories. This
// resolves whatever is actually on disk, story folder first, then house_refs/.
const IMG_EXT = ['.jpg', '.jpeg', '.png', '.webp'];

function resolveCharacterRef(refs, name, storyDir, fsMod) {
    const fs = fsMod || require('fs');
    const pathMod = require('path');
    const key = String(name || '').trim();
    if (!key) return null;

    const table = refs && typeof refs === 'object' ? refs : {};
    const declared = table[key] || table[key.toLowerCase()] ||
                     table[key.charAt(0).toUpperCase() + key.slice(1).toLowerCase()];

    if (declared) {
        const abs = pathMod.resolve(storyDir, declared);
        if (fs.existsSync(abs)) return abs;
        // A standing cast declares its sheet as `./house_refs/Meera.png`, which is
        // relative to the PROJECT, not to the story folder - so it resolves
        // against storyDir and misses by design. Try the project root before
        // falling through to the basename search below.
        const fromRoot = pathMod.resolve(__dirname, declared);
        if (fs.existsSync(fromRoot)) return fromRoot;
        for (const ext of IMG_EXT) {
            const swapped = abs.replace(/\.(jpe?g|png|webp)$/i, ext);
            if (fs.existsSync(swapped)) return swapped;
        }
    }

    // Nothing declared (or a stale name): look for a file whose basename IS the
    // character's name, case-insensitively. Two folders are searched, in order:
    // the story's own character_refs/, then the shared house_refs/ at the top of
    // the project - because a standing cast's sheets are made once and reused by
    // every story, so they are deliberately not copied into each story folder.
    const wanted = key.toLowerCase();
    const dirs = [
        pathMod.join(storyDir, 'character_refs'),
        pathMod.join(__dirname, 'house_refs'),
    ];
    for (const dir of dirs) {
        let entries = [];
        try { entries = fs.readdirSync(dir); } catch { continue; }
        // Exact basename first, then any basename that starts with the name, so
        // "tara" finds "TARA.jpg" but never "tara_old_backup.png" before it.
        for (const pass of [0, 1]) {
            for (const f of entries) {
                const base = pathMod.basename(f, pathMod.extname(f)).toLowerCase();
                if (pass === 0 && base !== wanted) continue;
                if (pass === 1 && !base.startsWith(wanted)) continue;
                if (!IMG_EXT.includes(pathMod.extname(f).toLowerCase())) continue;
                const full = pathMod.join(dir, f);
                if (fs.existsSync(full)) return full;
            }
        }
    }
    return null;
}

module.exports = {
    chooseMentionTile, describeChoice, tileKind, isNavCategory, isAction,
    resolveCharacterRef, distinctMentions, KIND_RANK, normText,
};
