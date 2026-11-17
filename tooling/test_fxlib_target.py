"""Real legacy import/resource/build/key/file/timer integration through the Agent.

Requires a complete updated SDK package. All projects, guest files and sessions
are isolated under a new output directory. No physical hardware is exercised.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''#include <fxlib.h>
#include <gint/display.h>
#include <project_assets.h>
#include <string.h>
volatile int validation_bits, timer_one, timer_two, key_result, key_count;
static void tick_one(void) { timer_one++; }
static void tick_two(void) { timer_two++; }
__attribute__((noinline)) void compat_ready(void) { __asm__ volatile("" ::: "memory"); }
int AddIn_main(int isAppli, unsigned short OptionNum)
{
    (void)isAppli; (void)OptionNum;
    Bdisp_AllClr_DDVRAM();
    Bdisp_SetPoint_VRAM(2,2,1);
    if(Bdisp_GetPoint_VRAM(2,2)==1) validation_bits|=1;
    DISPGRAPH graph={0}; graph.x=4; graph.y=4;
    graph.GraphData.width=sprite_width; graph.GraphData.height=sprite_height;
    graph.GraphData.pBitmap=sprite; graph.WriteModify=1; graph.WriteKind=1;
    Bdisp_WriteGraph_VRAM(&graph);
    if(Bdisp_GetPoint_VRAM(4,4)==1 && Bdisp_GetPoint_VRAM(12,5)==1) validation_bits|=2;
    SetTimer(1,10,tick_one); SetTimer(2,20,tick_two); Sleep(80);
    KillTimer(1); KillTimer(2);
    if(timer_one>0 && timer_two>0) validation_bits|=4;
    FONTCHARACTER path[32]={0}; unsigned char data[3]={0};
    Bfile_StrToName_ncpy(path,(const unsigned char*)"\\\\fls0\\FXTEST.bin",32);
    Bfile_DeleteFile(path); fxlib_compat_clear_error();
    int made=Bfile_CreateFile(path,3), handle=Bfile_OpenFile(path,_OPENMODE_READWRITE);
    if(made>=0 && handle>=0) {
        int written=Bfile_WriteFile(handle,blob,3);
        int size=Bfile_GetFileSize(handle);
        int read=Bfile_ReadFile(handle,data,3,0);
        if(written==3 && size==3 && read==3 && !memcmp(data,blob,3)) validation_bits|=8;
        Bfile_CloseFile(handle); Bfile_DeleteFile(path);
    }
    if(blob_size==3 && blob[1]==0x42 && sprite_width==9 && sprite_stride==2) validation_bits|=16;
    PrintXY(1,16,(const unsigned char*)"FXLIB CHECK",0);
    dimage(100,1,&native_sprite);
    font_t const *previous=dfont(&digits); dtext(1,30,C_BLACK,"0123456789"); dfont(previous);
    Bdisp_PutDisp_DD(); compat_ready();
    while(1) { unsigned int key=0; GetKey(&key); key_result=(int)key;
        if(key==KEY_CTRL_EXE) { key_count++; PrintXY(1,44,(const unsigned char*)"EXE OK",0); Bdisp_PutDisp_DD(); }
        if(key==KEY_CTRL_EXIT) return 1;
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package, output = args.package.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    python = package / 'sdk/native/host/python/python.exe'
    helper = ROOT / 'skills/fxstudio/scripts/fxstudio.py'
    state, project = output / 'state', output / '迁移工程'
    original = output / '原工程'; original.mkdir()
    (original / 'main.c').write_text(SOURCE, encoding='utf-8')
    original_hash = hashlib.sha256((original / 'main.c').read_bytes()).hexdigest()
    from PIL import Image
    Image.new('RGBA', (9, 2), (0, 0, 0, 255)).save(output / 'sprite.png')
    # Reuse the public, already reviewed numeric glyph sheet.
    font = ROOT / 'probes/emulator/graphics-audit/assets/digits.png'
    (output / 'blob.bin').write_bytes(b'\x13\x42\xa9')

    def process(command):
        done = subprocess.run(list(map(str, command)), capture_output=True, text=True,
                              encoding='utf-8', timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode:
            raise RuntimeError(done.stdout + done.stderr)
        return json.loads(done.stdout)

    migration = process([python, package / 'tooling/legacy_project.py', 'create', '--source', original, '--output', project, '--name', 'CompatCheck'])
    for kind, file, symbol, extra in (
        ('bitmap', output / 'sprite.png', 'sprite', []),
        ('image', output / 'sprite.png', 'native_sprite', []),
        ('binary', output / 'blob.bin', 'blob', []),
        ('font', font, 'digits', ['--font-grid', '3x5', '--font-charset', 'numeric']),
    ):
        process([python, package / 'tooling/project_assets.py', 'import', '--project', project,
                 '--input', file, '--kind', kind, '--symbol', symbol, *extra])

    def cli(*arguments):
        return process([python, helper, '--package', package, '--state', state, *arguments])

    def call(command, arguments, timeout=240):
        file = output / 'arguments.json'; file.write_text(json.dumps(arguments), encoding='utf-8')
        reply = cli('call', command, '--args-file', file)
        operation = reply['structuredContent']['operation']
        deadline = time.monotonic() + timeout
        while operation['status'] in ('queued', 'running'):
            if time.monotonic() >= deadline:
                cli('operation', operation['operationId'], '--cancel')
                raise TimeoutError(command)
            time.sleep(.1)
            operation = cli('operation', operation['operationId'])['structuredContent']['operation']
        if operation['status'] != 'succeeded':
            raise RuntimeError(json.dumps(operation))
        return operation

    session = None
    try:
        cli('doctor'); cli('start')
        catalog = cli('discover')['structuredContent']
        names = {x['name'] for x in catalog['commands']}
        if not {'session.open', 'build.run', 'debug.launch', 'debug.snapshot', 'debug.key', 'debug.pause', 'debug.resume'} <= names:
            raise RuntimeError('Required commands absent from the actual Agent catalog')
        session = call('session.open', {'projectPath': str(project)})['result']['sessionId']
        print('Building migrated source and four resource formats (Debug)', flush=True)
        debug = call('build.run', {'sessionId': session, 'configuration': 'Debug'})['result']['artifact']
        call('debug.launch', {'sessionId': session, 'stopAt': 'compat_ready'})
        expressions = ['validation_bits', 'timer_one', 'timer_two', 'key_result', 'key_count']

        def snapshot(label):
            op = call('debug.snapshot', {'sessionId': session, 'include': ['screen'], 'expressions': expressions})
            values = [int(x['value']) for x in op['result']['expressions']]
            cli('operation', op['operationId'], '--screen', output / (label + '.png'))
            print(label + ': ' + repr(values), flush=True)
            return values

        before = snapshot('startup')
        if before[0] != 31 or min(before[1:3]) <= 0:
            raise AssertionError('Actual target drawing/timer/file/resource checks failed: ' + repr(before))
        call('debug.resume', {'sessionId': session})
        call('debug.key', {'sessionId': session, 'key': 'EXE', 'action': 'press'})
        call('debug.pause', {'sessionId': session})
        after = snapshot('after-key')
        if after[3:] != [30004, 1]:
            raise AssertionError('Legacy key mapping or screen update failed: ' + repr(after))
        call('debug.stop', {'sessionId': session})
        print('Building migrated source and four resource formats (Release)', flush=True)
        release = call('build.run', {'sessionId': session, 'configuration': 'Release'})['result']['artifact']
        if hashlib.sha256((original / 'main.c').read_bytes()).hexdigest() != original_hash:
            raise AssertionError('Original source changed')
        record = {'passed': True, 'hardwareTested': False, 'migration': migration, 'debug': debug,
                  'release': release, 'before': before, 'after': after, 'originalSha256': original_hash,
                  'emulatorSha256': hashlib.sha256((package / 'runtime/emulator/FxEmulator.exe').read_bytes()).hexdigest(),
                  'scope': 'Actual SuperH drawing, two cooperative timers, file roundtrip, four resources, old EXE code; no physical OS lifecycle claim'}
    finally:
        if (state / 'bridge.json').exists():
            try:
                if session:
                    call('session.close', {'sessionId': session}, timeout=30)
            finally:
                try:
                    cli('stop')
                except RuntimeError as error:
                    # A lost stop response may be retried after shutdown began.
                    # Verify descriptor removal instead of treating it as a pass.
                    if 'Host is stopping.' not in str(error):
                        raise
                    deadline = time.monotonic() + 40
                    while (state / 'bridge.json').exists() and time.monotonic() < deadline:
                        time.sleep(.1)
                    if (state / 'bridge.json').exists():
                        raise
    record['ownedHostStopped'] = not (state / 'bridge.json').exists()
    (output / 'validation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'report': str(output / 'validation.json'), 'hardwareTested': False}), flush=True)


if __name__ == '__main__':
    main()
