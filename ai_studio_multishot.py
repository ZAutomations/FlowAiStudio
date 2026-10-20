"""Explicit edit instructions added at submission, without changing media identities."""
import math

RULES = """MANDATORY MULTI-SHOT EDIT: Each eight-second VIDEO must contain at least TWO distinct sequential shots, preferably THREE, with visible HARD CUTS at the specified times. A continuous camera pan, zoom, orbit, reframing or pose change does NOT count as a new shot. Render one edited video asset per clip, never separate outputs per shot, split-screen, collage or storyboard. Each shot must depict its assigned narration beat; never invent unrelated events to fill time. Keep the same identities, wardrobe, props/holders, injuries, emotional progression, location geography, lighting and screen direction across cuts. Keep characters silent; local narration is added later. No generated audio or on-screen text."""

def shot_instructions(record,seconds=8):
    shots=record.get('shots') or []
    valid=isinstance(shots,list) and 2<=len(shots)<=4
    cursor=0
    if valid:
        for shot in shots:
            try:
                start=float(shot['start']);end=float(shot['end'])
                if not math.isfinite(start+end) or abs(start-cursor)>.02 or not start<end<=seconds or not str(shot.get('visual_prompt','')).strip():valid=False;break
                cursor=end
            except (KeyError,TypeError,ValueError):valid=False;break
        valid=valid and abs(cursor-seconds)<.02
    if not valid:
        # Local composition plan only; the supplied visual/narration remains authoritative.
        a=round(seconds*.375,3);b=round(seconds*.75,3)
        shots=[dict(start=0,end=a,visual_prompt='Wide or medium establishing view of the exact narrated action and its required setting from the scene prompt.'),
               dict(start=a,end=b,visual_prompt='A distinct closer angle of the same relevant subject, action or meaningful prop as the narration progresses. Preserve established geography and facts.'),
               dict(start=b,end=seconds,visual_prompt='A distinct reaction or detail angle concluding that same narrated beat. Show only subjects/events supported by this scene; no new story facts.')]
    lines=[RULES,'EDIT DECISION LIST FOR THIS OUTPUT (local clip time):']
    for i,shot in enumerate(shots):
        cut='OPENING SHOT' if i==0 else 'HARD CUT - visibly different shot size or camera angle, same story continuity'
        lines.append(f'SHOT {i+1} [{float(shot["start"]):g}-{float(shot["end"]):g}s] {cut}: {shot["visual_prompt"]}')
    lines.append('Before generating, check that the video request contains every timed shot and cut above. Do not simplify this into one continuous shot. If the selected model cannot follow the edit, report that limitation; do not claim a single-shot result satisfies the request.')
    return '\n'.join(lines)
