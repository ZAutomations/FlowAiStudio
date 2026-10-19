// A conversation error may happen before Flow schedules any video. A partial
// batch, an unknown outcome, or an unrelated conversation must never be replayed.
function failedBeforeMedia(snapshot, pendingPrompt) {
    const mt = snapshot.mediaTiles || {};
    if (!snapshot.agentOn || snapshot.promptText === null
        || mt.flow_video_tile !== 0 || mt.ready_video_tile !== 0
        || mt.failed_video_tile !== 0 || mt.generating_video_tile !== 0) return false;
    const rows = snapshot.conversationRows || [];
    const last = rows[rows.length - 1];
    const request = rows[rows.length - 2];
    if (!last || !request || last.role !== 'agent' || request.role !== 'user'
        || !last.error || !/something went wrong|please try again/i.test(last.text)) return false;
    const normalize = text => String(text || '').replace(/\s+/g, ' ').trim();
    const prompt = normalize(pendingPrompt);
    // Reference chips may precede the text. Match the entire text, not merely
    // a scene count that could belong to a different film or batch.
    return prompt.length > 100 && normalize(request.text).includes(prompt);
}

module.exports = { failedBeforeMedia };
