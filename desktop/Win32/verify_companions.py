"""Launch the packaged SDK companions using the shipped runtimes and an isolated user profile."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from verify_host import clean_environment

def run(package, work):
    work.mkdir(parents=True,exist_ok=False)
    root=package/"Studio"
    env=clean_environment(work)
    startup=subprocess.STARTUPINFO()
    startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow=0
    def execute(args, timeout=100):
        return subprocess.run([str(v) for v in args],env=env,cwd=work,timeout=timeout,check=True,
            startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True)
    catalog=json.loads(execute([root/"FxStudio.Agent.exe","--describe"]).stdout)
    assert "debug.snapshot" in json.dumps(catalog)
    generated=work/"profile-results"
    profile_config=work/"profile-request.json"
    profile_config.write_text(json.dumps({"mode":"generate","inputs":[str(root/"examples/prebuilt/counter-c/addin.g1a")],
        "output":str(generated),"language":"zh-CN","deep":False,"includeLoader":True}),encoding="utf-8")
    exe=root/"ProfileStudio/ProfileStudio.exe"
    execute([exe,"--settings-dir",work/"profile-settings","--verify",profile_config])
    generated_result=json.loads((generated/"ui-verification.json").read_text(encoding="utf-8-sig"))
    assert len(generated_result["items"])==1 and not generated_result["operationError"],generated_result
    item=generated_result["items"][0]
    assert item["StatusCode"]=="candidate",item
    export=work/"loader-export"
    profile_config.write_text(json.dumps({"mode":"export-loader","output":str(export)}),encoding="utf-8")
    execute([exe,"--settings-dir",work/"profile-settings","--verify",profile_config])
    bundled=root/"loader-artifacts";names=("FlashLd.g1a",)
    output=export/"FX-Loader"
    assert sorted(p.name for p in output.glob("*.g1a"))==list(names)
    flash=(bundled/names[0]).read_bytes()
    assert json.loads((output/"checksums.json").read_bytes())=={names[0]:hashlib.sha256(flash).hexdigest()}
    assert (Path(item["Output"])/"calculator"/names[0]).read_bytes()==flash
    for name in names:
        assert (export/"FX-Loader"/name).read_bytes()==(bundled/name).read_bytes()
    picture=work/"classic.png"
    execute([root/"FxStudio.exe","--settings-dir",work/"classic-settings","--render-to",picture,"--verify-loader-ui"])
    assert picture.read_bytes().startswith(b"\x89PNG") and not Path(str(picture)+".error.txt").exists()
    result={"classicDesktop":True,"profileStudioBatch":item["StatusCode"],"independentLoaderExport":list(names),"agentDiscovery":True}
    print(json.dumps(result));(work/"validation.json").write_text(json.dumps(result,indent=2),encoding="utf-8")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("package",type=Path);p.add_argument("new_work",type=Path)
    a=p.parse_args();run(a.package.resolve(),a.new_work.resolve())
