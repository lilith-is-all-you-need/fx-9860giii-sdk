 .text
 .macro SC name,number
 .align 2
 .global _\name
_\name:
 mov.l 1f,r0
 mov.l 2f,r2
 jmp @r2
 nop
 .align 2
1: .long \number
2: .long 0x80010070
 .endm
 SC r_malloc,0xacd
 SC r_free,0xacc
 SC r_sleep,0x420
