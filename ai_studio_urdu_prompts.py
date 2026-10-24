"""Local DSP transcript preparation prompt; no API calls or project mutations."""
from pathlib import Path

def master_prompt():
    return (Path(__file__).resolve().parent / 'docs' / 'dsp-hindi-to-urdu-master-prompt.md').read_text(encoding='utf-8')
