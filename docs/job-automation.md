# Retry and part compilation

Compile video part card (AI Studio and Animate):
- Auto retry failed processing tasks: unlimited attempts, 5 or 10 second delay (default 10). Captured when a job starts. Existing saved jobs without this flag keep their old behavior.
- Auto compile selected part after images are saved: opt-in. Set Start and End before Generate Images / Generate Missing / image download. After the phase succeeds, all selected scene files are decoded/validated before Compile Selected Part runs. A successful incomplete scan cannot render an incomplete part.

Retry reuses the same job, saved settings and project checkpoints; attempts are logged. Existing-output checks, exact scene identities and provider restriction handling remain active. This does not turn a quota, login or unusual-activity restriction into permission to generate. Repeated failures may still require user action; Stop ends the countdown/retry chain. App shutdown stops active work; restart does not silently resume interrupted jobs.

Audio-first parts require whole-story verified narration. Captions/transitions follow Compile Selected Part settings. Auto-compile is a direct backend operation, not a simulated button click. Generation/download actions trigger it; a separate unrelated failed job does not. Keep the app running for retries and compilation. Retries have no attempt cap, so use Stop if an unchanged error requires intervention.
