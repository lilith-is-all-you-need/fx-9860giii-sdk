#include "probe.h"
volatile uint32_t initialized=0x1234abcd;
volatile uint32_t zeroed[1025];
__attribute__((section(".resource"),used))
const unsigned char resource[64]={
 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,
 17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,
 33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,
 49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64 };
__attribute__((section(".far"),noinline))
static uint32_t far_call(uint32_t x){return x^0x5a5aa5a5;}
__attribute__((section(".far"),noinline))
static void target_quit(PayloadState *s){s->target_quit_calls++;}
uint32_t module_main(PayloadState *s)
{
 uint32_t sum=0,bss=0;
 const volatile unsigned char *p=resource;
 for(unsigned i=0;i<64;i++)sum+=p[i];
 for(unsigned i=0;i<1025;i++)bss|=zeroed[i];
 s->resource_sum=sum;s->data_seen=initialized;s->bss_seen=bss;
 s->heap_ok=0;uint32_t *v=r_malloc(64);
 if(v){*v=0xaabbccdd;s->heap_ok=*v==0xaabbccdd;r_free(v);}
 unsigned before=s->ticks;
 r_sleep(240);
 s->timer_during_payload=s->ticks-before;
 zeroed[0]=zeroed[1024]=++s->calls;
 s->target_quit=(uint32_t)(uintptr_t)target_quit;
 return far_call(sum)==(2080^0x5a5aa5a5)&&initialized==0x1234abcd&&REG(0x00302000)==initialized&&!bss&&s->heap_ok?0x600d0001:0xbad00001;
}
