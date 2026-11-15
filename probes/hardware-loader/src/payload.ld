OUTPUT_ARCH(sh)
ENTRY(_module_start)
SECTIONS {
 .text 0x00300200 : { *(.text.entry) *(.text .text.*) *(.rodata .rodata.*) }
 ASSERT(. <= 0x00300ff0,"payload code overlaps resource fixture")
 .resource 0x00300ff0 : { KEEP(*(.resource)) }
 .far 0x00303000 : { KEEP(*(.far)) }
 .end 0x00303ffc : { LONG(0x5032454e); }
 .data 0x08100004 : AT(0x00302000) { *(.data .data.*) }
 .bss 0x08100008 (NOLOAD) : { *(.bss .bss.*) }
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
