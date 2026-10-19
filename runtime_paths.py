import os
from pathlib import Path
def configure():
    root=Path(__file__).resolve().parent
    paths=[root/'runtime/ffmpeg',root/'runtime/node']
    os.environ['PATH']=os.pathsep.join(map(str,paths))+os.pathsep+os.environ.get('PATH','')
    os.environ['CHANGEGUI_ROOT']=str(root)
    os.environ['HF_HOME']=str(root/'cache/huggingface')
    os.environ['XDG_CACHE_HOME']=str(root/'cache')
    os.environ['ESPEAK_DATA_PATH']=str(root/'runtime/espeak-ng-data') if (root/'runtime/espeak-ng-data').is_dir() else os.environ.get('ESPEAK_DATA_PATH','')
    os.chdir(root)
