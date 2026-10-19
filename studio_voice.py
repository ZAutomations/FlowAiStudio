import math, re, os, json, subprocess, shutil, time, traceback
from pathlib import Path
import numpy as np
import piper_tts_helper as _piper_tts
_SHORT_WORDS = {'a', 'an', 'the', 'to', 'in', 'of', 'for', 'on', 'at', 'by', 'with', 'from', 'as', 'is', 'it', 'its', "it's", 'and', 'or', 'but', 'so', 'if', 'no', 'not', 'up', 'out', 'be', 'he', 'she', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'our', 'i', 'you', 'are', 'was', 'were', 'been', 'do', 'does', 'did', 'has', 'had', 'have', 'can', 'could', 'will', 'would', 'shall', 'should', 'may', 'might', 'must', 'than', 'that', 'this', 'these', 'those', 'there', 'their', 'them', 'then', 'which', 'what', 'when', 'where', 'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'some', 'any', 'such', 'only', 'own', 'same', 'too', 'very', 'just', 'also', 'else', 'off', 'over', 'here', 'there'}
def refine_word_timings_smart(word_timings, total_duration, audio_path=None):
    """Refine word timings using smarter syllable-based model + VAD gap detection.

    The old character-weighted model (equal time per character) causes ~0.3-0.5s
    drift because short function words (spoken fast) get too much time while
    long content words (spoken slower) get too little.

    This function replaces naive linear-char weighting with:
    1. sqrt(char_count) weight - compresses range between short/long words
    2. Function-word discounts - words like 'the', 'a', 'and' get 40% less time
    3. Punctuation pauses - 120ms pause added after . ! ?
    4. VAD gap detection - if audio_path given, uses pydub silence detector to
       align word boundaries to actual speech gaps in the audio waveform
    5. Scale-preserving - total duration is maintained regardless of weighting

    Returns: updated word_timings (mutated in-place and returned)
    """
    word_count = len(word_timings)
    if word_count == 0 or total_duration <= 0:
        return word_timings
    weights = []
    total_weight = 0.0
    for w in word_timings:
        word = w['word']
        weight = math.sqrt(max(1, len(word)))
        if word.lower() in _SHORT_WORDS:
            weight *= 0.6
        if len(word) > 8:
            weight *= 1.2
        weights.append(weight)
        total_weight += weight
    if total_weight <= 0:
        return word_timings
    current_time = 0.0
    for i, (word_info, weight) in enumerate(zip(word_timings, weights)):
        word_info['offset'] = current_time
        word_duration = weight / total_weight * total_duration
        word_duration = max(0.06, word_duration)
        word_info['duration'] = word_duration
        current_time += word_duration
    pause_indices = []
    for i, w in enumerate(word_timings):
        word = w['word']
        if word and word[-1] in '.!?' and (i < word_count - 1):
            pause_indices.append(i)
    if pause_indices:
        pause_per = min(0.12, total_duration * 0.02)
        shift_acc = 0.0
        for i in range(word_count):
            word_timings[i]['offset'] += shift_acc
            if i in pause_indices:
                word_timings[i]['duration'] += pause_per * 0.3
                shift_acc += pause_per * 0.7
    if audio_path and audio_path.exists():
        try:
            _refine_with_vad_pydub(word_timings, audio_path)
        except Exception:
            pass
    last_end = word_timings[-1]['offset'] + word_timings[-1]['duration']
    if last_end > 0 and abs(last_end - total_duration) > 0.02:
        scale = total_duration / last_end
        for w in word_timings:
            w['offset'] *= scale
            w['duration'] *= scale
    return word_timings
def _refine_with_vad_pydub(word_timings, audio_path):
    """Refine word timings by aligning to actual speech gaps via pydub VAD.

    Detects natural pauses in the TTS audio waveform, then maps word boundaries
    to those pauses for frame-accurate sync that's far better than any
    character-based model.
    """
    from pydub import AudioSegment
    from pydub.silence import detect_silence
    audio = AudioSegment.from_file(str(audio_path))
    duration_ms = len(audio)
    if duration_ms <= 0:
        return
    silent_segs = detect_silence(audio, min_silence_len=80, silence_thresh=-25, seek_step=10)
    if not silent_segs:
        return
    speech_segs = []
    prev_end = 0
    for start_ms, end_ms in silent_segs:
        if start_ms > prev_end:
            speech_segs.append((prev_end, start_ms))
        prev_end = end_ms
    if prev_end < duration_ms:
        speech_segs.append((prev_end, duration_ms))
    if not speech_segs:
        return
    total_s = duration_ms / 1000.0
    word_count = len(word_timings)
    counts = [0] * len(speech_segs)
    for w in word_timings:
        s = w['offset']
        for si, (ss, se) in enumerate(speech_segs):
            if ss / 1000.0 <= s <= se / 1000.0:
                counts[si] += 1
                break
    idx = 0
    cur_s = 0.0
    for si, (ss, se) in enumerate(speech_segs):
        nw = counts[si]
        if nw == 0:
            continue
        seg_s = (se - ss) / 1000.0
        sw = []
        for j in range(idx, min(idx + nw, word_count)):
            word = word_timings[j]['word']
            wt = math.sqrt(max(1, len(word)))
            if word.lower() in _SHORT_WORDS:
                wt *= 0.7
            sw.append(wt)
        tw = sum(sw)
        for j, wt in enumerate(sw):
            pos = idx + j
            word_timings[pos]['offset'] = cur_s
            dur = wt / tw * seg_s if tw > 0 else seg_s / nw
            word_timings[pos]['duration'] = max(0.06, dur)
            cur_s += word_timings[pos]['duration']
        idx += nw
    if word_timings and cur_s > 0:
        sc = total_s / cur_s
        for w in word_timings:
            w['offset'] *= sc
            w['duration'] *= sc
    print(f'  [VAD] Aligned {word_count} words to {len(speech_segs)} speech segments ({len(silent_segs)} pauses)')
class TTSGenerator:

    @staticmethod
    def _generate_kokoro_voiceover(text: str, output_path: Path, settings: dict):
        """Generate voiceover using local Kokoro TTS (offline)
        Returns: (success: bool, word_timings: list)
        """
        try:
            try:
                from kokoro_onnx import Kokoro
            except ImportError:
                print('[ERROR] Kokoro TTS not installed. Install with: pip install kokoro-onnx')
                print('[INFO] Run Setup.bat to install the bundled local voice engine dependencies.')
                return False, ['Kokoro is unavailable. Run Setup.bat; no unsupported voice fallback is used.']
            voice_setting = settings.get('kokoro_voice', 'af_bella')
            if ' - ' in voice_setting:
                voice = voice_setting.split(' - ')[0].strip()
            else:
                voice = voice_setting
            speed = float(settings.get('kokoro_speed', 1.0))
            clean_text = re.sub('[\\U0001F300-\\U0001F9FF\\U0001F600-\\U0001F64F\\U0001F680-\\U0001F6FF\\U00002600-\\U000027BF\\U0001F1E0-\\U0001F1FF]+', '', text)
            clean_text = clean_text.strip()
            if not clean_text:
                print('[WARNING] No text to convert after cleaning')
                return (False, [])
            print(f'[INFO] Generating Kokoro TTS with voice: {voice}')
            kokoro = None
            try:
                import os
                possible_paths = []
                try:
                    import kokoro_onnx
                    pkg_dir = os.path.dirname(kokoro_onnx.__file__)
                    possible_paths.extend([pkg_dir, os.path.join(pkg_dir, 'models')])
                except:
                    pass
                possible_paths.extend([settings.get('kokoro_model_path', ''), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VoiceModules', 'KokoroTTS'), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VoiceModules'), os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kokoro_models'), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models'), os.getcwd(), os.path.join(os.getcwd(), 'kokoro_models'), os.path.join(os.getcwd(), 'models'), os.path.join(os.getcwd(), 'VoiceModules', 'KokoroTTS'), os.path.expanduser('~/.kokoro'), os.path.expanduser('~/kokoro'), os.path.expanduser('~/.cache/kokoro'), os.path.expanduser('~/.local/share/kokoro'), '/usr/share/kokoro', '/usr/local/share/kokoro'])
                print(f'[DEBUG] Searching for Kokoro models in {len(possible_paths)} locations...')
                model_path = None
                voices_path = None
                for base_path in possible_paths:
                    if not base_path or not os.path.exists(base_path):
                        continue
                    for model_name in ['kokoro-v0_19.onnx', 'kokoro-v0_19-half.onnx', 'kokoro.onnx', 'model.onnx']:
                        test_model = os.path.join(base_path, model_name)
                        if os.path.exists(test_model):
                            model_path = test_model
                            print(f'[DEBUG] Found model: {model_path}')
                            break
                    for voices_name in ['voices-multilingual.bin', 'voices-v1.0.bin', 'voices.bin', 'voices-v0_19.bin', 'voices.json']:
                        test_voices = os.path.join(base_path, voices_name)
                        if os.path.exists(test_voices):
                            voices_path = test_voices
                            print(f'[DEBUG] Found voices: {voices_path}')
                            break
                    if model_path and voices_path:
                        break
                    elif model_path or voices_path:
                        model_path = None
                        voices_path = None
                if model_path and voices_path:
                    print(f'[OK] Initializing Kokoro with model: {model_path}')
                    kokoro = Kokoro(model_path, voices_path)
                else:
                    try:
                        kokoro = Kokoro()
                        print('[OK] Kokoro initialized with package defaults')
                    except (TypeError, Exception) as e:
                        searched = [p for p in possible_paths if p and os.path.exists(p)]
                        not_found = [p for p in possible_paths if p and (not os.path.exists(p))]
                        print(f'[ERROR] Kokoro model files not found!')
                        print(f'[ERROR] Searched existing paths: {searched}')
                        print(f'[ERROR] Non-existing paths: {not_found[:5]}')
                        print(f'[ERROR] Please download Kokoro models and place them in one of these locations')
                        print(f"[ERROR] Or set 'kokoro_model_path' in settings to point to the models directory")
                        raise FileNotFoundError(f'Kokoro model files not found')
            except Exception as init_error:
                print(f'[ERROR] Failed to initialize Kokoro: {init_error}')
                print('[INFO] Run Setup.bat to install the bundled local voice engine dependencies.')
                return False, ['Kokoro is unavailable. Run Setup.bat; no unsupported voice fallback is used.']
            _voice_prefix = voice.split('_')[0].lower() if '_' in voice else ''
            _lang_map = {'af': 'en-us', 'am': 'en-us', 'bf': 'en-gb', 'bm': 'en-gb', 'jf': 'ja', 'jm': 'ja', 'zf': 'zh', 'zm': 'zh', 'ef': 'es', 'em': 'es', 'ff': 'fr', 'gf': 'es', 'hf': 'hi', 'hm': 'hi', 'if': 'it', 'im': 'it', 'pf': 'pt', 'pm': 'pt', 'rf': 'ru', 'tf': 'tr'}
            _kokoro_lang = _lang_map.get(_voice_prefix, 'en-us')
            if _kokoro_lang != 'en-us':
                print(f"  [INFO] Kokoro auto-detected language '{_kokoro_lang}' from voice prefix '{_voice_prefix}'")
            _sr = None

            def _kokoro_create_safe(_k, _txt, _v, _sp, _lg):
                """Call kokoro.create with fallback—split in half if IndexError (phoneme OOB)."""
                nonlocal _sr
                try:
                    _p, _sr = _k.create(text=_txt, voice=_v, speed=_sp, lang=_lg)
                    return _p
                except (IndexError, ValueError) as _e:
                    _mid = len(_txt) // 2
                    for _j in range(_mid, min(_mid + 30, len(_txt))):
                        if _txt[_j] in (' ', '\n', ',', '.'):
                            _mid = _j
                            break
                    _a, _b = (_txt[:_mid].strip(), _txt[_mid:].strip())
                    if not _a or not _b:
                        print(f"  [WARN] Kokoro phoneme OOB, can't split further: {_e}")
                        return None
                    print(f'  [INFO] Kokoro phoneme OOB — split chunk ({len(_txt)}→{len(_a)}+{len(_b)})')
                    _pa = _kokoro_create_safe(_k, _a, _v, _sp, _lg)
                    _pb = _kokoro_create_safe(_k, _b, _v, _sp, _lg)
                    if _pa is not None and _pb is not None:
                        import numpy as np
                        return np.concatenate([_pa, _pb])
                    return None
            _max_chunk = 40 if _kokoro_lang in ('ja', 'zh', 'ko') else 100
            if len(clean_text) > _max_chunk:
                _segments = re.split('(?<=[。！？.!?\\n])', clean_text)
                _chunks = []
                _buf = ''
                for _seg in _segments:
                    _seg = _seg.strip()
                    if not _seg:
                        continue
                    if _buf and len(_buf + _seg) > _max_chunk:
                        _chunks.append(_buf)
                        _buf = _seg
                    else:
                        _buf += _seg
                if _buf:
                    _chunks.append(_buf)
            else:
                _chunks = [clean_text]
            _audio_parts = []
            for _ci, _chunk in enumerate(_chunks):
                _chunk = _chunk.strip()
                if not _chunk:
                    continue
                print(f'  [INFO] Kokoro chunk {_ci + 1}/{len(_chunks)} ({len(_chunk)} chars)')
                _part = _kokoro_create_safe(kokoro, _chunk, voice, speed, _kokoro_lang)
                if _part is None:
                    raise RuntimeError(f'Kokoro chunk {_ci} failed after splitting')
                _audio_parts.append(_part)
            if not _audio_parts:
                raise RuntimeError('Kokoro produced no audio output')
            audio = np.concatenate(_audio_parts) if len(_audio_parts) > 1 else _audio_parts[0]
            sample_rate = _sr
            import soundfile as sf
            wav_path = output_path.with_suffix('.wav')
            sf.write(str(wav_path), audio, sample_rate)
            import subprocess
            try:
                subprocess.run(['ffmpeg', '-y', '-i', str(wav_path), '-acodec', 'libmp3lame', '-q:a', '2', str(output_path)], capture_output=True, check=True)
                wav_path.unlink()
            except Exception as e:
                print(f'[WARNING] Could not convert to MP3: {e}')
                output_path = wav_path
            words = clean_text.split()
            word_timings = []
            audio_duration = len(audio) / sample_rate
            for i, word in enumerate(words):
                word_timings.append({'word': word, 'offset': 0.0, 'duration': 0.0})
            refine_word_timings_smart(word_timings, audio_duration, audio_path=output_path)
            print(f'[OK] Generated Kokoro TTS voiceover: {output_path.name}')
            print(f'  {len(word_timings)} words, {audio_duration:.2f}s duration (smart timing)')
            return (True, word_timings)
        except Exception as e:
            print(f'[ERROR] Kokoro TTS generation failed: {e}')
            import traceback
            traceback.print_exc()
            return (False, [])

    @staticmethod
    def _generate_piper_voiceover(text: str, output_path: Path, settings: dict):
        """Generate voiceover using Piper TTS (lightweight ONNX-based TTS)
        Returns: (success: bool, word_timings: list)
        """
        try:
            if _piper_tts is None:
                print('[ERROR] Piper TTS helper not available (piper_tts_helper.py missing)')
                return (False, [])
            voice = settings.get('piper_voice', 'en_US-ryan-medium')
            speed = float(settings.get('piper_speed', 1.0))
            length_scale = 1.0 / speed if speed > 0 else 1.0
            noise_scale = float(settings.get('piper_noise_scale', 0.667))
            sentence_silence = float(settings.get('piper_sentence_silence', 0.2))
            speaker_id = None
            speaker_name = settings.get('piper_speaker', '')
            if speaker_name and _piper_tts:
                speakers = _piper_tts.get_voice_speakers(voice)
                for s in speakers:
                    if s['name'] == speaker_name:
                        speaker_id = s['id']
                        break
            import re
            clean_text = re.sub('[\\U0001F300-\\U0001F9FF\\U0001F600-\\U0001F64F\\U0001F680-\\U0001F6FF\\U00002600-\\U000027BF\\U0001F1E0-\\U0001F1FF]+', '', text)
            clean_text = clean_text.strip()
            if not clean_text:
                print('[WARNING] Piper TTS: No text to convert after cleaning')
                return (False, [])
            emotion_info = f' + style={speaker_name}' if speaker_id is not None else ''
            print(f'[TTS] Piper TTS voiceover (voice={voice}, speed={length_scale:.1f}{emotion_info})')
            print(f'[TTS] Text: {clean_text[:120]}...' if len(clean_text) > 120 else f'[TTS] Text: {clean_text}')
            if _piper_tts and (not _piper_tts.is_voice_available(voice)):
                print(f"[TTS] Piper voice '{voice}' not downloaded yet — auto-downloading...")
                try:
                    ok_dl = _piper_tts.download_voice(voice)
                    if not ok_dl:
                        print(f"[ERROR] Failed to auto-download Piper voice '{voice}'")
                        return (False, [])
                    print(f"[TTS] Downloaded Piper voice '{voice}' successfully")
                except Exception as dl_e:
                    print(f'[ERROR] Piper voice download exception: {dl_e}')
                    return (False, [])
            wav_path = output_path.with_suffix('.wav')
            result = _piper_tts.generate_speech(text=clean_text, output_path=str(wav_path), voice=voice, length_scale=length_scale, noise_scale=noise_scale, sentence_silence=sentence_silence, speaker_id=speaker_id)
            if not result:
                if wav_path.exists() and wav_path.stat().st_size > 0:
                    print(f'[TTS] Piper generate_speech returned False but WAV exists ({wav_path.stat().st_size} bytes) — proceeding anyway')
                else:
                    print(f'[ERROR] Piper TTS generation failed for voice={voice}')
                    return (False, [])
            if output_path.suffix.lower() == '.mp3' and wav_path.exists():
                import subprocess as _sp
                _sp.run(['ffmpeg', '-y', '-i', str(wav_path), '-codec:a', 'libmp3lame', '-qscale:a', '2', str(output_path)], capture_output=True, timeout=30)
                wav_path.unlink(missing_ok=True)
            audio_path = output_path if output_path.exists() else wav_path
            audio_duration = 0
            if audio_path.exists():
                try:
                    if audio_path.suffix.lower() == '.wav':
                        import wave
                        with wave.open(str(audio_path), 'rb') as wf:
                            audio_duration = wf.getnframes() / wf.getframerate()
                    else:
                        import subprocess as _sp
                        _dur = _sp.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)], capture_output=True, text=True, timeout=10)
                        if _dur.returncode == 0 and _dur.stdout.strip():
                            audio_duration = float(_dur.stdout.strip())
                except Exception:
                    pass
            word_timings = []
            if audio_duration > 0:
                words = clean_text.split()
                words_count = len(words)
                if words_count > 0:
                    time_per_word = audio_duration / words_count
                    for i, word in enumerate(words):
                        word_timings.append({'word': word, 'start': i * time_per_word, 'end': (i + 1) * time_per_word})
            print(f'[OK] Piper TTS voiceover: {audio_path.name}')
            print(f'  {len(word_timings)} words, {audio_duration:.2f}s duration')
            return (True, word_timings)
        except Exception as e:
            print(f'[ERROR] Piper TTS generation failed: {e}')
            import traceback
            traceback.print_exc()
            return (False, [])

    @staticmethod
    def _generate_google_cloud_voiceover(text: str, output_path: Path, settings: dict):
        """Generate voiceover using Gemini API TTS (Developer API).
        Returns: (success: bool, word_timings: list)
        """
        try:
            import gemini_api_tts_helper as _gtts
        except ImportError:
            print('[ERROR] gemini_api_tts_helper.py not found')
            return (False, [])
        if not text:
            print('[WARNING] Gemini API TTS: empty text')
            return (False, [])
        wav_path = output_path.with_suffix('.wav')
        success, word_timings = _gtts.generate_speech(text, str(wav_path), {'gemini_api_key': settings.get('gemini_api_key', ''), 'gemini_tts_voice': settings.get('gemini_tts_voice', 'Zephyr'), 'gemini_tts_model': settings.get('gemini_tts_model') or 'gemini-2.5-flash-tts', 'gemini_tts_speed': settings.get('gemini_tts_speed', 1.0), 'gemini_tts_prompt': settings.get('gemini_tts_prompt', ''), 'gemini_tts_language': settings.get('gemini_tts_language', 'en-US'), 'service_account_path': settings.get('service_account_path', ''), 'use_cloud_tts': settings.get('use_cloud_tts', False), 'cloud_tts_voice': settings.get('cloud_tts_voice', settings.get('gemini_tts_voice', 'en-US-Studio-Q'))})
        if not success:
            reason = ''
            if word_timings and isinstance(word_timings[0], str):
                reason = word_timings[0]
            print(f"[ERROR] Gemini API TTS generation failed: {reason or 'unknown reason'}")
            return (False, [reason] if reason else [])
        if output_path.suffix.lower() == '.mp3' and wav_path.exists():
            import subprocess as _sp
            _sp.run(['ffmpeg', '-y', '-i', str(wav_path), '-codec:a', 'libmp3lame', '-qscale:a', '2', str(output_path)], capture_output=True, timeout=30)
            wav_path.unlink(missing_ok=True)
        audio_path = output_path if output_path.exists() else wav_path
        duration_info = ''
        if audio_path.exists():
            import wave as _wave
            try:
                with _wave.open(str(audio_path), 'rb') as wf:
                    d = wf.getnframes() / wf.getframerate()
                    duration_info = f', {d:.1f}s'
            except Exception:
                pass
        print(f'[OK] Gemini API TTS voiceover: {audio_path.name}{duration_info}')
        print(f'  {len(word_timings)} words')
        return (True, word_timings)

def _generate_voiceover(text,output_path,settings=None):
    settings=dict(settings or {})
    engine=settings.get('tts_engine','google_cloud')
    methods={'google_cloud':TTSGenerator._generate_google_cloud_voiceover,'local':TTSGenerator._generate_kokoro_voiceover,'piper':TTSGenerator._generate_piper_voiceover}
    if engine not in methods:raise ValueError('Choose Gemini TTS, Kokoro or Piper')
    output_path=Path(output_path);output_path.parent.mkdir(parents=True,exist_ok=True)
    settings['use_cloud_tts']=False
    settings['kokoro_model_path']=str(Path(__file__).parent/'VoiceModules/KokoroTTS')
    return methods[engine](text,output_path,settings)
TTSGenerator.generate_voiceover=staticmethod(_generate_voiceover)
