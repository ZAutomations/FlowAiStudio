# Flow AI Studio Portable — Windows 10/11 x64

1. Copy this **entire folder**, including hidden `.git`, to the other PC. Do not copy only the launcher.
2. Run `Setup.bat` (or `setup/Setup.bat`). Internet is needed for missing Python packages and missing system apps. Windows may ask for installation permission.
3. Run `FlowAiStudio.bat`. Configure your API keys and sign into your browser accounts on this PC.
4. Run `Update.bat` for GitHub updates. It uses `git pull --ff-only`, then checks dependencies. Local changes are never forcibly reset. GitHub access/sign-in may be required.

Bundled: portable Python, Node, FFmpeg/FFprobe, Puppeteer, Kokoro/Piper engines and voices, and faster-whisper **base** in `models/whisper/faster-whisper-base`. Base alignment needs no model download. Selecting small/medium/large may download another model. GPU acceleration is optional; CPU works without CUDA.

Setup skips existing Git, Chrome and WebView2 Runtime. Missing apps install through Windows App Installer (`winget`); if winget is unavailable, install **App Installer** from Microsoft Store and rerun setup. Python packages install into a separate per-user environment; satisfied requirements are reused. Requirements live at the app root; `setup/requirements.txt` is a convenient mirrored copy.

Private settings, API keys, browser sessions and existing projects are intentionally excluded. Projects created here stay in `Projects`. Keep backups before moving or updating. Binary runtimes/voices/models are bundled in this folder but excluded from Git; Git updates do not download them again.

Diagnostic check without installing: `powershell -NoProfile -ExecutionPolicy Bypass -File setup/Install.ps1 -CheckOnly`.
