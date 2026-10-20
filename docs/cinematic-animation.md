# Narration-first cinematic Animate

This is an optional new workflow in Animate. Existing scene-wise projects retain their current behavior.
Use **New Animate Project** before switching a project with generated images/clips to this workflow.

1. Paste/import the complete unchanged script. Imported ChatGPT JSON may supply semantic beats;
   its estimated shot timing is replaced by measured narration timing in this mode.
2. Choose **Narration & continuity workflow → Narration-first cinematic · 8-second clips**.
3. Select the voice engine, voice, narration style and alignment model (Small recommended).
4. Choose Full, or Partial with opening narration seconds/count. In this mode a count means
   eight-second opening clips; 80 seconds means ten clips unless the complete narration is shorter.
5. Choose visual style, aspect ratio, model and cast/location references. Keep recurring subjects in
   Character references mode; documentary/no-reference mode does not invent a recurring cast.
6. Press **Plan Cinematic Clips** (the Write Story action in this mode). It creates/reuses continuous
   narration, measures words locally, and asks Gemini for the actual timed visual plan. Gemini keys
   are required for this directing step even when Piper or Kokoro provides the narration.
7. Press **Review Cinematic Plan** to inspect narration windows, locations, start/end states,
   reference assignments and the 2–4 shots inside each video clip.
8. Press **Generate Agent Media**, then **Render Video**, or use **Build All** for the whole sequence.

## Timing and continuity

Generated video outputs are eight seconds. Narration windows use the measured PCM sample clock;
the final/partial-boundary clip is trimmed if necessary. The remaining still-image section follows
the source narration beats and measured durations. Speech can continue across a visual cut without
restarting synthesis. Original words and their order are retained. Most timestamps are ASR-matched;
small unmatched word spans are interpolated for captions/visual planning, without changing audio.

Each video has 2–4 sequential shots with local times 0–8 seconds. A clip is one generated asset,
not a separate request for each internal shot. The director retains the full story context and
previous end state. Continuations must use the exact same location/start state as the previous end;
genuine time/place changes are marked explicitly.

Connected video clips are generated sequentially. Once the preceding clip is verified and downloaded,
its actual final frame is extracted and uploaded as `PreviousClipNNNN.png` alongside the needed cast
references. The prompt asks the model to use it as starting visual guidance and advance the action.
This uses Flow Agent's named image-reference mechanism; it is **not** a guaranteed first-frame lock
or a model-native extend-video API. Generative models can still deviate and results need review.
Remaining still images can use normal batches.

Rendering uses natural cuts, keeps the local continuous narration, and discards generated clip audio.
Camera transition/SFX and legacy transition settings are bypassed in this mode. A downloaded video
that is shorter than its needed narration window is rejected rather than hiding missing action with
a frozen end frame. BGM, captions and other independently selected render settings still apply.

## Saved work

`cinematic_source.json` preserves the source scene plan. `cinematic/<identity>/planning.json` saves
completed Gemini planning batches; `storyboard.json` locks the final timeline, prompts and states.
Continuous narration is cached under `voice/continuous/`; generated requests use the existing
`animate_media.json` checkpoint. Completed clips are reused on retry, including after restarting.
Changing voice/timing/style after generation requires restoring the original settings or a new
project. No old media/request identities are silently reassigned to a different cinematic timeline.

Long narration uses larger TTS chunks, so completely identical vocal delivery across those requests
is not guaranteed. First alignment use may download the selected local multilingual model.

Validation includes exact PCM reconstruction, measured full/partial windows, unchanged narration,
continuity validation, actual FFmpeg renders, last-frame extraction and a simulated sequential Agent
run with verified attachments and no duplicate submissions on retry. Live paid Flow generation is
not part of these automated tests.

Speech models are cached under `%USERPROFILE%/.flow_ai_studio/speech_models` on C:, keeping the video project drive free for media.


## Fast video + image JSON workflow

In Animate, open **Video + Image JSON**, copy its master prompt to ChatGPT and supply the full
script, visual preset, reference identities and number of opening eight-second clips. Ask for
`video_clips.json` and `image_scenes.json`. Paste both into that dialog and import into a new
empty project. Both files together must retain the complete original narration in order.

Press **Plan Cinematic Clips** to create/reuse continuous narration and measure timings locally.
Ready directions bypass the Gemini director completely. Review the resulting plan because
ChatGPT duration estimates can differ from actual speech. Then press **Generate Video Clips Only**,
followed by **Generate Remaining Images**, then **Render** (or Build All to complete missing work).
These buttons share one project and checkpoint; they do not create disconnected stories.

Without ready directions, automatic cinematic planning now requests only video clips, in groups
of four, with bounded context. Image prompts are reused from the source plan locally. Completed
storyboards remain cached. One next narration chunk is synthesized while current audio is aligned;
voice generation and local alignment remain necessary and are not eliminated by JSON import.


## Full-story cast in Animate

In **References**, enable **Full story character/location consistency**. Parse/import the story,
then choose **Analyze full script** or **Import ready cast / story**. Review all characters, aliases,
locations and per-scene assignments; approve before generation. The library supports 40 approved
identities, with at most six assigned references per scene. Full mode supersedes the legacy
two-character/one-location controls.

**Create / reuse all references** generates missing named images, keeps valid saved images and
uploads the entire library to the selected Flow project. A permanent DSPMalik path skips his
generation. You may instead export reference prompts, generate manually, then use **Download,
rename & upload references**. Supplied libraries must use the approved identifier filenames.
Use **Show saved reference library** to inspect all saved character/location images.

Each video request attaches only its assigned cast/location subset; continuous narration regrouping
carries assignments from the overlapping source narration. Connected cinematic clips also receive
the previous clip's final frame. Image batches keep their combined reference library within six;
prompts specify each image's own identities. More than six required identities in one measured clip
produces a review error rather than silently dropping identities.

Both ordinary ready-animation JSON and split video/image JSON may declare an `assets` array.
The updated master prompt includes the schema. Split imports create a reviewable cast without an
additional discovery call; video directions still skip the Gemini director. Existing prepared audio
is retained. Cast/design changes after reference or media submission require a separate project;
old checkpoints are not reassigned to new identities.

Verified with disposable projects, a five-reference UI review/approval, exact per-clip identity keys,
regrouping, review gates, library upload calls, split import and existing narration/retry tests.
Paid live Flow generation was not exercised by these tests.


## Detailed continuity ledger (additive, video clips only)

Open **Continuity Ledger** in Animate. **Prepare / resume continuity ledger** reads the existing
reviewed video plan and builds `continuity_ledger.json`, four video clips per metadata call. It
never synthesizes narration, changes clip timings, replaces visual prompts, or generates images.
Saved entries resume after interruptions. Images retain their existing workflow.

The ledger records each clip's before/after state and evidence-backed changes: character wardrobe,
location, held props, injuries and emotion; prop description, holder, location and condition; clue
status and which characters know it; scene time, place and lighting. Unchanged facts carry forward,
including off-screen characters. Unspecified facts remain unknown. Inference must be reviewed; it
is based on narration/planned visuals, not visual inspection of already-generated footage.

**Review continuity ledger** shows states and editable supported updates. Submitted/generated clips
are locked, including edits earlier in the ledger that would change a later locked state. Each
new video request includes its ledger constraints outside the immutable scene tracking identity.
Enabling the ledger does not change existing keys or resubmit completed media.

For a project whose narration and cinematic plan already exist but cast was never defined:
1. Enable Full story character/location consistency.
2. Analyze full script, review the discovered cast and scene assignments, and approve. No reimport.
3. Create / reuse all references.
4. Prepare / resume the ledger and review it.
5. Generate the remaining video clips, remaining images, then Render.

Late cast analysis keeps the reviewed cinematic timeline and valid audio. A public migration receipt
proves the previous model/scene/project context before retaining completed or uncertain media
tracking identities; only unissued requests gain new cast attachments. It does not retroactively
correct faces or continuity in already-produced media. Changed story/model/design is not treated
as a compatible resume. No automatic deletion of audio, plans, images or browser assets occurs.
