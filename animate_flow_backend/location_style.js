const BRIGHT_LOCATION = 'LOCATION LIGHTING: Bright, clean, airy clear-day setting, with luminous white and ivory surfaces, soft natural daylight and gentle shadows. Faces and the entire background remain clearly visible. Use restrained polished highlights, without blown-out skin or harsh glare. Interiors have bright white walls and light furnishings with daylight through windows. Gardens stay recognizably outdoors with healthy natural greenery, a clear daytime sky and light or white paths, seating or architectural accents. No gloomy lighting, murky shadows, night, dusk, horror atmosphere, clutter or dirty surfaces. Keep this same daylight throughout the film.';
function isRelationship(value) {
    return /^relationship-dialogue(?:-(?:real|ghibli|3d))?$/.test(value?.id || '') || /^Relationship Dialogue\b/i.test(value?.niche || '');
}
function brightVisualText(text) {
    return String(text || '')
        .replace(/\b(?:dimly|poorly) lit\b/gi, 'brightly daylit')
        .replace(/\b(?:late afternoon|twilight|dusk|sunset|midnight|nighttime)\b/gi, 'clear daytime')
        .replace(/\b(?:honeyed|dim|moody|low|dark|warm gold) (?:afternoon )?(?:lighting|light|highlights)\b/gi, 'bright soft daylight')
        .replace(/\b(?:deep|dark|heavy|harsh|murky|dreamy blue) shadows?\b/gi, 'gentle daylight shadows')
        .replace(/\b(?:dim|gloomy|dark) room\b/gi, 'bright airy room')
        .replace(/\b(?:muted )?(?:sage green|dark grey|dark gray|charcoal|deep teal) (walls?|curtains?|cabinets?)\b/gi, 'white $1')
        .replace(/(?:The )?(?:warm gold highlights|light|lighting|afternoon light)[^.!?\n]*(?:dim|fade)[^.!?\n]*[.!?]/gi, 'The bright daylight remains constant.');
}
function withBrightLocation(story, prompt) {
    if (!isRelationship(story)) return String(prompt || '');
    const parts = String(prompt || '').split(/\n\[AUDIO\]/);
    const visual = brightVisualText(parts.shift());
    return visual + (visual.includes('LOCATION LIGHTING:') ? '' : '\n' + BRIGHT_LOCATION)
        + (parts.length ? '\n[AUDIO]' + parts.join('\n[AUDIO]') : '');
}
function locationPrompt(preset, place) {
    const original = String(place.prompt || '').trim();
    if (!isRelationship(preset)) return original;
    if (preset.id === 'relationship-dialogue-3d' || preset.niche === 'Relationship Dialogue — Stylized 3D') {
        return `${require('./relationship_3d_style').LOCATION} ${brightVisualText(place.description)} One empty location reference image, wide composition showing the full setting. No people or animals, text, labels or watermark. ${BRIGHT_LOCATION}`;
    }
    if (preset.id !== 'relationship-dialogue-real' && preset.niche !== 'Relationship Dialogue (Realistic)') return brightVisualText(original) + (original.includes('LOCATION LIGHTING:') ? '' : ' ' + BRIGHT_LOCATION);
    // Character reference artwork must never choose the location's medium.
    const details = brightVisualText(place.description).trim();
    return `Photorealistic location photograph, cinematic 4K quality. ${details} `
        + 'One empty location reference image, straight-on wide view, the whole setting clearly readable. '
        + 'Natural photographic lighting, realistic shadows and reflections, true-to-life perspective, physical fabric, wood and wall textures. '
        + 'The environment must look like a real filmed location. No people or animals. No text, labels or watermark. '
        + BRIGHT_LOCATION + ' '
        + 'No cartoon, anime, Ghibli aesthetic, illustration, ink outlines, cel shading, watercolor or painted rendering.';
}
module.exports = { locationPrompt, BRIGHT_LOCATION, brightVisualText, isRelationship, withBrightLocation };
