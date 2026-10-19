# Continuous narration for image videos

In AI Studio → Voice, choose **Narration workflow → Continuous narration · images only**.
Use **Generate Voice**, then **Render Video** for existing images, or **Build All** for a new video.
Build All creates narration before generating the images. Existing scene plans, image identities and
download checkpoints stay intact. Compile Selected Part also supports this mode for its selected range.

The selected Gemini TTS, Kokoro or Piper voice reads adjacent narration in larger chunks (up to about
2,400 characters, preserving scene text). Short videos normally need a single synthesis request.
Long stories need multiple requests; this reduces voice resets but cannot guarantee identical delivery
between those requests. A chunk never switches to another TTS engine automatically.

A local multilingual faster-whisper model measures word timestamps. Source script matching locates
image boundaries; the audio is split as lossless PCM at those measured boundaries. Rendering concatenates
the original samples without adding pauses. The complete master is saved under
`voice/continuous/<identity>/narration.wav`. Captions use measured word timing.

**Small** is the recommended alignment model; **Base** is faster and **Medium** may improve difficult
matching. First use downloads the selected model and requires internet. Later use is local. Run Setup.bat
after updating to install faster-whisper. Alignment is a separate local step and does not use Gemini keys.

Audio chunks and word timestamps are checkpointed. A retry reuses completed audio; changing only the
alignment model does not regenerate narration. A failed/uncertain boundary stops rather than guessing
durations; choose a stronger alignment model and retry. Old scene audio remains available until the
complete new timing has been verified. Changing narration, voice or delivery creates a separate cache.

This mode applies only to AI Studio image videos. Animate keeps its existing narration workflow.
