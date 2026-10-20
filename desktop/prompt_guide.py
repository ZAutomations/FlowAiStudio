"""Local prompt library sourced from the same validators/workflows as the app."""
def content():
    from ai_studio_animate_prompts import master_prompt,split_master_prompt
    from ai_studio_cast import MASTER_PROMPT
    from ai_studio_pipeline import STYLE_PRESETS
    return {'visual_presets':dict(STYLE_PRESETS),'prompts':[
        {'id':'split','title':'Opening videos + remaining images','use':'Fresh Animate project: choose 10, 15 or any number of opening clips. Includes complete cast and locations.','input':'Title, complete narration, clip count, selected visual preset, ratio and any existing identity descriptions.','output':'video_clips.json + image_scenes.json + thumbnail_prompts.json (4 concepts) + video_metadata.json','import':'Animate → Video + Image JSON → paste both files → Import both JSON files. Review and approve cast.','text':split_master_prompt()},
        {'id':'partial','title':'Partial animation · single JSON','use':'Alternative single-file Animate import for opening animation plus still images.','input':'Complete narration, opening clip count/seconds, visual preset and reference designs.','output':'ready_story.json + thumbnail_prompts.json (4 concepts) + video_metadata.json','import':'Animate → Master prompts / Import JSON → paste ready-story JSON → Import ready story. Use a fresh empty project.','text':master_prompt('partial')},
        {'id':'full','title':'Full animation · single JSON','use':'Every narration section becomes an animated clip.','input':'Complete narration, visual preset, ratio and reference designs.','output':'ready_story.json + thumbnail_prompts.json (4 concepts) + video_metadata.json','import':'Animate → Master prompts / Import JSON → Import ready story. Review cast if assets are included.','text':master_prompt('full')},
        {'id':'cast','title':'Cast & locations · existing numbered scenes','use':'Use when a story/plan already exists but no characters or locations were defined. Preserves scene numbers and narration.','input':'Full script, selected visual style and ALL existing numbered scenes with their exact narration. The Animate import dialog adds these automatically.','output':'JSON with assets and per-scene reference assignments','import':'Animate → References → Import ready cast / story. Review → Approve. Do not use Video + Image JSON to replace an existing plan.','text':MASTER_PROMPT+'\nIMPORTANT: I supply EXISTING NUMBERED SCENES below. Keep their scene numbers, count and narration exactly unchanged. Return complete JSON for cast review only; do not replan shots, timing or narration.\nVisual preset: [PASTE]\nFull script: [PASTE]\nExisting numbered scenes: [PASTE ALL SCENES]'}],
        'steps':[
            'New Animate Project banayein; title, visual preset, 16:9 ratio, video model aur voice select karein.',
            'Narration & continuity workflow mein Narration-first cinematic select karein.',
            'Opening videos + remaining images prompt copy karein. Selected visual preset aur clips count prompt mein automatically shamil honge; ChatGPT ko copied prompt aur apni script dein.',
            'ChatGPT ke dono complete JSON files Video + Image JSON mein paste karke Import both JSON files dabayein. Naya empty project use karein.',
            'Review cast & locations mein faces, clothes, period, places aur har scene ki references check karein. Approve reviewed cast karein. Assets included hon to Analyze full script dobara nahi chahiye.',
            'Permanent DSPMalik reference chahiye to uska path dein. Create / reuse all references dabayein; valid saved references reuse aur complete library upload hogi.',
            'Plan Cinematic Clips dabayein. Continuous narration aur actual audio timings tayar hongi. Ready directions hon to Gemini director skip hoga.',
            'Review Cinematic Plan mein video/image split, shots aur narration windows check karein.',
            'Continuity Ledger → Prepare / resume continuity ledger → Review continuity ledger. Props, injuries, clues aur emotions check karein.',
            'Generate Video Clips Only dabayein; connected clips previous final-frame guidance use karte hain.',
            'Generate Remaining Images dabayein. Existing valid files reuse hongi.',
            'Render dabayein. Local narration aur selected Pro ASS captions final video mein combine honge.'],
        'resume':[
            'Existing project open karein. New project, Parse Scenes ya ready-animation reimport se dobara shuru na karein.',
            'Cast missing ho to Full story character/location consistency enable karein. Analyze full script, ya Cast & locations prompt se exact existing-scene JSON import karein. Review → Approve → Create / reuse all references.',
            'Existing reviewed cinematic timeline, narration aur downloaded images retain hote hain. Ledger sirf nayi metadata banata hai; generated footage ko retroactively fix nahi karta.',
            'Missing clips/images generate karein; failed task ka Retry saved checkpoint se resume karta hai. Complete hon to Render.'],
        'notes':[
            '8 seconds sirf animated video clips ke liye hain. Baqi still images: narration ke natural beats, mostly 4 seconds, aam tor par 2-6 seconds. Actual duration measured voice se aati hai; images ko 8-second video windows mein group na karein.',
            'ChatGPT output: story JSON files, thumbnail_prompts.json (4 prompts), video_metadata.json (best title, alternatives, description, hashtags, tags). Sirf story JSON import karein; thumbnails aur posting metadata alag files hain, automatic generation/upload nahi hota.',
            'Har 8-second video clip: 2-3 distinct shots, default 0-3 / 3-6 / 6-8 seconds. Har boundary par HARD CUT; sirf pan/zoom multi-shot nahi. Narration, cast, props aur screen direction consistent rakhein. Existing downloaded clips khud replace nahi hotay; updated directions new requests par apply hoti hain.',
            'Split aur single-file prompts alternatives hain. Fresh project ke liye split prompt recommended hai; sab prompts ek ke baad ek import nahi karne.',
            'Continuous voice generation aur local speech alignment phir bhi required hain. ChatGPT ke time estimates actual measured timings nahi hain.',
            'Ready ChatGPT JSON uses imported continuity locally without Gemini planning. Detailed continuity_updates supplied hon to woh carry hotay hain; missing facts unknown rehte hain. Ordinary non-ready workflows may still use optional Gemini analysis.',
            'References: maximum 40 story identities; maximum six assigned references per scene. Images ke liye multi-shot video directions na dein.',
            'Manual reference prompts project-specific hain: References → Export reference prompts. Manually generate karein, phir Download, rename & upload references dabayein. Generic prompt se exact download tracking IDs replace na karein.',
            'Credentials, API keys, account cookies aur passwords ChatGPT prompts mein paste na karein.']}
