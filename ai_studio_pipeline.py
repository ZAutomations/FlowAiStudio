"""Scene planning, durable projects and a narration-preserving FFmpeg renderer.

This module has no GUI or browser dependencies. Image and TTS adapters supply
assets; the renderer never invents missing assets or silently drops scenes.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
STYLE_PRESETS = {'Colorful stickman · grey background': 'minimalist 2D stickman explainer illustration, light grey and off-white grayscale scenery drawn with fine grey linework, clean bold dark character outlines of consistent thickness, simple round heads, expressive minimal faces, slim stick limbs, bright flat-colored clothing and important props, red blue yellow and green accents reserved for the main characters and story objects, uncluttered composition, consistent character proportions and clothing colors across scenes, no photorealism, no 3D rendering, no embedded text', 'Colorful cartoon · grayscale scenery': '2D hand-drawn cartoon explainer illustration, expressive young adult characters with large readable eyes and consistent head and body proportions, dark clean character outlines, colorful clothing with yellow red blue and green accents, detailed room or street backgrounds rendered exclusively in light grey and off-white with fine grey architectural linework, color reserved for recurring main characters and meaningful props, bright clear visual storytelling, subtle flat cartoon shading, no photorealism, no 3D rendering, no embedded text', 'Cinematic realistic': 'cinematic realistic photography, natural anatomy, soft dramatic lighting, rich detail, cohesive film color grade', 'Documentary': 'documentary photography, authentic environments, natural lighting, realistic people and objects', 'Watercolor': 'hand-painted watercolor illustration, soft paper texture, muted warm colors, delicate brushwork', '3D animation': 'stylized 3D animated film, expressive characters, polished materials, soft cinematic lighting', 'Illustrated story': 'editorial storybook illustration, consistent linework, warm colors, expressive visual storytelling', 'Anime': 'cinematic anime illustration, detailed backgrounds, consistent character design, expressive lighting'}
TRANSITIONS = {'Cut': None}
from ai_studio_story import STYLE_NAME as NARRATION_STYLE, SILENT_DIRECTION
STYLE_PRESETS[NARRATION_STYLE] = STYLE_PRESETS['Colorful cartoon · grayscale scenery'] + '. ' + SILENT_DIRECTION
from ai_studio_story import DOCUMENTARY_STYLE, DOCUMENTARY_DIRECTION
STYLE_PRESETS[DOCUMENTARY_STYLE] = STYLE_PRESETS['Colorful cartoon · grayscale scenery'].replace('expressive young adult characters with large readable eyes and consistent head and body proportions, dark clean character outlines, colorful clothing with yellow red blue and green accents,', 'clear readable object illustrations and explanatory diagrams, dark clean outlines, yellow red blue and green accents on important objects,').replace('color reserved for recurring main characters and meaningful props', 'color reserved for key objects and meaningful details') + '. ' + DOCUMENTARY_DIRECTION
from ai_studio_story import HANDPAINTED_DOCUMENTARY_STYLE, HANDPAINTED_RELATIONSHIP_STYLE
HANDPAINTED_ART = '2D hand-painted storybook illustration on subtly textured off-white watercolor paper, loose confident pencil and dark ink contours with natural uneven hand-drawn linework, soft translucent watercolor washes and colored-pencil detail, gentle warm natural light, expressive readable adult faces with large friendly eyes when people are relevant, consistent proportions, tactile fabric details and tasteful colorful clothing and meaningful props in yellow blue green and red, white and light grey scenery sketched with fine graphite architectural lines and soft grey wash, color reserved for main subjects and meaningful props, delicate paper grain visible through paint, clear topic-specific visual storytelling, no glossy vector finish, no neon glow, no photorealism, no 3D rendering, no embedded text'
STYLE_PRESETS[HANDPAINTED_RELATIONSHIP_STYLE] = HANDPAINTED_ART + '. ' + SILENT_DIRECTION
STYLE_PRESETS[HANDPAINTED_DOCUMENTARY_STYLE] = HANDPAINTED_ART + '. ' + DOCUMENTARY_DIRECTION
from ai_studio_story import PUNJAB_DSP_STYLE, PUNJAB_DSP_DIRECTION
STYLE_PRESETS[PUNJAB_DSP_STYLE] = '2D hand-painted historical Punjabi village crime-memoir illustration on lightly aged ivory paper, fine graphite and ink contours, textured watercolor washes, expressive natural adult faces, consistent character proportions, lived-in cotton fabric and tactile brick, earth and wood details, warm ochre, faded indigo, muted olive, dusty brown and restrained maroon accents, pale grey and ivory environmental linework with gentle warm washes and soft natural light, quiet investigative atmosphere, grounded village compositions, no glossy modern cartoon finish, no neon, no photorealism, no 3D rendering, no embedded text. ' + PUNJAB_DSP_DIRECTION
from ai_studio_story import PUNJAB_DSP_COLORMIX_STYLE
STYLE_PRESETS[PUNJAB_DSP_COLORMIX_STYLE] = '2D hand-painted historical Punjabi village crime-memoir storybook illustration on subtly textured ivory watercolor paper, loose confident graphite and dark ink contours, soft translucent watercolor washes and colored-pencil fabric detail, expressive natural adult faces and consistent character proportions and identities, gentle warm natural light, retain the authentic 1920–1960 Punjab atmosphere but introduce gentle visible color throughout the scene, homes with warm terracotta brick, cream or pale ochre limewashed walls, faded teal or indigo wooden doors, police uniforms in natural khaki and muted olive with dark brown leather belts and boots, men in softly colored cotton kurtas, shalwars, waistcoats and turbans appropriate to the script, women in period-appropriate muted maroon, mustard, dusty rose, indigo or sage clothing and dupattas, tasteful yellow blue green and red accents, natural skin tones, soft green foliage and warm earthen lanes, preserve each recurring person’s clothing colors across scenes and honor supplied reference identities, keep color restrained and harmonious, with off-white breathing space and fine grey architectural detail, do not make the entire environment monochrome, grey or sepia; avoid oversaturation and neon, tactile cotton, wood, earth and brick, delicate paper texture visible through paint, grounded investigative compositions, no glossy modern cartoon finish, no photorealism, no 3D rendering, no embedded text. ' + PUNJAB_DSP_DIRECTION
from ai_studio_story import MODERN_MIXED_STORY_STYLE, MODERN_MIXED_STORY_DIRECTION
STYLE_PRESETS[MODERN_MIXED_STORY_STYLE] = 'contemporary cinematic illustration blending colorful hand-painted watercolor and gouache with hyperrealistic detail, one cohesive painterly-realistic visual language across all scenes, anatomically believable adult characters with realistic facial proportions, natural skin tones and fine facial texture softly integrated with visible brushwork, expressive restrained eyes and authentic body language, rich but balanced jewel-tone and earthy colors, warm amber, deep teal, muted coral, indigo and leafy green accents, fully colored modern interiors and streets, tactile fabric, painted plaster, glass and wood, realistic perspective and material detail, soft cinematic light, natural highlights, subtle depth of field and painterly background edges, delicate canvas or watercolor-paper texture, gentle brush strokes retained on clothing and environments so the result remains an artwork rather than a raw photograph, adapt lighting and mood to the actual scene: warm intimacy, uneasy contrast for betrayal, restrained tension for crime, consistent faces, wardrobe colors and environments across recurring scenes; match approved reference identities, no default grey-only scenery, no antique sepia or aged historical treatment, no exaggerated cartoon eyes, no plastic 3D skin, no glossy game-render appearance, no oversaturated neon, no embedded text. ' + MODERN_MIXED_STORY_DIRECTION

class Cancelled(RuntimeError):
    pass

def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled('Stopped. Completed assets are saved; resume when ready.')

def fingerprint(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()

def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            break
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))

def split_script(text, max_words=22):
    """Split paragraphs at sentences/clauses, retaining every spoken word.

    Explicit visual/caption tags apply to each shot produced from that line.
    SRT numbering/timestamps and Markdown headings are not spoken.
    """
    max_words = max(6, min(80, int(max_words)))
    scenes = []
    for line_no, raw in enumerate((text or '').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#') or '-->' in line:
            continue
        if re.fullmatch('[\\d\\s\\-.]+', line) or re.match('^title\\s*:', line, re.I):
            continue
        visual = re.search('\\[visual:\\s*(.*?)\\]', line, re.I)
        caption = re.search('\\[caption:\\s*(.*?)\\]', line, re.I)
        narration = re.sub('\\[(?:visual|caption|emotion):\\s*.*?\\]', '', line, flags=re.I).strip()
        narration = re.sub('^\\s*(?:CTA)\\s*[:\\-–—]\\s*', '', narration, flags=re.I)
        narration = re.sub('\\s*\\(\\s*\\d+\\s*(?:words?)?\\s*\\)\\s*$', '', narration, flags=re.I)
        if not narration:
            continue
        protected = re.sub('\\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\\.g|i\\.e)\\.', lambda m: m.group().replace('.', '\ue000'), narration, flags=re.I)
        sentences = re.split('(?<=[.!?。！？])\\s+|(?<=[;؛])\\s+', protected)
        for sentence in sentences:
            sentence = sentence.replace('\ue000', '.')
            words = sentence.split()
            while words:
                count = min(max_words, len(words))
                if len(words) > max_words:
                    breaks = [i + 1 for i, word in enumerate(words[:max_words]) if word.endswith((',', ':', '،')) and i + 1 >= max_words // 2]
                    if breaks:
                        count = breaks[-1]
                spoken = ' '.join(words[:count])
                words = words[count:]
                scene = {'id': fingerprint(line_no, len(scenes), spoken)[:16], 'raw': raw, 'source_line': line_no, 'narration': spoken, 'visual_prompt': visual.group(1).strip() if visual else '', 'caption': caption.group(1).strip() if caption else '', 'image_path': '', 'audio_path': '', 'word_timings': []}
                scenes.append(scene)
    return scenes

def image_prompt(scene, style, aspect, continuity=''):
    subject = scene.get('visual_prompt') or 'A concrete visual scene illustrating this narration: ' + scene['narration']
    parts = ['Generate one finished image, not a description or a storyboard.', subject, 'Visual style: ' + style, 'Composition: ' + aspect + ' aspect ratio.']
    if continuity.strip():
        parts.append('Keep these characters and setting consistent: ' + continuity.strip())
        parts.append('Character design lock: preserve the same face and head shape, hair silhouette and color, body proportions, line thickness, and exact clothing colors. Change only pose, expression, camera angle and the requested action; do not redesign the characters.')
    parts.append('One scene in this image. No collage, split screen, captions, logos, watermark, or embedded text.')
    return '\n'.join(parts)

def valid_image(path):
    try:
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError, TypeError):
        return False

def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,width,height', '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Cannot read media: ' + str(path))
    data = json.loads(result.stdout)
    duration = float(data.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError('Media has no positive duration: ' + str(path))
    return (duration, data.get('streams', []))

def valid_audio(path):
    try:
        return bool(path) and any((s.get('codec_type') == 'audio' for s in probe(path)[1]))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return False

def run_ffmpeg(args, cancel=None, cwd=None):
    check_cancel(cancel)
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('FFmpeg and FFprobe must be installed and available on PATH.')
    import tempfile
    with tempfile.TemporaryFile() as log:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        process = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y'] + [str(a) for a in args], stdout=subprocess.DEVNULL, stderr=log, cwd=cwd, creationflags=flags)
        try:
            while process.poll() is None:
                check_cancel(cancel)
                time.sleep(0.1)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        if process.returncode:
            log.seek(0, 2)
            log.seek(max(0, log.tell() - 4000))
            raise RuntimeError('FFmpeg failed: ' + log.read().decode('utf-8', 'replace'))

def build_timeline(scenes, transition='Cut', transition_seconds=0.4, fps=25):
    timeline = []
    cursor = 0.0
    durations = []
    for scene in scenes:
        if not valid_image(scene.get('image_path', '')):
            raise RuntimeError('Missing or invalid image for: ' + scene.get('narration', '')[:70])
        duration, streams = probe(scene.get('audio_path', ''))
        if not any((s.get('codec_type') == 'audio' for s in streams)):
            raise RuntimeError('Voice file has no audio stream.')
        durations.append(duration)
    for i, (scene, duration) in enumerate(zip(scenes, durations)):
        overlap = 0.0
        timeline.append({'index': i, 'start': cursor, 'duration': duration, 'end': cursor + duration, 'tail': overlap})
        cursor += duration
    return timeline

def timed_words(scene, duration):
    """Use TTS word boundaries where available; label estimated timing otherwise."""
    entries = []
    for word in scene.get('word_timings') or []:
        try:
            text = str(word.get('word', word.get('text', ''))).strip()
            start = float(word.get('offset', word.get('start', 0)))
            length = float(word.get('duration', float(word.get('end', start)) - start))
            if text and math.isfinite(start + length) and (length > 0) and (0 <= start < duration):
                entries.append({'word': text, 'start': start, 'end': min(duration, start + length)})
        except (TypeError, ValueError):
            continue
    if entries:
        return (sorted(entries, key=lambda word: word['start']), scene.get('timing_source', 'tts'))
    words = scene.get('narration', '').split()
    weight = sum((max(1, len(word)) for word in words)) or 1
    cursor = 0.0
    for word in words:
        end = cursor + duration * max(1, len(word)) / weight
        entries.append({'word': word, 'start': cursor, 'end': end})
        cursor = end
    return (entries, 'estimated')

def caption_cues(scenes, timeline, words_per_caption=6):
    cues = []
    for scene, shot in zip(scenes, timeline):
        if scene.get('caption'):
            words, origin = timed_words(scene, shot['duration'])
        else:
            words, origin = timed_words(scene, shot['duration'])
        for i in range(0, len(words), words_per_caption):
            chunk = words[i:i + words_per_caption]
            cues.append({'start': shot['start'] + chunk[0]['start'], 'end': shot['start'] + chunk[-1]['end'], 'text': ' '.join((w['word'] for w in chunk)), 'timing': origin, 'words': chunk})
    return cues

def subtitle_time(seconds, ass=False):
    units = 100 if ass else 1000
    ticks = max(0, int(round(seconds * units)))
    hours, remainder = divmod(ticks, 3600 * units)
    minutes, remainder = divmod(remainder, 60 * units)
    seconds, fraction = divmod(remainder, units)
    return f'{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}' if ass else f'{hours:02d}:{minutes:02d}:{seconds:02d},{fraction:03d}'

def write_subtitles(project, scenes, timeline, width, height, settings):
    from ai_studio_tab_render import write_pro_captions
    cues = caption_cues(scenes, timeline, max(1, int(settings.get('caption_words_per_line', 3))))
    srt = '\n\n'.join((f"{i}\n{subtitle_time(c['start'])} --> {subtitle_time(c['end'])}\n{c['text']}" for i, c in enumerate(cues, 1))) + '\n'
    (project / 'captions.srt').write_text(srt, encoding='utf-8')
    write_pro_captions(project / 'captions.ass', scenes, timeline, width, height, settings)
    return cues

def _concat_file(paths, output):
    output.write_text('\n'.join(("file '" + Path(p).name.replace("'", "'\\''") + "'" for p in paths)) + '\n', encoding='utf-8')

def render_video(scenes, project, options, cancel=None, progress=None, log=None):
    """Standalone scene assembly on one continuous narration clock with clean cuts."""
    if options.get('camera_transitions_enabled'):
        from ai_studio_camera_transitions import settings as validate_camera_transitions
        validate_camera_transitions(options)
    project = Path(project).resolve()
    project.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda value: None)
    log = log or (lambda message: None)
    from ai_studio_thumbnails import render_scenes
    scenes = render_scenes(scenes, project, options, cancel)
    width, height = map(int, options.get('resolution', '1920x1080').split('x'))
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError('Resolution must use positive even dimensions.')
    fps = 25
    transition = 'Cut'
    if transition not in TRANSITIONS:
        raise ValueError('Unknown transition: ' + transition)
    timeline = build_timeline(scenes, transition, options.get('transition_seconds', 0.4), fps)
    if not timeline:
        raise ValueError('No scenes to render.')
    total_duration = timeline[-1]['end']
    render_dir = project / 'clips'
    render_dir.mkdir(exist_ok=True)
    segments = []
    voice_files = []
    for scene, shot in zip(scenes, timeline):
        check_cancel(cancel)
        i = shot['index']
        length = shot['duration'] + shot['tail']
        frames = max(2, math.ceil(shot['end'] * fps - 1e-07) - math.ceil(shot['start'] * fps - 1e-07))
        clip = render_dir / f'shot_{i:04d}.mp4'
        voice = render_dir / f'voice_{i:04d}.wav'
        if options.get('motion', True):
            from ai_studio_motion import motion_filter
            vf = motion_filter(width, height, frames, i, options, fps)
            input_args = ['-i', scene['image_path']]
        else:
            vf = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps}'
            input_args = ['-loop', '1', '-i', scene['image_path']]
        run_ffmpeg(input_args + ['-vf', vf, '-frames:v', str(frames), '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-threads', '2', clip], cancel)
        run_ffmpeg(['-i', scene['audio_path'], '-af', f"apad,atrim=duration={shot['duration']:.6f},asetpts=PTS-STARTPTS", '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', voice], cancel)
        voice_files.append(voice)
        segments.append({'path': clip, 'duration': shot['duration'], 'tail': shot['tail']})
        progress(int((i + 1) / len(scenes) * 60))
        log(f"Scene {i + 1}/{len(scenes)} rendered ({shot['duration']:.2f}s voice).")
    level = 0
    while len(segments) > 1:
        joined = []
        for group_index in range(0, len(segments), 4):
            group = segments[group_index:group_index + 4]
            if len(group) == 1:
                joined.append(group[0])
                continue
            out = render_dir / f'join_{level}_{group_index:04d}.mp4'
            listing = render_dir / f'join_{level}_{group_index:04d}.txt'
            _concat_file([s['path'] for s in group], listing)
            run_ffmpeg(['-f', 'concat', '-safe', '0', '-i', listing.name, '-an', '-c:v', 'copy', out], cancel, cwd=render_dir)
            joined.append({'path': out, 'duration': sum((s['duration'] for s in group)), 'tail': group[-1]['tail']})
        segments = joined
        level += 1
    listing = render_dir / 'voice_concat.txt'
    _concat_file(voice_files, listing)
    narration = project / 'narration.wav'
    run_ffmpeg(['-f', 'concat', '-safe', '0', '-i', listing.name, '-c:a', 'pcm_s16le', narration], cancel, cwd=render_dir)
    visual_source = segments[0]['path']
    sfx = None
    settings = dict(options.get('settings', {}))
    from ai_studio_tab_render import captions_enabled
    use_transitions = False
    use_effects = False
    from ai_studio_camera_transitions import apply as apply_camera_transitions
    visual_source, sfx = apply_camera_transitions(visual_source, timeline, options, cancel, log, sfx)
    progress(80)
    settings['_zb_use_text_effects'] = use_effects
    cues = write_subtitles(project, scenes, timeline, width, height, settings)
    generated_thumbnail_duration = sum((shot['duration'] for scene, shot in zip(scenes, timeline) if scene.get('is_thumbnail')))
    narration_duration = total_duration - generated_thumbnail_duration
    thumbnail_duration = max(0.1, min(30, float(settings.get('thumbnail_frame_duration', 3)))) if use_effects and settings.get('add_thumbnail_frame') else 0
    total_duration += thumbnail_duration
    args = ['-i', visual_source, '-i', narration]
    bgm = options.get('bgm_file')
    if bgm:
        if not valid_audio(bgm):
            raise RuntimeError('Selected background music is missing or invalid.')
        args += ['-stream_loop', '-1', '-i', bgm]
        volume = max(0, min(1, float(options.get('bgm_volume', 0.12))))
        graph = f'[1:a]apad=pad_dur={thumbnail_duration},asplit=2[voice][control];[2:a]volume={volume}[music];[music][control]sidechaincompress=threshold=0.03:ratio=6[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]'
    else:
        graph = f'[1:a]apad=pad_dur={thumbnail_duration}[a]'
    if sfx:
        sfx_index = 3 if bgm else 2
        args += ['-i', sfx]
        graph = graph.replace('[a]', '[baseaudio]') + f';[baseaudio][{sfx_index}:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]'
    args += ['-filter_complex', graph, '-map', '0:v', '-map', '[a]']
    want_captions = options.get('captions', True)
    if options.get('use_captions_tab'):
        want_captions = want_captions and captions_enabled(settings)
    if want_captions:
        log('Captions tab: ' + (str(settings.get('clipper_caption_preset', 'bold_white')) + ' / ' + str(settings.get('clipper_caption_animation', 'none')) if settings.get('clipper_captions_enabled') else 'highlight' if settings.get('caption_highlight_enabled') else 'simple'))
        args += ['-vf', 'ass=captions.ass:fontsdir=fonts' if (project / 'fonts').exists() else 'ass=captions.ass', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-threads', '2']
    else:
        args += ['-c:v', 'copy']
    final = project / 'final.mp4'
    temporary = project / 'final.rendering.mp4'
    args += ['-c:a', 'aac', '-b:a', '192k', '-t', f'{total_duration:.6f}', '-movflags', '+faststart', temporary]
    log('Final export: burning captions and mixing audio…' if want_captions else 'Final export: attaching audio without re-encoding images…')
    final_started = time.perf_counter()
    run_ffmpeg(args, cancel, cwd=project)
    log(f'Final export finished in {time.perf_counter() - final_started:.1f}s.')
    duration, streams = probe(temporary)
    if not {'audio', 'video'}.issubset({s.get('codec_type') for s in streams}):
        raise RuntimeError('Rendered file is missing video or narration.')
    if abs(duration - total_duration) > max(0.12, len(scenes) / fps):
        raise RuntimeError(f'Render duration mismatch: voice {total_duration:.3f}s, video {duration:.3f}s')
    os.replace(temporary, final)
    from ai_studio_tab_render import tab_settings_snapshot
    atomic_json(project / 'timeline.json', {'duration': total_duration, 'narration_duration': narration_duration, 'thumbnail_duration': thumbnail_duration, 'generated_thumbnail_duration': generated_thumbnail_duration, 'scenes': timeline, 'captions': cues, 'captions_burned': bool(want_captions), 'transition': transition, 'resolution': [width, height], 'use_transitions_tab': use_transitions, 'use_effects_tab': use_effects, 'render_tab_settings': tab_settings_snapshot(settings)})
    progress(100)
    return final
