#include "debug_bridge.h"
bool probe_debug_ignore_memory;
void probe_debug_before(Cpu *cpu, uint32_t address) { (void)cpu; (void)address; }
void probe_debug_poll(Cpu *cpu) { (void)cpu; }
void probe_debug_memory(uint32_t address, int size, bool write) { (void)address; (void)size; (void)write; }
