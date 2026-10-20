"""Create/use this app's own per-user environment; all engines stay app-local."""
import hashlib,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
key=hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:12]
ENV=Path.home()/'.flow_ai_studio'/'environments'/key
PYTHON=ENV/'Scripts/python.exe'
def main():
    action=sys.argv[1] if len(sys.argv)>1 else 'launch'
    if action=='setup' or not PYTHON.exists():
        ENV.parent.mkdir(parents=True,exist_ok=True)
        if not PYTHON.exists():subprocess.run([str(ROOT/'runtime/python/python.exe'),'-m','venv',str(ENV)],check=True)
        subprocess.run([str(PYTHON),'-m','pip','install','-r',str(ROOT/'requirements.txt')],check=True)
        subprocess.run([str(PYTHON),str(ROOT/'tools/verify_install.py')],check=True,cwd=ROOT)
        if action=='setup':return
    command={'launch':[str(ROOT/'desktop_app.py')],'verify':[str(ROOT/'tools/verify_install.py')],
             'test':['-m','unittest','discover','-s','tests'],'media':[str(ROOT/'tools/smoke_media.py')]}
    if action not in command:raise ValueError('Choose setup, launch, verify, test or media')
    print('Flow AI Studio environment:',ENV,flush=True)
    result=subprocess.run([str(PYTHON),'-X','utf8',*command[action]],cwd=ROOT)
    raise SystemExit(result.returncode)
if __name__=='__main__':main()
