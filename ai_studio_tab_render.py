"""Standalone Pro Captions (ASS) adapter; no editor transitions or effects."""
import shutil
from pathlib import Path
TRANSITION_KEYS=()
def has_frame_effects(settings):return False
def captions_enabled(settings):return bool(settings.get('clipper_captions_enabled',True))
def tab_settings_snapshot(settings):
 return {k:v for k,v in settings.items() if k.startswith(('caption_','clipper_')) and not k.startswith('caption_highlight')}
def write_pro_captions(path, scenes, timeline, width, height, settings):
    """Use the same Pro Captions preset/animation engine with Studio word timings."""
    from ai_studio_pipeline import timed_words
    from clipper_captions import build_ass_from_settings, get_preset, DEFAULT_PRESET
    import caption_fonts
    words = []
    offset = float(settings.get('caption_sync_offset', 0) or 0)
    total = timeline[-1]['end']
    for scene, shot in zip(scenes, timeline):
        timed, _ = timed_words(scene, shot['duration'])
        for word in timed:
            start = max(0, shot['start'] + word['start'] + offset)
            end = min(total, shot['start'] + word['end'] + offset)
            if end > start:
                words.append({'word': word['word'], 'start': start, 'end': end})
    preset_id = settings.get('clipper_caption_preset', DEFAULT_PRESET)
    preset = get_preset(preset_id)
    overrides = {'position': settings.get('caption_position', preset.get('position', 'bottom')), 'max_words': max(1, int(settings.get('caption_words_per_line', 3))), 'max_lines': 1 if settings.get('caption_layout') == '1-line' else 2}
    if settings.get('caption_font_size'):
        overrides['font_scale'] = float(settings['caption_font_size']) / preset.get('font_size', 90)
    for key, target in [('highlight_color', 'highlight_color'), ('primary_color', 'primary_color'), ('stroke_color', 'outline_color'), ('font_family', 'font_family'), ('stroke', 'outline'), ('bold', 'bold')]:
        value = settings.get('clipper_override_' + key)
        if value:
            overrides[target] = value
    if settings.get('clipper_override_bg_enabled'):
        overrides.update(background_enabled=True, background_color=settings.get('clipper_override_bg_color') or '#000000', background_opacity=settings.get('clipper_override_bg_opacity', 80))
    yoff = float(settings.get('caption_y_offset', 0) or 0)
    if yoff:
        overrides.update(pos_x=50, pos_y={'top': 10, 'center': 50, 'bottom': 78}.get(overrides['position'], 78) + yoff / height * 100)
    build_ass_from_settings(words, preset_id, width, height, path, overrides=overrides, animation=settings.get('clipper_caption_animation', 'none'))
    family = overrides.get('font_family', preset.get('font_family', 'Roboto'))
    font_file = caption_fonts.resolve_font_path(family)
    if font_file and Path(font_file).is_file():
        fonts = path.parent / 'fonts'
        fonts.mkdir(exist_ok=True)
        shutil.copy2(font_file, fonts / Path(font_file).name)
