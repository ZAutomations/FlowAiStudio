"""Offline model and bundled browser-driver verification; no generation requests."""
from pathlib import Path
import subprocess
from faster_whisper import WhisperModel
root=Path(__file__).resolve().parents[1]
model=root/'models/whisper/faster-whisper-base'
WhisperModel(str(model),device='cpu',compute_type='int8',local_files_only=True)
print('Bundled Whisper base loads offline.',flush=True)
subprocess.run([str(root/'runtime/node/node.exe'),'-e',"console.log('Bundled Puppeteer:',require.resolve('puppeteer'))"],cwd=root/'animate_flow_backend',check=True)
import sys
sys.path.insert(0,str(root))
import gemini_api_tts_helper
print('Gemini TTS helper imports successfully; no API call made.')
