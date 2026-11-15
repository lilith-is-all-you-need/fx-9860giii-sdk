import hashlib,json,struct,sys
from pathlib import Path
def fnv(b):
 h=2166136261
 for x in b:h=((h^x)*16777619)&0xffffffff
 return h
def make(folder):
 data=bytearray()
 for page in range(512):
  block=bytearray(((page*37+i*13+(i>>8))&255) for i in range(4096))
  block[:8]=b'FXPAGE03';struct.pack_into('>I',block,8,page)
  # mov.l @(pc+4+4),r0; rts; nop; padding; literal. Return page identity.
  block[32:44]=bytes.fromhex('d001000b00090000')+struct.pack('>I',0x50670000|page)
  data+=block
 data=data[:2094444];h=fnv(data);folder.mkdir(parents=True,exist_ok=True)
 (folder/'Probe3.bin').write_bytes(data)
 for size in [4095,4096,4097]:
  edge=bytearray((i*7+size)&255 for i in range(size));edge[:8]=b'FXP3EDGE'
  (folder/f'P3e{size}.bin').write_bytes(edge)
 (folder/'Probe3.cfg').write_text(f'FXPROBE3\nbytes={len(data)}\nfnv={h:08X}\nloops=2\nhold_ms=240\n',encoding='ascii',newline='\n')
 (folder/'probe3-input.json').write_text(json.dumps({'bytes':len(data),'pages':512,'fnv':f'{h:08X}','sha256':hashlib.sha256(data).hexdigest(),'kind':'authored deterministic file; not a third-party G1A','entry_offset_per_page':32},indent=2),encoding='utf8')
if __name__=='__main__':make(Path(sys.argv[1]))
