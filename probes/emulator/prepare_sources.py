"""Generate audited debugger hook copies. The upstream checkout stays unchanged."""
from pathlib import Path
import difflib
root = Path(__file__).resolve().parents[2]
up = root / 'third_party/emuCasioCalc/src/engine'
out = root / 'probes/emulator/build/patched'
out.mkdir(parents=True, exist_ok=True)

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'upstream hook location changed: {old[:90]!r}')
    return text.replace(old, new)

cpu = original_cpu = (up / 'cpu.c').read_text()
cpu = '#include "debug_bridge.h"\n' + cpu
cpu = replace_once(cpu, '    exec(cpu, pc + 2);', '''    cpu->pc = pc + 2;
    probe_debug_before(cpu, pc + 2);
    exec(cpu, pc + 2);''')
cpu = replace_once(cpu, '    uint16_t op = mem_read16(mem, pc);', '''    probe_debug_ignore_memory = true;
    uint16_t op = mem_read16(mem, pc);
    probe_debug_ignore_memory = false;''')
cpu = replace_once(cpu, 'static inline void step_one(Cpu *cpu)\n{', '''static inline void step_one(Cpu *cpu)
{
    probe_debug_before(cpu, cpu->pc);''')
cpu = replace_once(cpu, '        cpu->attention = false;', '''        probe_debug_poll(cpu);
        cpu->attention = false;''')
(out / 'cpu.c').write_text(cpu)

mem = original_mem = (up / 'mem.h').read_text()
mem = replace_once(mem, '#include <stdint.h>', '''#include <stdint.h>
/* Hook covers interpreted data accesses; debugger reads use raw pages. */
extern void probe_debug_memory(uint32_t address, int size, bool write);''')
for bits in (8,16,32):
    read = f'static inline uint{bits}_t mem_read{bits}(Memory *mem, uint32_t addr)\n{{'
    write = f'static inline void mem_write{bits}(Memory *mem, uint32_t addr, uint{bits}_t value)\n{{'
    mem = replace_once(mem, read, read + f'\n    probe_debug_memory(addr, {bits//8}, false);')
    mem = replace_once(mem, write, write + f'\n    probe_debug_memory(addr, {bits//8}, true);')
(out / 'mem.h').write_text(mem)
# Quoted includes resolve next to source. Copy all engine sources/headers and
# overwrite just the two patched files, avoiding an inconsistent mem.h copy.
for p in up.glob('*'):
    if p.suffix in ('.c', '.h') and p.name not in ('cpu.c', 'mem.h'):
        (out / p.name).write_bytes(p.read_bytes())
diff = ''.join(difflib.unified_diff(original_cpu.splitlines(True), cpu.splitlines(True), fromfile='upstream/cpu.c', tofile='patched/cpu.c'))
diff += ''.join(difflib.unified_diff(original_mem.splitlines(True), mem.splitlines(True), fromfile='upstream/mem.h', tofile='patched/mem.h'))
(root / 'probes/emulator/debugger-hooks.patch').write_text(diff)
