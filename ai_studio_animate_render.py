"""Separate mixed-media renderer for Animate; the Studio renderer is unchanged."""
import math
import os
import time
from pathlib import Path
from ai_studio_animate_options import animation_count
from ai_studio_pipeline import TRANSITIONS, build_timeline, check_cancel, run_ffmpeg, _concat_file, valid_audio, write_subtitles, probe, atomic_json

def render_animated_video(scenes, project, options, cancel=None, progress=None, log=None):
    """Standalone scene assembly on one continuous narration clock with clean cuts."""
    project = Path(project).resolve()
    project.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda value: None)
    log = log or (lambda message: None)
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
    animated = animation_count(options, len(scenes))
    for scene, shot in zip(scenes, timeline):
        check_cancel(cancel)
        i = shot['index']
        length = shot['duration'] + shot['tail']
        frames = max(2, math.ceil(shot['end'] * fps - 1e-07) - math.ceil(shot['start'] * fps - 1e-07))
        clip = render_dir / f'shot_{i:04d}.mp4'
        voice = render_dir / f'voice_{i:04d}.wav'
        if i < animated:
            from ai_studio_animate_media import valid_video
            video = scene.get('video_path', '')
            if not valid_video(video):
                raise RuntimeError(f'Scene {i + 1} needs its matched animated clip before rendering.')
            vf = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={length:.6f}'
            input_args = ['-i', video]
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
    progress(80)
    settings['_zb_use_text_effects'] = use_effects
    cues = write_subtitles(project, scenes, timeline, width, height, settings)
    narration_duration = total_duration
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
    atomic_json(project / 'timeline.json', {'duration': total_duration, 'narration_duration': narration_duration, 'thumbnail_duration': thumbnail_duration, 'scenes': timeline, 'captions': cues, 'captions_burned': bool(want_captions), 'transition': transition, 'resolution': [width, height], 'use_transitions_tab': use_transitions, 'use_effects_tab': use_effects, 'render_tab_settings': tab_settings_snapshot(settings), 'animation_mode': options.get('animation_mode', 'partial'), 'animated_scenes': animated, 'animate_model': options.get('animate_model', 'Omni 1.1 Flash')})
    progress(100)
    return final
