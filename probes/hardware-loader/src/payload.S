 .section .text.entry,"ax"
 .align 2
 .global _module_start
_module_start:
 sts.l pr,@-r15
 mov.l .Lmain,r0
 jsr @r0
 nop
 lds.l @r15+,pr
 rts
 nop
 .align 2
.Lmain: .long _module_main
