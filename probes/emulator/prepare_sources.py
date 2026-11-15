"""Generate audited debugger/compatibility copies; upstream stays unchanged."""
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

# Keep OS quoted includes beside the patched engine headers too. Compatibility
# implementations live in reviewable headers, not in the submodule checkout.
os_out = out / 'os'
os_out.mkdir(exist_ok=True)
for p in (up / 'os').glob('*'):
    if p.suffix in ('.c', '.h'):
        (os_out / p.name).write_bytes(p.read_bytes())
syscalls = original_syscalls = (up / 'os/syscalls.c').read_text()
syscalls = '#include "debug_bridge.h"\n#include "syscall_trace.h"\n#include <stdlib.h>\n' + syscalls
start = syscalls.index('/*\n * The OS heap ')
end = syscalls.index('/* Timer_Install', start)
syscalls = syscalls[:start] + '#include "heap_compat.h"\n\n' + syscalls[end:]
start = syscalls.index('/* memcpy(dst, src, n)')
end = syscalls.index('static SC(sc_strlen)', start)
syscalls = syscalls[:start] + '#include "memory_compat.h"\n\n' + syscalls[end:]
syscalls = replace_once(syscalls, '    {0x0E6D, "realloc", sc_realloc},',
    '    {0x0E6B, "calloc", sc_calloc},\n    {0x0E6C, "memmove", sc_memcpy},\n    {0x0E6D, "realloc", sc_realloc},')
syscalls = replace_once(syscalls, 'static SC(sc_get_setup_setting)', '''static SC(sc_fx_cursor_position)
{
    int x = (int8_t)a[0], y = (int8_t)a[1];
    if (x < 0 || x > 20 || y < 0 || y > 7) return 0;
    emu->cursor_x = x + 1;
    emu->cursor_y = y + 1;
    return 1;
}

/* Only the fx keyboard-mode entry is modeled. Do not invent other settings. */
static SC(sc_fx_setup_get)
{
    if (a[0] != 0x14) {
        cpu_report(&emu->cpu, "unsupported Setup_GetEntry index 0x%X", a[0]);
        emu->cpu.state = CPU_ERROR;
        return 0;
    }
    return (emu->key_shift ? 1 : 0) |
           (emu->key_alpha == ALPHA_ONCE ? 4 : emu->key_alpha == ALPHA_LOCK ? 0x84 : 0);
}

static SC(sc_get_setup_setting)''')
syscalls = replace_once(syscalls, '    {0x0494, "SetQuitHandler", sc_nothing},',
    '    {0x04DC, "Setup_GetEntry", sc_fx_setup_get},\n    {0x0494, "SetQuitHandler", sc_nothing},')
syscalls = replace_once(syscalls, '    {0x0139, "Cursor_SetFlashStyle", sc_nothing},',
    '    {0x0138, "Cursor_SetPosition", sc_fx_cursor_position},\n    {0x0139, "Cursor_SetFlashStyle", sc_nothing},')
syscalls = replace_once(syscalls, '    {0x0813, "SaveDisp", sc_fx_save_disp},',
    '    {0x0812, "Cursor_SetFlashOff", sc_nothing}, /* cursor is not rendered */\n    {0x0813, "SaveDisp", sc_fx_save_disp},')
syscalls = replace_once(syscalls, '        sc_spend(emu, SYSCALL_CYCLES);', '''        uint64_t event_id = probe_trace_enter(emu, number, args, table[i].name,
            table[i].fn == sc_nothing ? "stub" : "implemented");
        if (table[i].fn == sc_nothing && probe_trace_strict()) {
            cpu_report(cpu, "stub syscall 0x%04X %s rejected by strict mode", number, table[i].name);
            cpu->state = CPU_ERROR;
            probe_trace_leave(emu, event_id, 0, false);
            return;
        }
        sc_spend(emu, SYSCALL_CYCLES);''')
syscalls = replace_once(syscalls, '''        return;
    }
    cpu_report(cpu, "unimplemented %ssyscall''', '''        probe_trace_leave(emu, event_id, cpu->r[0], cpu->state != CPU_ERROR);
        return;
    }
    uint64_t event_id = probe_trace_enter(emu, number, args, "unknown", "missing");
    cpu_report(cpu, "unimplemented %ssyscall''')
syscalls = replace_once(syscalls, '''    cpu->state = CPU_ERROR;
}

void syscalls_install''', '''    cpu->state = CPU_ERROR;
    probe_trace_leave(emu, event_id, 0, false);
}

void syscalls_install''')
(os_out / 'syscalls.c').write_text(syscalls)
compat_diff = ''.join(difflib.unified_diff(original_syscalls.splitlines(True), syscalls.splitlines(True),
    fromfile='upstream/os/syscalls.c', tofile='patched/os/syscalls.c'))
(root / 'probes/emulator/runtime-compat.patch').write_text(compat_diff)
