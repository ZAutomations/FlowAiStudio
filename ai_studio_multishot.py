"""Explicit edit instructions added at submission, without changing media identities."""
import math

RULES = """MANDATORY MULTI-SHOT EDIT: Each eight-second VIDEO must contain TWO distinct sequential shots by default; use THREE only when the narration genuinely requires a third visual beat, never four or more, with visible HARD CUTS at the specified times. A continuous camera pan, zoom, orbit, reframing or pose change does NOT count as a new shot. Render one edited video asset per clip, never separate outputs per shot, split-screen, collage or storyboard. Each shot must depict its assigned narration beat; never invent unrelated events to fill time. Keep the same identities, wardrobe, props/holders, injuries, emotional progression, location geography, lighting and screen direction across cuts. Keep characters silent; local narration is added later. No generated audio or on-screen text."""

def shot_instructions(record,seconds=8):
    shots=record.get('shots') or []
    if isinstance(shots,list) and len(shots)==4:
        # Legacy plans retain their media identity; combine their actions locally.
        shots=[dict(start=group[0]['start'],end=group[-1]['end'],visual_prompt=' '.join(str(s.get('visual_prompt','')) for s in group)) for group in (shots[:2],shots[2:])]
    valid=isinstance(shots,list) and 2<=len(shots)<=3
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
        middle=round(seconds/2,3)
        shots=[dict(start=0,end=middle,visual_prompt='Wide or medium establishing view of the exact narrated action and its required setting from the scene prompt.'),
               dict(start=middle,end=seconds,visual_prompt='HARD CUT to a distinct closer angle or relevant reaction concluding the same narrated beat. Preserve established geography, characters, props and facts; no unrelated event.')]
    lines=[RULES,'The following current edit decision list overrides any older shot-count/timing instructions in this request.','EDIT DECISION LIST FOR THIS OUTPUT (local clip time):']
    for i,shot in enumerate(shots):
        cut='OPENING SHOT' if i==0 else 'HARD CUT - visibly different shot size or camera angle, same story continuity'
        lines.append(f'SHOT {i+1} [{float(shot["start"]):g}-{float(shot["end"]):g}s] {cut}: {shot["visual_prompt"]}')
    lines.append('Before generating, check that the video request contains every timed shot and cut above. Do not simplify this into one continuous shot. If the selected model cannot follow the edit, report that limitation; do not claim a single-shot result satisfies the request.')
    return '\n'.join(lines)
