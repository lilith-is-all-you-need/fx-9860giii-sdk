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
cpu = '#include "debug_bridge.h"\n#include "hardware_model.h"\n' + cpu
cpu = replace_once(cpu, '    exec(cpu, pc + 2);', '''    cpu->pc = pc + 2;
    probe_debug_before(cpu, pc + 2);
    exec(cpu, pc + 2);''')
cpu = replace_once(cpu, '    uint16_t op = mem_read16(mem, pc);', '''    probe_debug_ignore_memory = true;
    uint16_t op = probe_hw_fetch(cpu, pc);
    probe_debug_ignore_memory = false;''')
cpu = replace_once(cpu, 'static inline void step_one(Cpu *cpu)\n{', '''static inline void step_one(Cpu *cpu)
{
    probe_debug_before(cpu, cpu->pc);''')
cpu = replace_once(cpu, '        cpu->attention = false;', '''        probe_debug_poll(cpu);
        cpu->attention = false;''')
cpu = replace_once(cpu, 'case 0x0038: return;', 'case 0x0038: probe_hw_ldtlb(cpu); return;')
cpu = replace_once(cpu, 'case 0x8: case 0x9: case 0xA: case 0xB: case 0xD: case 0xE: return;',
    'case 0x8: case 0x9: case 0xA: case 0xB: case 0xD: case 0xE: probe_hw_cache(cpu, op, RN); return;')
cpu = replace_once(cpu, '    if (cpu->pc == EXIT_ADDR) {',
    '    if (cpu->pc == EXIT_ADDR) {\n        if (!probe_hw_exit(cpu)) return;')
(out / 'cpu.c').write_text(cpu)

mem = original_mem = (up / 'mem.h').read_text()
mem = replace_once(mem, '#include <stdint.h>', '''#include <stdint.h>
/* Hook covers interpreted data accesses; debugger reads use raw pages. */
extern void probe_debug_memory(uint32_t address, int size, bool write);''')
mem = replace_once(mem, '    uint8_t **rd;', '    struct ProbeHardware *probe_hw;\n    uint8_t **rd;')
mem = replace_once(mem, '/* SH is big-endian.', '''uint32_t probe_hw_read(Memory *, uint32_t, int);
void probe_hw_write(Memory *, uint32_t, uint32_t, int);
/* SH is big-endian.''')
for bits in (8,16,32):
    read = f'static inline uint{bits}_t mem_read{bits}(Memory *mem, uint32_t addr)\n{{'
    write = f'static inline void mem_write{bits}(Memory *mem, uint32_t addr, uint{bits}_t value)\n{{'
    mem = replace_once(mem, read, read + f'\n    probe_debug_memory(addr, {bits//8}, false);\n    if(mem->probe_hw) return (uint{bits}_t)probe_hw_read(mem, addr, {bits//8});')
    mem = replace_once(mem, write, write + f'\n    probe_debug_memory(addr, {bits//8}, true);\n    if(mem->probe_hw) {{ probe_hw_write(mem, addr, value, {bits//8}); return; }}')
(out / 'mem.h').write_text(mem)
# Quoted includes resolve next to source. Copy all engine sources/headers and
# overwrite just the two patched files, avoiding an inconsistent mem.h copy.
for p in up.glob('*'):
    if p.suffix in ('.c', '.h') and p.name not in ('cpu.c', 'mem.h'):
        (out / p.name).write_bytes(p.read_bytes())
mem_c = original_mem_c = (up / 'mem.c').read_text()
mem_c = '#include "hardware_model.h"\n' + mem_c
mem_c = replace_once(mem_c, 'void mem_free(Memory *mem)\n{', 'void mem_free(Memory *mem)\n{\n    probe_hw_destroy(mem);')
mem_c = replace_once(mem_c, 'uint8_t *mem_ptr(Memory *mem, uint32_t addr, uint32_t len)\n{',
    'uint8_t *mem_ptr(Memory *mem, uint32_t addr, uint32_t len)\n{\n    if(mem->probe_hw) return probe_hw_pointer(mem, addr, len);')
(out / 'mem.c').write_text(mem_c)
diff = ''.join(difflib.unified_diff(original_cpu.splitlines(True), cpu.splitlines(True), fromfile='upstream/cpu.c', tofile='patched/cpu.c'))
diff += ''.join(difflib.unified_diff(original_mem.splitlines(True), mem.splitlines(True), fromfile='upstream/mem.h', tofile='patched/mem.h'))
diff += ''.join(difflib.unified_diff(original_mem_c.splitlines(True), mem_c.splitlines(True), fromfile='upstream/mem.c', tofile='patched/mem.c'))
(root / 'probes/emulator/debugger-hooks.patch').write_text(diff)

# Keep OS quoted includes beside the patched engine headers too. Compatibility
# implementations live in reviewable headers, not in the submodule checkout.
os_out = out / 'os'
os_out.mkdir(exist_ok=True)
for p in (up / 'os').glob('*'):
    if p.suffix in ('.c', '.h'):
        (os_out / p.name).write_bytes(p.read_bytes())
syscalls = original_syscalls = (up / 'os/syscalls.c').read_text()
syscalls = '#include "debug_bridge.h"\n#include "hardware_model.h"\n#include "syscall_trace.h"\n#include <stdlib.h>\n' + syscalls
start = syscalls.index('/*\n * The OS heap ')
end = syscalls.index('/* Timer_Install', start)
syscalls = syscalls[:start] + '#include "heap_compat.h"\n\n' + syscalls[end:]
start = syscalls.index('/* memcpy(dst, src, n)')
end = syscalls.index('static SC(sc_strlen)', start)
syscalls = syscalls[:start] + '#include "memory_compat.h"\n\n' + syscalls[end:]
syscalls = replace_once(syscalls, '    {0x0E6D, "realloc", sc_realloc},',
    '    {0x0E6B, "calloc", sc_calloc},\n    {0x0E6C, "memmove", sc_memcpy},\n    {0x0E6D, "realloc", sc_realloc},')
syscalls = replace_once(syscalls, 'static SC(sc_get_setup_setting)', '''static SC(sc_quit_handler)
{
    probe_hw_register_quit(&emu->cpu, a[0]);
    return 0;
}

static SC(sc_fx_cursor_position)
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
    '    {0x04DC, "Setup_GetEntry", sc_fx_setup_get},\n    {0x0494, "SetQuitHandler", sc_quit_handler},')
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
keys = original_keys = (up / 'os/syscalls_keys.c').read_text()
keys = '#include "debug_bridge.h"\n' + keys
keys = replace_once(keys, '        if (menu_dropped(emu, code))\n            continue;',
    '        if (menu_dropped(emu, code)) {\n            if(probe_os_menu(&emu->cpu)) return -1;\n            continue;\n        }')
# gint uses a timer-injected matrix MENU followed by GetKeyWait(menu=0).
# Unlike PutKey(GetKey-code), this path must enter the menu lifecycle too.
keys = replace_once(keys, '    uint32_t type = a[2];', '    uint32_t type = a[2];\nwait_again: ;')
keys = replace_once(keys, '    os_matrix(key, &col, &row);\n    mem_write32(mem, a[0], (uint32_t)col);', '''    if (KEYS[key].getkey == KEY_CTRL_MENU && !a[4]) {
        if(probe_os_menu(&emu->cpu)) return 0;
        goto wait_again;
    }
    os_matrix(key, &col, &row);
    mem_write32(mem, a[0], (uint32_t)col);''')
keys += '''
/* Empty buffered events without releasing keys that are physically held. */
SC(sc_clear_key_buffer)
{
    (void)a;
    emu->inject_count = 0;
    probe_clear_key_buffer();
    return 0;
}
'''
(os_out / 'syscalls_impl.h').write_text((os_out / 'syscalls_impl.h').read_text()+'\nSC(sc_clear_key_buffer);\n')
syscalls = replace_once(syscalls, '{0x0241, "Keyboard_ClrBuffer", sc_nothing}',
    '{0x0241, "Keyboard_ClrBuffer", sc_clear_key_buffer}')
(os_out / 'syscalls.c').write_text(syscalls)
(os_out / 'syscalls_keys.c').write_text(keys)
fx = original_fx = (up / 'os/syscalls_fx.c').read_text()
# Probe v1 returns minor=0x70 for OS 03.70, not decimal 70 (0x46).
fx = replace_once(fx, "int major = (v[0] - '0') * 10 + (v[1] - '0'), minor = (v[3] - '0') * 10 + (v[4] - '0');",
    "int major = (v[0] - '0') * 16 + (v[1] - '0'), minor = (v[3] - '0') * 16 + (v[4] - '0');")
(os_out / 'syscalls_fx.c').write_text(fx)
timers = original_timers = (up / 'os/syscalls_time.c').read_text()
timers = replace_once(timers, 'uint64_t timers_next_due(const Emu *emu)\n{',
    'uint64_t timers_next_due(const Emu *emu)\n{\n    if(emu->in_timer || (emu->cpu.sr & (SR_IMASK|SR_BL))) return UINT64_MAX;')
timers = replace_once(timers, 'if (emu->in_timer || emu->cpu.state != CPU_RUNNING)',
    'if (emu->in_timer || emu->cpu.state != CPU_RUNNING || (emu->cpu.sr & (SR_IMASK|SR_BL)))')
# A masked timer cannot advance its deadline; do not busy-loop during OS delay.
timers = replace_once(timers, 'while (emu->cpu.state == CPU_RUNNING && !emu->in_timer)',
    'while (emu->cpu.state == CPU_RUNNING && !emu->in_timer && !(emu->cpu.sr & (SR_IMASK|SR_BL)))')
(os_out / 'syscalls_time.c').write_text(timers)
compat_diff = ''.join(difflib.unified_diff(original_syscalls.splitlines(True), syscalls.splitlines(True),
    fromfile='upstream/os/syscalls.c', tofile='patched/os/syscalls.c'))
for name, old, new in [('syscalls_keys.c',original_keys,keys),('syscalls_time.c',original_timers,timers),('syscalls_fx.c',original_fx,fx)]:
    compat_diff += ''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='upstream/os/'+name,tofile='patched/os/'+name))
(root / 'probes/emulator/runtime-compat.patch').write_text(compat_diff)
