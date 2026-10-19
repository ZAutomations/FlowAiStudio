# Flow AI Studio — independent desktop application

Only two workspace tabs are included: **AI Studio** and **Animate**. Voice, audio, credentials and **Pro Captions (ASS)** are available through App settings. Everything runs against a local FastAPI backend in a pywebview desktop window.

## Start

1. Open **Setup.bat** once. It creates this app's own Python environment under %LOCALAPPDATA%/FlowAiStudio on C: and installs dependencies. Models and binaries stay in this app folder. Python, Node, FFmpeg, FFprobe, Kokoro models and all installed Piper voices are bundled.
2. Open **FlowAiStudio.bat**.
3. Add/login a Google browser account in the app. Google Chrome and the Microsoft Edge WebView2 runtime must be installed on the computer. The first dependency installation needs internet; Gemini and browser generation always need internet.

## Included

Scene planning, visual/story presets, unchanged narration, reviewed cast/location analysis, fixed DSPMalik references, automatic/manual reference generation and upload, automatic/manual prompt batches, exact scene recovery, one image per scene, model/account fallback, thumbnails, Excel batches, partial exports, independent checkpoints, Stop/Retry, Gemini TTS, Kokoro, Piper, image camera motion, ASS captions and final render.

## Rendering boundary

The original editor's transition/effect processors, LUTs, overlays, particles, SFX and non-ASS caption engines are **not included**. Current joins are clean cuts. This folder is the starting point for your own transitions; image camera motion remains an optional AI Studio feature. Imported projects cannot enable the removed render engines.

## Move to another Windows x64 machine

Copy this entire folder, including `runtime`, `VoiceModules`, `assets`, and `animate_flow_backend/node_modules`. Run Setup.bat on the new machine to create that machine's independent per-user environment. No original application's environment is used. Projects are separate data folders; copy any projects you want and open their saved `project.json`. Local scene/reference/voice paths are preserved inside each project where possible.

Browser login sessions are intentionally separate from the old app. Sign in yourself on the new machine. API keys are protected with Windows DPAPI, so enter them again in Credentials on another machine. Never upload `private`, `.desktop`, or browser-profile folders to a public repository. A service-account JSON selected in Credentials is copied into the private local app folder.

Kokoro and Piper work locally once Setup completes. Gemini TTS uses your own key or service account. The service-account API project may require its existing Google configuration. No purchases or provider requests are made by Setup or verification.

## Verify

Run `runtime\python\python.exe bootstrap.py verify` for the dependency/binary check, or `runtime\python\python.exe bootstrap.py test` for offline regression tests. `tools\smoke_media.py` synthesizes a short local Piper/Kokoro sample and renders a small ASS-captioned video, without calling paid providers.

The original Video Automation Studio installation and its projects are unchanged.

## GitHub source checkout

This repository stores source, UI assets, tests and dependency manifests. It excludes credentials, browser sessions, local settings, generated projects, installed node_modules, and the large portable runtime/model bundle.

To reproduce the current portable installation, copy `runtime/` and `VoiceModules/` from the working FlowAiStudio distribution into the checkout. Run `runtime\node\node.exe` with `npm ci` in `animate_flow_backend` (or copy its installed `node_modules` from the same distribution), then run `Setup.bat`. Keep the entire local app folder for transfer to another machine; a Git clone alone does not contain voice model weights or bundled executables.
