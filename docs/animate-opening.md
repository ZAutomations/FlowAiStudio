# Opening animation and ChatGPT master prompts

Restart the app. Animate → Animation mode → Partial animation. Opening animation measured by offers Number of opening scenes (for example 10, without the old 3-scene cap) or Opening narration seconds (for example 80). Full animation selects all scenes.

For seconds mode, Generate Agent Media generates/reuses narration first to measure the exact opening span. Every scene starting before the cutoff needs a video clip. At a cutoff inside a scene, the last animated frame is held as a still for the remainder; subsequent scenes use still images. The scene count estimate shown before audio exists is advisory. New plans use eight-second generated clips with 2–4 sequential shots inside ONE clip; six-second legacy mode remains available. Still-image rows remain narration-based. Internal shots are not separate media requests; final narration controls the scene duration. Completed media/checkpoints are retained across selection changes.

Master prompts / Import JSON opens two copyable ChatGPT prompts: partial and full. Current style, resolution and opening selection are appended to the copied prompt. Add your script and reference descriptions before sending it to ChatGPT. ChatGPT returns visual scene directions; the app generates media through the selected provider/model.

Paste ChatGPT's complete JSON into that same dialog and Import ready story into a new empty Animate project. Import keeps narration unchanged and loads the prepared scene visual prompts. Existing generated projects cannot be replaced through import. Select/create reference images normally. Then Generate Agent Media / Build All. Imported prompts are reused without an extra Gemini rewrite; Write Story remains available when you explicitly want to replace them.

Standalone master prompt files: animate-master-prompt-partial.md and animate-master-prompt-full.md in docs/. A first-80-seconds plan is estimated by ChatGPT; actual TTS duration in the app is authoritative. Neither master prompt adds voices/music to generated raw clips; local narration and captions are mixed at export.

Master JSON video rows may contain a shots array of 2–4 items with start/end/visual_prompt. Times are local to the clip, contiguous, and cover its complete duration. The scene table tracks generated media/narration segments, not each internal camera shot. Use a new project to replan an existing generated story into multi-shot clips. Existing legacy project defaults remain unchanged.

An 8-second clip can contain 2–4 timed sequential shots, not separate media requests. The rest of the image section remains narration-based. Set Generated clip duration to 8 seconds and enable multi-shot planning. Use a new project when changing an existing generated story into this structure.
