"""Native subset needed by fxSDK CMake modules; building is handled by CMake."""
from pathlib import Path
import sys
prefix=Path(__file__).resolve().parent.parent
paths={'sysroot':prefix,'include':prefix/'sh3eb-elf/include','lib':prefix/'sh3eb-elf/lib'}
if len(sys.argv)==3 and sys.argv[1]=='path' and sys.argv[2] in paths:
    print(paths[sys.argv[2]].as_posix())
elif sys.argv[1:] in (['--version'],['version']):
    print('fxSDK 2.11.0 (FX Studio native Windows host tools)')
else:
    sys.exit('Native fxsdk supports path sysroot|include|lib and --version. Build with CMake or FX Studio.')
