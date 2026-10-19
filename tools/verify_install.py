"""Check bundled assets and imports without generating media or calling providers."""
import importlib,json,sys,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from runtime_paths import configure
configure()
errors=[]
for name in ('fastapi','uvicorn','webview','requests','PIL','numpy','soundfile','kokoro_onnx','onnxruntime','playwright.sync_api','google.auth','openpyxl','faster_whisper'):
    try:importlib.import_module(name)
    except Exception as e:errors.append(name+': '+str(e))
for name in ('desktop.worker','desktop.server','studio_voice','clipper_captions','ai_studio_animate'):
    try:importlib.import_module(name)
    except Exception as e:errors.append(name+': '+str(e))
for name in ('ffmpeg','ffprobe','node'):
    found=shutil.which(name)
    if not found or not Path(found).resolve().is_relative_to(root):errors.append('Bundled '+name+' is missing')
for name in ('VoiceModules/KokoroTTS/kokoro-v0_19.onnx','VoiceModules/KokoroTTS/voices-v1.0.bin','VoiceModules/PiperTTS/bin/piper.exe'):
    if not (root/name).is_file():errors.append('Missing '+name)
if errors:
    print('\n'.join(errors));raise SystemExit(1)
print('Standalone imports and bundled engines verified.')
print('Local Piper voices:',len(list((root/'VoiceModules/PiperTTS/voices').glob('*.onnx'))))
print('Gemini API keys and Google browser login must be configured on a new machine.')
