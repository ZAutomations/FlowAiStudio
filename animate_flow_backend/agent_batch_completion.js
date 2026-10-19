// Require two consecutive complete observations, with no active/error tiles.
// One optimistic snapshot must never release the next group of prompts.
function completionTracker(expected) {
    let stable = 0;
    return media => {
        const complete = expected > 0 && media.ready_video_tile === expected
            && media.failed_video_tile === 0 && media.generating_video_tile === 0
            && !media.agent_busy && media.project_scan_complete !== false;
        stable = complete ? stable + 1 : 0;
        return stable >= 2;
    };
}
module.exports = { completionTracker };
