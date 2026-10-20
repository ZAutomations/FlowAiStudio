"""Model fallback policy for reference-based Flow Agent images."""
import re

IMAGE_MODELS = ('Nano Banana Pro', 'Nano Banana 2.1', 'Nano Banana 2 Lite')


def preferred(config):
    model = config.get('agent_image_model', IMAGE_MODELS[0])
    if model not in IMAGE_MODELS:
        raise ValueError('Choose Nano Banana Pro, Nano Banana 2.1 or Nano Banana 2 Lite.')
    return model


def batch_instructions(config):
    model=preferred(config)
    if not config.get('agent_image_fallback',True):
        return (f'Use {model} only. If its quota prevents generation, report the model and reason, then stop. '
                'Do not switch models or accounts. '+refusal_instructions())
    exhausted=[m for m in IMAGE_MODELS if m in config.get('exhausted_image_models',[])]
    available=[m for m in IMAGE_MODELS if m not in exhausted]
    if model in exhausted and available:model=available[0]
    order=' → '.join(available)
    skip=(' Already quota-exhausted for this account/project: '+', '.join(exhausted)+'. Skip these models in this and every later batch; do not try them again or reset to Pro.' if exhausted else '')
    return (
        f'Image model fallback order: {order}. Start this batch with {model}, the currently selected model. '+skip+' '
        'Once any model explicitly hits quota, remember it as exhausted for all subsequent batches on this account/project. Never restart the fallback order on a new batch; continue with the next non-exhausted model. '
        'If a model reports an explicit usage/quota limit, automatically continue with the next model in that order '
        'for only the outputs still missing from THIS batch; do not ask which model to use. '
        'Keep the same account, project, attached references, style, aspect ratio and exact AS_SCENE tracking labels. '
        'Check whether each requested output already exists or is generating before requesting it again. '
        'Never regenerate a completed output or duplicate an in-progress request. '
        'Report the actual model used for each output and any model-specific quota error. '
        'If no model remains, stop and report the exhausted models. '
        'A missing attachment, download error or connection problem is not a quota error: report it and stop. '
        + refusal_instructions() + ' Do not switch accounts.'
    )


def refusal_instructions():
    return (
        'If content is refused, stop and propose a materially safer, non-graphic visual for the affected scene. '
        'Preserve the story meaning, historical setting, style and relevant character identities; keep the narration unchanged. '
        'For example, an investigation can show the officer examining the room and taking notes, with a body outside the frame. '
        'Describe what would actually change visually, not merely substitute words or hide restricted details. '
        'Identify the affected scene number and tracking label, explain the proposed alternative, and wait for user review. '
        'Do not automatically submit the alternative, retry the rejected content, or change models to work around a refusal. '
        'Keep all completed outputs.'
    )


def quota_models(text):
    """Require an explicit model quota statement, not an offered alternative."""
    name = r'(Nano Banana (?:Pro|2\.1|2 Lite))'
    patterns = (
        r'(?:reached|exhausted|used up)[^\n]{0,50}?(?:quota|limit)[^\n]{0,60}?' + name,
        r'(?:quota|limit)[^\n]{0,40}?(?:for|of)\s*(?:[🍌 ]*)' + name + r'[^\n]{0,40}?(?:has been|is|was)?\s*(?:reached|exhausted)',
        r'(?:quota|limit)[^\n]{0,90}?' + name + r'[^\n]{0,60}?(?:reached|exhausted|used up)',
        name + r'[^\n]{0,70}?(?:quota|limit)[^\n]{0,50}?(?:reached|exhausted|used up)',
    )
    matches = []
    for pattern in patterns:
        matches.extend((m.start(), m.group(1)) for m in re.finditer(pattern, str(text), re.I))
    values={value.casefold() for _,value in matches}
    return tuple(model for model in IMAGE_MODELS if model.casefold() in values)


def quota_model(text):
    models=quota_models(text)
    return models[-1] if models else None


class ModelQuotaExhausted(RuntimeError):
    """Existing outputs scanned; remaining requests absent and Agent idle."""
    def __init__(self, model, reported_models=()):
        self.model = model
        self.reported_models=tuple(reported_models) or (model,)
        super().__init__(f'Model quota reached: {model}. Existing matching outputs were collected before fallback.')


class ImageModelsExhausted(RuntimeError):
    """Every enabled model exhausted; current batch verified idle and absent."""
    pass
