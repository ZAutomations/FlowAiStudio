const fs = require('fs');
const path = require('path');
function thumbnailPrompt(story, ratio = '16:9') {
    const concept = story.thumbnail || {};
    const headline = String(concept.headline || story.title || '').split(/\s+/).slice(0, 5).join(' ');
    return `Create a compelling ${ratio} YouTube thumbnail for "${story.title}".
MAIN TOPIC: ${story.description || story.title}
VISUAL HOOK: ${concept.visual_concept || story.description || story.title}
STYLE: ${story.style || story.visual_style || story.niche || 'Match the video artwork'}
CHARACTERS: ${Object.keys(story.character_descriptions || {}).join(', ') || 'Use the actual subjects of the story'}. Use the supplied reference sheets; preserve their exact faces, hair, ages and clothing.
Use one clear focal idea, expressive faces when appropriate, strong readable contrast and a simple background. The topic must be understandable at phone size. Keep important faces and details inside safe margins.
Optional headline: "${headline}". Maximum five words, large readable lettering. Leave the text area clean if accurate lettering is unavailable.
Show the actual central tension or discovery of this video. Do not invent events, accusations, violence or misleading claims. No watermarks, logos, interface elements or multi-panel reference-sheet layouts.
`;
}
function writeThumbnailPrompts(folder, story) {
    fs.writeFileSync(path.join(folder, 'thumbnail_prompt.txt'), thumbnailPrompt(story), 'utf8');
    fs.writeFileSync(path.join(folder, 'thumbnail_prompt_vertical.txt'), thumbnailPrompt(story, '9:16'), 'utf8');
}
module.exports = { thumbnailPrompt, writeThumbnailPrompts };
