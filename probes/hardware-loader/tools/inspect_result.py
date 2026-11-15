"""Summarize evidence, without certifying arbitrary G1A compatibility."""
import json
import sys
from pathlib import Path

def inspect(data):
    lines=data.rstrip(' \r\n').splitlines()
    if not lines or lines[0]!='FXPROBE2':raise ValueError('not a Probe2 result')
    reentry=next((i for i,s in enumerate(lines) if s.startswith('REENTERED_NEW_STARTUP=')),len(lines))
    first=lines[:reentry]
    auto=[s for s in first if s.startswith('AUTO_DONE=')]
    cycles=sum(s.startswith('PASS_CYCLE=') for s in first)
    configured=next((int(s.split('=')[1].split(',')[0],16) for s in first if s.startswith('CONFIG_LOOPS_HOLD=')),0)
    failed=[s for s in lines if s.startswith(('FAIL_','SKIP_'))]
    callback=any(s=='CALLBACK_CLEANED=00000000,00000001' for s in first)
    menu_callback=any(s.startswith('OS_CALLBACK=00000001,') for s in first)
    checks={'automaticCyclesCompleted':bool(auto and auto[-1]==f'AUTO_DONE={configured:08X},00000000' and cycles==configured>0),
            'successfulCycles':cycles,'failuresOrSkips':failed,
            'menuStageReached':any(s.startswith('MENU_READY=00000000,') for s in first),
            'getKeyResumedWithMapping':any(s.startswith('GETKEY_RESUMED=') and s.endswith(',00000000') for s in first),
            'activeMappingOsCallback':menu_callback,
            'activeMappingCallbackGuardPassed':any(s.startswith('CALLBACK_MAP_GUARD=00000000,') for s in first),
            'cleanupRecordedBeforeFirstReentry':callback,
            'mainReturnRecorded': 'EXIT_MAIN_RETURN' in first,
            'newStartupRecorded':reentry<len(lines),'lastRecord':lines[-1],
            'arbitraryAddinCompatibilityProven':False}
    checks['assessment']='requires review' if failed or not callback or not auto else 'recorded path passed; review remaining paths'
    return checks

if __name__=='__main__':
    print(json.dumps(inspect(Path(sys.argv[1]).read_text('ascii')),indent=2,ensure_ascii=False))
