# Existing Audio + Script (optional)

The default remains Existing workflow / generate TTS. Existing saved TTS projects keep their workflow.

1. Prepare a complete final recording and its exact script. Use clean single-narrator speech, without background music. Review repeated/missing passages before import.
2. Start a fresh AI Studio or Animate project. Import the matching ready story JSON, including the full narration and visual/reference assignments. Existing media projects are protected from automatic retiming.
3. Voice card > Audio workflow > Audio first / existing audio + script. Paste the complete local WAV, MP3, M4A or FLAC path.
4. AI Studio: press Align Existing Audio. Animate: Narration-first cinematic is selected automatically; press Plan Cinematic Clips to align and create the measured clip/image plan.
5. Local faster-whisper alignment requires processing time. Base, small and medium caches are reused. A mismatch blocks timing publication; no guessed durations and no TTS requests.
6. Review scene timings / cinematic plan, review cast, create references and generate media. Imported ChatGPT directions do not require Gemini planning; optional non-ready story planning can still use the selected LLM.
7. Render uses the supplied performance, converted to local PCM and sliced at verified boundaries. Concatenating the image-scene PCM slices preserves the imported PCM samples without extra pauses. Captions and enabled transitions follow the existing renderer.
8. Parts: align the complete story first, then choose start/end scene numbers and Compile Selected Part. Parts reuse verified audio rather than realigning the entire recording against a partial script.

The original recording is never modified. Cached PCM/recognized words and manifests live under voice/imported/<identity>. A changed recording or narration gets a separate cache. Automatic switch to another voice is never performed.

Speech recognition is fallible: the match check is a guard, not proof of flawless pronunciation. Review the aligned plan and listen before a long final render. This workflow supports one full recording, not independent per-part recordings or dialogue speaker diarization.


## Targeted repair and boundary review
Once any full transcript passes the recording/script coverage check, further boundary repairs use only unresolved spans between verified anchors (up to 60 seconds each). Full-story model fallback is still allowed when the global recording/script check itself fails. Recognition windows, model results and verified anchors are cached for retry.

If short-window repairs cannot resolve a boundary, open Voice > Review audio boundaries. The dialog shows preceding/next narration, recognized words, verified neighbouring times and an audio excerpt with its absolute offset. Enter the exact next-scene start in seconds. Save corrections, then Retry alignment. Only unresolved times can be changed, in increasing order and within verified neighbours; global coverage failures cannot be bypassed manually. Changes are locked after scene images/clips exist. Your original audio is never edited.
