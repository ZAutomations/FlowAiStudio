function hasPastedTranscript(detail) {
    const text = String(detail || '');
    return (text.match(/>>/g) || []).length >= 2
        || /(?:^|\n)\s*(?:transcript|source dialogue|video transcript)\s*:/i.test(text)
        || (text.match(/(?:^|\n|>>)\s*(?:Sarah|George|male|female|man|woman|husband|wife|speaker\s*[12]|person\s*[ab])\s*:/gi) || []).length >= 2;
}
function resolveTranscriptPreset(id, title, detail) {
    return id === 'ghibli' && hasPastedTranscript(detail)
        && /\b(relationship|marriage|married|wife|wives|husband|cheat|cheating|cheated|partner|couple|betrayal)\b/i.test(`${title} ${detail}`)
        ? 'relationship-dialogue-ghibli' : id;
}
module.exports = { hasPastedTranscript, resolveTranscriptPreset };
