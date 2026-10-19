"""Standalone workflow boundary: three voices, ASS captions and clean cuts only."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
VOICES=('google_cloud','local','piper')
def normalize(config):
    c=dict(config);s=dict(c.get('settings',{}))
    c.update(use_transitions_tab=False,use_effects_tab=False,transition='Cut',transition_seconds=0)
    c['agent_tool_dir']=str(ROOT/'animate_flow_backend')
    if c.get('voice_engine') not in VOICES:c['voice_engine']='google_cloud'
    s.update(use_cloud_tts=False,caption_highlight_enabled=False,enable_captions=False)
    s['kokoro_model_path']=str(ROOT/'VoiceModules/KokoroTTS')
    if (ROOT/'private/google_service_account.json').is_file():s['service_account_path']=str(ROOT/'private/google_service_account.json')
    c['settings']=s
    return c
