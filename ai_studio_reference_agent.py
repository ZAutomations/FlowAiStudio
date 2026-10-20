"""Generate the missing identity library in one Agent image request."""
from pathlib import Path
from ai_studio_pipeline import fingerprint,valid_image


def generate(config,refs,cancel,log):
    from ai_studio_animate_media import generate_agent_media
    records=[];scenes=[]
    for i,ref in enumerate(refs):
        key=fingerprint('reference-agent-v1',ref['name'],ref['kind'],ref['prompt'],'16:9','x1')
        records.append(dict(index=i,kind='image',key=key,token='AS_SCENE_'+key[:20],name=ref['name'],
                            prompt=ref['prompt']+'\nREFERENCE IDENTITY ONLY. Exactly one 16:9 landscape image. No variants, collage, names or embedded text.',
                            output=ref['output']))
        scenes.append({'id':i+1,'narration':'Reference identity: '+ref['name']})
    agent={**config,'image_agent':True,'reference_mode':'none','references':[],
           'scene_reference_map':None,'character_consistency':False,'continuity_ledger_enabled':False,
           'animate_narration_mode':'scene','animation_mode':'partial','animate_count':0,
           'animate_model':config.get('animate_model','Veo 3.1 - Lite'),'aspect':'16:9','resolution':'1920x1080',
           'image_batch_size':max(1,len(records)),
           '_manifest_name':'reference_agent_media.json','agent_image_fallback':True}
    agent.update(scene_start=1,scene_end=None)
    log(f'Reference Agent: one prompt containing all {sum(not valid_image(r["output"]) for r in records)} missing identities; 16:9, x1. Quota fallback Pro → 2.1 → Lite; completed identities retained.')
    generate_agent_media(scenes,agent,cancel,log,
        lambda r:log('Reference saved: '+r['name']+'.png') if not r.get('_reused') else None,
        reference_records=records)
    missing=[r['name'] for r in refs if not valid_image(r['output'])]
    if missing:raise RuntimeError('Reference Agent paused. Saved references retained; retry resumes: '+', '.join(missing))
