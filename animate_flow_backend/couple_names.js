// Apply the preset's couple names even if the writer retains source names.
function genderOf(c) {
    const explicit = String(c.gender || c.sex || '').toLowerCase();
    if (/^(female|woman|wife)$/.test(explicit)) return 'female';
    if (/^(male|man|husband)$/.test(explicit)) return 'male';
    const text = `${c.description || ''} ${c.sheet_prompt || ''}`;
    if (/\b(woman|female|wife|girlfriend)\b/i.test(text)) return 'female';
    if (/\b(man|male|husband|boyfriend)\b/i.test(text)) return 'male';
    return null;
}

function replaceNames(value, aliases) {
    if (typeof value === 'string') {
        const entries = [...aliases.entries()].filter(([name, to]) => name && name.toLowerCase() !== to.toLowerCase());
        if (!entries.length) return value;
        const escaped = entries.map(([name]) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).sort((a, b) => b.length - a.length);
        const lookup = new Map(entries.map(([name, to]) => [name.toLowerCase(), to]));
        return value.replace(new RegExp(`\\b(?:${escaped.join('|')})\\b`, 'gi'), name => lookup.get(name.toLowerCase()));
    }
    if (Array.isArray(value)) return value.map(v => replaceNames(v, aliases));
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, replaceNames(v, aliases)]));
    return value;
}

function fixedCoupleCast(p, cast) {
    if (!p.fixed_couple_names) return cast;
    const used = new Set();
    const genders = cast.map(c => {
        const g = genderOf(c) || (c.name === p.fixed_couple_names.female ? 'female' : c.name === p.fixed_couple_names.male ? 'male' : null);
        if (g) used.add(g);
        return g;
    });
    const aliases = new Map();
    cast.forEach((c, i) => {
        const gender = genders[i] || (used.has('male') ? 'female' : 'male');
        used.add(gender);
        aliases.set(c.name, p.fixed_couple_names[gender]);
        if (c.source_name) aliases.set(c.source_name, p.fixed_couple_names[gender]);
        for (const old of c.source_names || []) aliases.set(old, p.fixed_couple_names[gender]);
    });
    return cast.map(c => {
        const renamed = replaceNames(c, aliases);
        renamed.name = aliases.get(c.name);
        renamed.source_names = [...new Set([c.name, ...(c.source_names || []), ...(c.source_name ? [c.source_name] : [])])];
        delete renamed.source_name;
        return renamed;
    });
}

function renameStoryInputs(p, cast, meta, scenes) {
    if (!p.fixed_couple_names) return { meta, scenes };
    const aliases = new Map();
    for (const c of cast) for (const old of c.source_names || []) aliases.set(old, c.name);
    return { meta: replaceNames(meta, aliases), scenes: replaceNames(scenes, aliases) };
}

module.exports = { fixedCoupleCast, renameStoryInputs, replaceNames };
