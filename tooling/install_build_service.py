"""Install only our service scripts into the dedicated SDK distribution."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
DISTRO='FxSDK-Dev-20261114'

def run(*args,**kw):
    return subprocess.run(['wsl.exe','-d',DISTRO,'--exec',*map(str,args)],check=True,**kw)

def main():
    run('mkdir','-p','/opt/fxide/bin')
    for name in ('build-project','compiler-launcher','cancel-build'):
        source=ROOT/'tooling'/(name+'.py')
        linux=run('wslpath','-u',source,capture_output=True,encoding='utf-8').stdout.strip()
        run('install','-m','755',linux,'/opt/fxide/bin/'+name)
    # Disable inherited Windows PATH for predictable tools and clean logs.
    config=Path(r'\\wsl.localhost\FxSDK-Dev-20261114\etc\wsl.conf')
    config.write_text('[interop]\nappendWindowsPath=false\n[user]\ndefault=root\n',encoding='utf-8')

if __name__=='__main__': main()
