"""Real-filesystem build helper checks. Runs natively; never starts WSL."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import struct
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('build_project',ROOT/'tooling/build-project.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

def make_g1a(payload):
    data=bytearray(512)+bytearray(payload)
    header=bytearray(32)
    header[:9]=b'USBPower\xf3'
    header[9:14]=bytes([0,16,0,16,0])
    header[14]=(len(data)+0x41)&255
    header[15]=1
    header[16:20]=len(data).to_bytes(4,'big')
    header[20]=(len(data)+0xb8)&255
    checksum=sum(int.from_bytes(data[i:i+2].ljust(2,b'\0'),'big') for i in range(0x300,0x310,2))&65535
    header[22:24]=checksum.to_bytes(2,'big')
    data[:32]=bytes(x^255 for x in header)
    data[0x1f0:0x1f4]=len(data).to_bytes(4,'big')
    return data

def make_elf():
    # Two separated ROM load segments; the second initializes target RAM.
    ident=b'\x7fELF\x01\x02\x01'+b'\0'*9
    header=struct.pack('>16sHHIIIIIHHHHHH',ident,2,42,1,0x300200,52,0,0,52,32,2,40,0,0)
    text=b'\xe0\x01\x00\x09'*4
    data=b'\x01\x23\x45\x67'*2
    first=struct.pack('>IIIIIIII',1,256,0x300200,0x300200,len(text),len(text),5,1)
    second=struct.pack('>IIIIIIII',1,272,0x08100200,0x300220,len(data),len(data),6,1)
    elf=bytearray(header+first+second)
    elf.extend(b'\0'*(256-len(elf)))
    elf.extend(text+data)
    payload=text+b'\0'*16+data
    return elf,make_g1a(payload)

class BuildHelperTests(unittest.TestCase):
    def setUp(self):
        self.scratch=ROOT/'tests/.build-project-tests'
        self.scratch.mkdir(exist_ok=True)
        self.temp=Path(tempfile.mkdtemp(prefix='case-',dir=self.scratch)).resolve()
        self.source=self.temp/'source'
        self.build=self.source/'.fxstudio/Debug'
        self.stage=self.build/'.fxide-source'
        self.source.mkdir()
        self.build.mkdir(parents=True)

    def tearDown(self):
        # Verify the resolved absolute boundary before recursive test cleanup.
        if self.temp==self.scratch.resolve() or not self.temp.is_relative_to(self.scratch.resolve()):
            raise RuntimeError('Unsafe test cleanup path')
        shutil.rmtree(self.temp)

    def sync(self): builder.sync_source(self.source,self.stage,self.build)

    def symlink(self,target,link,directory=False):
        try: link.symlink_to(target,target_is_directory=directory)
        except OSError as error: self.skipTest(f'Host cannot create test symlinks: {error}')

    def test_preserved_mtime_content_is_copied(self):
        source=self.source/'main.c'
        source.write_bytes(b'int main(){return 1;}')
        self.sync()
        stamp=source.stat()
        source.write_bytes(b'int main(){return 2;}')
        os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertEqual(source.stat().st_mtime_ns,(self.stage/'main.c').stat().st_mtime_ns)
        self.sync()
        self.assertEqual((self.stage/'main.c').read_bytes(),source.read_bytes())

    def test_other_profiles_and_build_tree_are_excluded(self):
        other=self.source/'.fxstudio/Release'
        other.mkdir()
        (other/'large-artifact.g1a').write_bytes(b'previous build')
        (self.source/'main.cpp').write_text('int main(){}')
        self.sync()
        self.assertFalse((self.stage/'.fxstudio').exists())
        self.assertTrue((self.stage/'main.cpp').is_file())

    def test_file_directory_changes_and_removed_sources(self):
        source=self.source/'changing'
        source.write_text('file')
        self.sync()
        source.unlink()
        source.mkdir()
        (source/'inner.c').write_text('new source')
        self.sync()
        self.assertEqual((self.stage/'changing/inner.c').read_text(),'new source')
        (source/'inner.c').unlink()
        source.rmdir()
        source.write_text('file again')
        self.sync()
        self.assertEqual((self.stage/'changing').read_text(),'file again')
        source.unlink()
        self.sync()
        self.assertFalse((self.stage/'changing').exists())

    def test_broken_source_link_rejects_old_staged_copy(self):
        source=self.source/'main.c'
        source.write_text('old source')
        self.sync()
        source.unlink()
        self.symlink(self.source/'absent.c',source)
        with self.assertRaisesRegex(RuntimeError,'broken or not a regular file'): self.sync()

    def test_staged_link_does_not_overwrite_external_file(self):
        source=self.source/'main.c'
        source.write_text('new source')
        self.sync()
        (self.stage/'main.c').unlink()
        outside=self.temp/'important.c'
        outside.write_text('preserve me')
        self.symlink(outside,self.stage/'main.c')
        self.sync()
        self.assertEqual(outside.read_text(),'preserve me')
        self.assertFalse((self.stage/'main.c').is_symlink())
        self.assertEqual((self.stage/'main.c').read_text(),'new source')

    def test_unmanaged_staging_rejected(self):
        self.stage.mkdir()
        with self.assertRaisesRegex(RuntimeError,'unmanaged'): self.sync()

    def test_symlink_staging_rejected(self):
        outside=self.temp/'outside-stage'
        outside.mkdir()
        (outside/'.fxide-managed').write_text('marker')
        self.symlink(outside,self.stage,True)
        with self.assertRaisesRegex(RuntimeError,'must not be a symlink'): self.sync()
        self.assertEqual((outside/'.fxide-managed').read_text(),'marker')

    def file_api(self,paths):
        reply=self.build/'.cmake/api/v1/reply'
        reply.mkdir(parents=True,exist_ok=True)
        (reply/'index-1.json').write_text(json.dumps({'reply':{'codemodel-v2':{'jsonFile':'model.json'}}}))
        entries=[]
        for number,path in enumerate(paths):
            name=f'target-{number}.json'
            entries.append({'jsonFile':name})
            (reply/name).write_text(json.dumps({'type':'EXECUTABLE','name':f'target{number}','artifacts':[{'path':str(path)}]}))
        (reply/'model.json').write_text(json.dumps({'configurations':[{'targets':entries}]}))

    def test_external_artifact_rejected_before_unlink(self):
        outside=self.temp/'important.elf'
        outside.write_bytes(b'\x7fELFpreserve')
        self.file_api([outside])
        with self.assertRaisesRegex(RuntimeError,'must remain inside'): builder.select_target(self.build,None,False)
        self.assertEqual(outside.read_bytes(),b'\x7fELFpreserve')

    def test_symlink_artifact_rejected_before_unlink(self):
        outside=self.temp/'important.elf'
        outside.write_bytes(b'\x7fELFpreserve')
        link=self.build/'link.elf'
        self.symlink(outside,link)
        self.file_api([link])
        with self.assertRaisesRegex(RuntimeError,'must remain inside'): builder.select_target(self.build,None,False)
        self.assertTrue(outside.is_file())

    def test_target_selection_and_first_build_nonexistent_output(self):
        self.file_api(['first.elf','second.elf'])
        with self.assertRaisesRegex(RuntimeError,'Expected one executable'): builder.select_target(self.build,None,False)
        name,path=builder.select_target(self.build,'target1',False)
        self.assertEqual(name,'target1')
        self.assertEqual(path,self.build/'second.elf')
        self.assertFalse(path.exists())

    def verify(self,elf,g1a):
        ep=self.temp/'input.elf';gp=self.temp/'input.g1a'
        ep.write_bytes(elf);gp.write_bytes(g1a)
        return builder.verify_artifact_pair(ep,gp)

    def test_matching_elf_with_zero_alignment_gap(self):
        elf,g1a=make_elf()
        report=self.verify(elf,g1a)
        self.assertTrue(report['verified'])
        self.assertEqual(report['payloadBytes'],40)
        self.assertEqual(report['comparedBytes'],24)

    def test_mismatches_and_malformed_artifacts_rejected(self):
        original_elf,original_g1a=make_elf()
        mutations=[('ELF truncated','elf',0,b''),('ELF endian','elf',5,b'\x01'),
                   ('ELF wrong CPU','elf',18,b'\x00\xb7'),('ELF wrong entry','elf',24,b'\x00\x30\x02\x02'),
                   ('ELF program table','elf',28,b'\xff\xff\xff\xf0'),
                   ('ELF oversized segment','elf',52+16,b'\xff\xff\xff\xff'),
                   ('ELF overlap','elf',52+32+12,b'\x00\x30\x02\x00'),
                   ('ELF invalid alignment','elf',52+28,b'\x00\x00\x00\x03'),
                   ('G1A magic','g1a',0,b'\x00'),('G1A control','g1a',14,b'\x00'),
                   ('G1A checksum','g1a',22,b'\x00'),('G1A payload','g1a',512,b'\x00'),
                   ('G1A gap data','g1a',512+20,b'\x55')]
        for label,which,offset,value in mutations:
            with self.subTest(label=label):
                elf=bytearray(original_elf);g1a=bytearray(original_g1a)
                target=elf if which=='elf' else g1a
                if label=='ELF truncated': elf=elf[:20]
                else: target[offset:offset+len(value)]=value
                with self.assertRaises(RuntimeError): self.verify(elf,g1a)
        with self.assertRaisesRegex(RuntimeError,'extent'):
            self.verify(original_elf,make_g1a(original_g1a[512:]+b'\0'))

    def test_real_cas01_pair_and_cas02_mismatch(self):
        fixtures=ROOT/'probes/emulator/build'
        if not (fixtures/'cas-audit.elf').exists(): self.skipTest('Historical local fixture not present')
        report=builder.verify_artifact_pair(fixtures/'cas-audit.elf',fixtures/'cas01.g1a')
        self.assertEqual(report['comparedBytes'],105288)
        with self.assertRaises(RuntimeError):
            builder.verify_artifact_pair(fixtures/'cas-audit.elf',fixtures/'cas02.g1a')

if __name__=='__main__': unittest.main(verbosity=2)
