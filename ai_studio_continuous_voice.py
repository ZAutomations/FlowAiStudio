"""Continuous image-video narration with measured, checkpointed scene timing."""
import difflib
import importlib.util
import json
import os
import re
import unicodedata
import wave
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from ai_studio_pipeline import atomic_json, check_cancel, fingerprint, run_ffmpeg, valid_audio
from ai_studio_narration import settings_for


def tokens(text):
    text = unicodedata.normalize('NFKC', text).casefold().replace('ي', 'ی').replace('ك', 'ک')
    return re.findall(r'[^\W_]+', ''.join(c for c in text if unicodedata.category(c) != 'Mn'), re.UNICODE)


def groups(scenes, limit=2400):
    """Keep adjacent narration together; never split a scene or change its text."""
    result = []; current = []; size = 0
    for i, scene in enumerate(scenes):
        length = len(scene['narration']) + 2
        if current and size + length > limit:
            result.append(current); current = []; size = 0
        current.append(i); size += length
    if current: result.append(current)
    return result


def align(scenes, words, duration):
    """Match source narration to recognized words; reject uncertain boundaries."""
    source = []; offsets = [0]
    for scene in scenes:
        source.extend(tokens(scene['narration'])); offsets.append(len(source))
    recognized = []; timing = []
    for word in words:
        start = float(word.get('offset', word.get('start', 0)))
        end = start + float(word.get('duration', float(word.get('end', start)) - start))
        if not 0 <= start < end <= duration + .2: continue
        for token in tokens(word.get('word', word.get('text', ''))):
            recognized.append(token); timing.append((start, min(end, duration)))
    matcher = difflib.SequenceMatcher(None, source, recognized, autojunk=False)
    mapping = {}
    for block in matcher.get_matching_blocks():
        mapping.update((block.a + i, block.b + i) for i in range(block.size))
    if not source or len(mapping) / len(source) < .65:
        raise RuntimeError('Continuous narration alignment is uncertain. Audio is saved. Retry with a larger alignment model; narration and images were not changed.')
    boundaries = [0.0]
    for offset in offsets[1:-1]:
        left = next((mapping[i] for i in range(offset-1, max(-1, offset-7), -1) if i in mapping), None)
        right = next((mapping[i] for i in range(offset, min(len(source), offset+6)) if i in mapping), None)
        if left is None or right is None or right <= left:
            raise RuntimeError('Cannot verify a scene boundary in continuous narration. Saved audio retained; no approximate scene durations used.')
        boundary = (timing[left][1] + timing[right][0]) / 2
        if boundary <= boundaries[-1]: raise RuntimeError('Continuous narration has overlapping scene boundaries; audio retained.')
        boundaries.append(boundary)
    boundaries.append(duration)
    return boundaries


@lru_cache(maxsize=1)
def speech_model(model):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError('Continuous Narration requires faster-whisper. Run Setup.bat to install the alignment dependency.') from exc
    cache=Path.home()/'.flow_ai_studio'/'speech_models'
    os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT','120')
    cache.mkdir(parents=True,exist_ok=True)
    return WhisperModel(model, device='cpu', compute_type='int8',download_root=str(cache))


def transcribe(path, model, cancel, language=None):
    recognizer = speech_model(model)
    segments, _ = recognizer.transcribe(str(path), language=language, word_timestamps=True, beam_size=5, vad_filter=True)
    words = []
    for segment in segments:
        check_cancel(cancel)
        for word in segment.words or []:
            words.append({'word': word.word, 'offset': word.start, 'duration': word.end-word.start})
    return words


def generate(adapter, q, config, tts, recognize=transcribe):
    scenes = adapter.zb_scenes
    if not scenes: raise ValueError('Parse scenes first.')
    if any(scene.get('is_thumbnail') for scene in scenes):
        raise ValueError('Continuous narration accepts story scenes only; thumbnails are added during rendering.')
    if recognize is transcribe and importlib.util.find_spec('faster_whisper') is None:
        raise RuntimeError('Continuous Narration requires faster-whisper. Run Setup.bat before generating narration.')
    root = Path(config['project']) / 'voice' / 'continuous'
    styled, _ = settings_for(config, 0, 1)
    styled = dict(styled, tts_engine=config['voice_engine'], use_tts_voiceover=True)
    keys = {k:v for k,v in styled.items() if k.startswith(('tts_', 'gemini_tts_', 'kokoro_', 'piper_', 'cloud_tts_')) or k == 'use_cloud_tts'}
    identity = fingerprint('continuous-v1', [s['narration'] for s in scenes], config['voice_engine'], keys)
    root = root / identity[:16]; root.mkdir(parents=True, exist_ok=True)
    q.put(('log', 'info', 'Continuous Narration: one voice request at a time; the next chunk synthesizes while the current chunk aligns. Saved audio/timing reused.'))
    chunks = groups(scenes); assignments = []; pieces = []
    def synthesize(number):
        check_cancel(adapter._zb_cancel)
        indices=chunks[number-1]
        audio=root/f'chunk_{number:04d}.mp3'
        text='\n\n'.join(scenes[i]['narration'] for i in indices)
        started=time.monotonic()
        if not valid_audio(audio):
            temporary = audio.with_name(audio.stem+'.generating.mp3')
            attempt = dict(styled)
            ok, _ = tts(text, temporary, attempt)
            if attempt.get('tts_engine') != config['voice_engine']:
                raise RuntimeError('Continuous narration cannot switch voices halfway through. Fix the selected engine and retry; completed chunks retained.')
            if not ok or not valid_audio(temporary): raise RuntimeError(f'Continuous voice chunk {number} failed; saved chunks retained.')
            temporary.replace(audio)
        q.put(('log','info',f'Voice chunk {number}/{len(chunks)} ready in {time.monotonic()-started:.1f}s (saved audio reused when present).'))
        return audio
    pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='continuous-tts')
    future=pool.submit(synthesize,1)
    try:
        for number, indices in enumerate(chunks,1):
            check_cancel(adapter._zb_cancel)
            audio=future.result();pcm=audio.with_suffix('.wav')
            text='\n\n'.join(scenes[i]['narration'] for i in indices)
            future=pool.submit(synthesize,number+1) if number<len(chunks) else None
            if not valid_audio(pcm):
                run_ffmpeg(['-i', str(audio), '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', str(pcm)], adapter._zb_cancel)
            with wave.open(str(pcm), 'rb') as stream:
                rate = stream.getframerate(); frames = stream.getnframes(); duration = frames/rate
            model = config.get('narration_alignment_model', 'small')
            if model not in ('base', 'small', 'medium'): raise ValueError('Choose base, small or medium narration alignment.')
            timing_file = root / f'chunk_{number:04d}_timing_{model}.json'
            if timing_file.exists():
                words = json.loads(timing_file.read_text('utf-8'))['words']
            else:
                q.put(('log', 'info', f'Aligning continuous narration chunk {number}/{len(chunks)} ({duration:.1f}s)…'))
                if recognize is transcribe:
                    # Avoid Urdu/Hindi auto-detection returning a different writing system.
                    language = 'hi' if re.search('[\u0900-\u097f]', text) else 'ur' if re.search('[\u0600-\u06ff]', text) else None
                    words = recognize(pcm, model, adapter._zb_cancel, language=language)
                else:
                    words = recognize(pcm, model, adapter._zb_cancel)
                atomic_json(timing_file, {'words': words})
            boundaries = align([scenes[i] for i in indices], words, duration)
            sample_bounds = [round(t*rate) for t in boundaries]; sample_bounds[-1] = frames
            with wave.open(str(pcm), 'rb') as source:
                for j, index in enumerate(indices):
                    check_cancel(adapter._zb_cancel)
                    start, end = sample_bounds[j:j+2]
                    out = root / f'scene_{index+1:04d}.wav'
                    source.setpos(start)
                    with wave.open(str(out), 'wb') as target:
                        target.setparams(source.getparams()); target.writeframes(source.readframes(end-start))
                    local_words = [{'word':w.get('word',w.get('text','')), 'offset':max(0,float(w.get('offset',w.get('start',0)))-start/rate),
                                    'duration': min(float(w.get('duration',0)), end/rate-float(w.get('offset',w.get('start',0))))}
                                   for w in words if start/rate <= float(w.get('offset',w.get('start',0))) < end/rate]
                    assignments.append((index, str(out), local_words, start/rate, end/rate))
            pieces.append(str(pcm))
            q.put(('log', 'success', f'Continuous narration chunk {number}/{len(chunks)} ready; {len(indices)} image timings verified.'))
    finally:
        if future:future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)
    # The split PCM files reproduce this master without added pauses or re-encoding.
    master = root/'narration.wav'
    with wave.open(str(master), 'wb') as target:
        for path in pieces:
            with wave.open(path, 'rb') as source:
                if target.getnframes() == 0: target.setparams(source.getparams())
                while True:
                    data = source.readframes(48000)
                    if not data: break
                    target.writeframes(data)
    # Publish scene changes only after every boundary has been verified.
    for index, path, words, start, end in assignments:
        scenes[index].update(audio_path=path, audio_key=identity, audio_status='done', voice_engine=config['voice_engine'],
                             word_timings=words, timing_source='continuous-aligned', continuous_voice_key=identity)
    atomic_json(root/'manifest.json', {'identity':identity, 'chunks':pieces, 'scenes':[{'index':i+1,'audio_path':p,'chunk_start':a,'chunk_end':b} for i,p,_,a,b in assignments]})
    adapter._zb_save_project(config)
    q.put(('refresh',)); q.put(('progress',100))
