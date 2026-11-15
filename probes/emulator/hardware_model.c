#include "hardware_model.h"
#include "emu.h"
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t a, d, x; } Tlb;
typedef struct { uint32_t tag; uint64_t age; bool valid; uint8_t bytes[32]; } ILine;
typedef struct ProbeHardware {
    Emu *emu;
    Tlb u[64], i[4];
    uint32_t pteh, ptel, ptea, mmucr, ccr, quit;
    bool exiting;
    uint64_t age;
    ILine cache[128][4]; /* 16 KiB, 32-byte lines; replacement is functional LRU. */
} Hardware;

void probe_hw_snapshot(const Memory *m,FILE *f)
{
    const Hardware *h=m->probe_hw;
    if(!h){fputs("null",f);return;}
    fprintf(f,"{\"pteh\":%u,\"ptel\":%u,\"ptea\":%u,\"mmucr\":%u,\"ccr\":%u,\"quitHandler\":%u,\"exiting\":%s,\"utlb\":[",h->pteh,h->ptel,h->ptea,h->mmucr,h->ccr,h->quit,h->exiting?"true":"false");
    for(int i=0;i<64;i++)fprintf(f,"%s[%u,%u,%u]",i?",":"",h->u[i].a,h->u[i].d,h->u[i].x);
    fputs("],\"itlb\":[",f);
    for(int i=0;i<4;i++)fprintf(f,"%s[%u,%u,%u]",i?",":"",h->i[i].a,h->i[i].d,h->i[i].x);
    fputs("],\"instructionCache\":[",f);bool first=true;
    for(int s=0;s<128;s++)for(int w=0;w<4;w++)if(h->cache[s][w].valid){
        const ILine *line=&h->cache[s][w];fprintf(f,"%s{\"set\":%d,\"way\":%d,\"tag\":%u,\"bytes\":\"",first?"":",",s,w,line->tag);first=false;
        for(int i=0;i<32;i++)fprintf(f,"%02x",line->bytes[i]);
        fputs("\"}",f);
    }
    fputs("]}",f);
}

static uint32_t raw_read(Memory *m, uint32_t a, int size)
{
    uint8_t *p = m->rd[a >> PAGE_SHIFT];
    return p && !(a & (size-1)) ? be_read(p+(a & (PAGE_SIZE-1)),size) : mem_read_slow(m,a,size);
}
static void raw_write(Memory *m, uint32_t a, uint32_t v, int size)
{
    uint8_t *p = m->wr[a >> PAGE_SHIFT];
    if(p && !(a & (size-1))) be_write(p+(a & (PAGE_SIZE-1)),v,size);
    else mem_write_slow(m,a,v,size);
}
static void error(Hardware *h, uint32_t a, bool write, const char *why)
{
    Memory *m=&h->emu->mem;
    if(!m->fault) { m->fault=FAULT_UNMAPPED; m->fault_addr=a; m->fault_write=write; }
    cpu_report(&h->emu->cpu,"SH7305 %s at %08X (no fabricated OS mapping)",why,a);
    h->emu->cpu.state=CPU_ERROR;
}
static unsigned page_size(uint32_t d)
{
    unsigned s=((d>>6)&2)|((d>>4)&1);
    return s==0?1024:s==1?4096:s==2?65536:1048576;
}
static bool match(Hardware *h, const Tlb *t, uint32_t a)
{
    bool shared=(t->d&2) || ((h->mmucr&0x100) && (h->emu->cpu.sr&SR_MD));
    return (t->a&0x100) && (t->d&0x100) &&
        (t->a & ~(page_size(t->d)-1)) == (a & ~(page_size(t->d)-1)) &&
        (shared || (t->a&255)==(h->pteh&255));
}
static int lookup(Hardware *h, Tlb *t, int count, uint32_t a)
{
    int found=-1;
    for(int k=0;k<count;k++) if(match(h,&t[k],a)) {
        if(found>=0) { error(h,a,false,"TLB multiple hit"); return -2; }
        found=k;
    }
    return found;
}
static unsigned advance_urc(Hardware *h)
{
    unsigned n=(h->mmucr>>10)&63, bound=(h->mmucr>>18)&63;
    if(!bound) bound=64;
    if(n>=bound) n=0;
    unsigned next=n+1; if(next>=bound) next=0;
    h->mmucr=(h->mmucr&~0xfc00u)|(next<<10);
    return n;
}
/* Only the OS-owned backing map can refill a miss. Temporary user mappings
 * have no hidden shadow page table and really disappear when evicted. */
static int os_refill(Hardware *h, uint32_t a)
{
    Emu *e=h->emu; Memory *m=&e->mem;
    uint8_t *p=m->rd[a>>PAGE_SHIFT];
    if(!p) return -1;
    uintptr_t host=(uintptr_t)p, rom=(uintptr_t)e->rom, ram=(uintptr_t)e->ram;
    uint32_t phys, flags;
    if(host>=rom && host-rom<ROM_SIZE) { phys=(uint32_t)(host-rom); flags=0x15c; }
    else if(host>=ram && host-ram<e->layout->ram_size) {
        phys=e->layout->ram_phys+(uint32_t)(host-ram); flags=0x17c;
    } else return -1;
    unsigned n=advance_urc(h);
    h->u[n]=(Tlb){(a&~4095u)|0x300|(h->pteh&255),phys|flags,0};
    return (int)n;
}
static bool translate(Hardware *h,uint32_t a,bool fetch,bool write,uint32_t *pa,bool *cache)
{
    Cpu *cpu=&h->emu->cpu;
    *pa=a; *cache=(a>>29)==4;
    if(a>=0x80000000u && a<0xc0000000u) {
        if(!(cpu->sr&SR_MD)) { error(h,a,write,"privileged address"); return false; }
        return true;
    }
    if(a>=0xe0000000u) { *cache=false; return true; }
    if(!(h->mmucr&1)) { *pa=P1(a&0x1fffffff); *cache=true; return true; }
    if(h->mmucr&0x80) { error(h,a,write,"extended MMU mode unsupported"); return false; }
    int n=fetch?lookup(h,h->i,4,a):-1;
    if(n==-2) return false;
    Tlb *t=n>=0?&h->i[n]:NULL;
    if(!t) {
        int u=lookup(h,h->u,64,a);
        if(u==-2) return false;
        if(u<0) u=os_refill(h,a);
        if(u<0) { error(h,a,write,"TLB miss"); return false; }
        t=&h->u[u];
        if(fetch) {
            /* Prefer invalid entries. A deterministic round-robin fallback;
             * do not advertise cycle/pseudo-LRU accurate replacement. */
            unsigned slot=4;
            for(unsigned k=0;k<4;k++) if(!(h->i[k].a&0x100)) { slot=k; break; }
            if(slot==4) slot=(unsigned)(h->age++&3);
            h->i[slot]=*t; t=&h->i[slot];
        } else advance_urc(h);
    }
    unsigned pr=(t->d>>5)&3;
    if((!(cpu->sr&SR_MD)&&pr<2) || (write&&!(pr&1))) {
        error(h,a,write,"TLB protection violation"); return false;
    }
    if(write&&!(t->d&4)) { error(h,a,true,"initial page write"); return false; }
    uint32_t mask=page_size(t->d)-1;
    *pa=P1((t->d&0x1ffffc00u&~mask)|(a&mask));
    *cache=(t->d&8)!=0;
    return true;
}
static uint32_t *reg(Hardware *h,uint32_t a)
{
    switch(a) {
    case 0xff000000:return &h->pteh; case 0xff000004:return &h->ptel;
    case 0xff000010:return &h->mmucr; case 0xff00001c:return &h->ccr;
    case 0xff000034:return &h->ptea;
    }
    unsigned k=(a>>8)&63;
    if((a&0xffffc0ffu)==0xf6000000u)return &h->u[k].a;
    if((a&0xffffc0ffu)==0xf7000000u)return &h->u[k].d;
    if((a&0xffffc0ffu)==0xf7800000u)return &h->u[k].x;
    k&=3;
    if((a&0xfffffcffu)==0xf2000000u)return &h->i[k].a;
    if((a&0xfffffcffu)==0xf3000000u)return &h->i[k].d;
    if((a&0xfffffcffu)==0xf3800000u)return &h->i[k].x;
    return NULL;
}
uint32_t probe_hw_read(Memory *m,uint32_t a,int size)
{
    Hardware *h=m->probe_hw; uint32_t *r=reg(h,a);
    if(r) {
        if(size!=4) { error(h,a,false,"non-long control access unsupported"); return 0; }
        return *r;
    }
    uint32_t pa; bool cached;
    if(!translate(h,a,false,false,&pa,&cached))return 0;
    return raw_read(m,pa,size);
}
void probe_hw_write(Memory *m,uint32_t a,uint32_t v,int size)
{
    Hardware *h=m->probe_hw; uint32_t *r=reg(h,a);
    if(r) {
        if(size!=4) { error(h,a,true,"non-long control access unsupported"); return; }
        *r=v;
        if(a==0xff000010 && (v&4)) {
            for(int n=0;n<64;n++) { h->u[n].a&=~0x100u; h->u[n].d&=~0x100u; }
            for(int n=0;n<4;n++) { h->i[n].a&=~0x100u; h->i[n].d&=~0x100u; }
            *r&=~4u;
        }
        if(a==0xff00001c) {
            if(v&0x800) memset(h->cache,0,sizeof h->cache);
            *r&=~0x808u; /* invalidate request bits self-clear */
        }
        /* V/D are shared fields between address/data array views. */
        unsigned k=(a>>8)&63;
        if((a&0xffffc0ffu)==0xf6000000u)
            h->u[k].d=(h->u[k].d&~0x104u)|(v&0x100)|((v>>7)&4);
        if((a&0xffffc0ffu)==0xf7000000u)
            h->u[k].a=(h->u[k].a&~0x300u)|(v&0x100)|((v&4)<<7);
        k&=3;
        if((a&0xfffffcffu)==0xf2000000u)h->i[k].d=(h->i[k].d&~0x100u)|(v&0x100);
        if((a&0xfffffcffu)==0xf3000000u)h->i[k].a=(h->i[k].a&~0x100u)|(v&0x100);
        return;
    }
    uint32_t pa; bool cached;
    if(translate(h,a,false,true,&pa,&cached)) raw_write(m,pa,v,size);
}
uint16_t probe_hw_fetch(Cpu *cpu,uint32_t a)
{
    Memory *m=cpu->mem; Hardware *h=m->probe_hw;
    if(!h)return mem_read16(m,a);
    if(a&1) { error(h,a,false,"unaligned instruction fetch");return 0; }
    uint32_t pa; bool cached;
    if(!translate(h,a,true,false,&pa,&cached))return 0;
    if(!cached || !(h->ccr&0x100))return (uint16_t)raw_read(m,pa,2);
    uint32_t tag=pa&~31u; ILine *set=h->cache[(a>>5)&127],*line=NULL;
    for(int i=0;i<4;i++)if(set[i].valid&&set[i].tag==tag)line=&set[i];
    if(!line) {
        line=&set[0];
        for(int i=0;i<4;i++)if(!set[i].valid||set[i].age<line->age)line=&set[i];
        for(int i=0;i<32;i++)line->bytes[i]=(uint8_t)raw_read(m,tag+(unsigned)i,1);
        if(m->fault)return 0;
        line->tag=tag;line->valid=true;
    }
    line->age=++h->age;
    return (uint16_t)be_read(line->bytes+(a&31),2);
}
void probe_hw_cache(Cpu *cpu,uint16_t op,uint32_t a)
{
    Hardware *h=cpu->mem->probe_hw;
    if(!h)return;
    if((op&0x00f0)==0x00e0) { /* ICBI; P2 is not instruction-cacheable. */
        uint32_t pa;bool cached;
        if(!translate(h,a,false,false,&pa,&cached)||!cached)return;
        ILine *set=h->cache[(a>>5)&127];
        for(int i=0;i<4;i++)if(set[i].tag==(pa&~31u))set[i].valid=false;
    }
    /* Operand accesses are an explicit coherent approximation. CCR=0x105
     * enables P1 copy-back; absence of delay in one probe is NOT proof of WT.
     * OCBP/OCBWB/SYNCO do not yet simulate operand cache lines or bus timing. */
}
void probe_hw_ldtlb(Cpu *cpu)
{
    Hardware *h=cpu->mem->probe_hw;if(!h)return;
    if(!(cpu->sr&SR_MD)) { error(h,cpu->pc,false,"privileged LDTLB");return; }
    unsigned slot=(h->mmucr>>10)&63;
    h->u[slot]=(Tlb){(h->pteh&0xfffffcffu)|(h->ptel&0x100)|((h->ptel&4)<<7),
                     h->ptel&0x1ffffdffu,h->ptea};
    /* Deliberately leave ITLB and I-cache stale, as observed on hardware. */
}
uint8_t *probe_hw_pointer(Memory *m,uint32_t a,uint32_t len)
{
    Hardware *h=m->probe_hw;uint32_t pa;bool cached;
    if(!len)len=1;
    if(a+len-1<a||!translate(h,a,false,false,&pa,&cached))return NULL;
    if(pa>=0xa0000000u&&pa<0xc0000000u)pa-=0x20000000u;
    uint8_t *p=m->rd[pa>>PAGE_SHIFT];if(!p)return NULL;
    p+=pa&(PAGE_SIZE-1);
    for(uint32_t n=0;n<len;) {
        uint32_t x;
        if(!translate(h,a+n,false,false,&x,&cached))return NULL;
        if(x>=0xa0000000u&&x<0xc0000000u)x-=0x20000000u;
        uint8_t *q=m->rd[x>>PAGE_SHIFT];
        if(!q||q+(x&(PAGE_SIZE-1))!=p+n)return NULL;
        uint32_t step=1024-((a+n)&1023); if(step>len-n)step=len-n;n+=step;
    }
    return p;
}
uint8_t *probe_hw_byte(Memory *m,uint32_t a,bool write)
{
    Hardware *h=m->probe_hw;uint32_t pa;bool cached;
    if(!translate(h,a,false,write,&pa,&cached))return NULL;
    if(pa>=0xa0000000u&&pa<0xc0000000u)pa-=0x20000000u;
    uint8_t *p=(write?m->wr:m->rd)[pa>>PAGE_SHIFT];
    return p?p+(pa&(PAGE_SIZE-1)):NULL;
}
bool probe_hw_enabled(const Memory *m){return m->probe_hw!=NULL;}
/* Debug reads must not refill/evict pages, populate caches or trigger MMIO. */
uint8_t *probe_hw_debug_byte(Memory *m,uint32_t a,bool write)
{
    Hardware *h=m->probe_hw; uint32_t pa=a;
    if(h && a<0x80000000u && (h->mmucr&1)) {
        Tlb *t=NULL;
        for(unsigned n=0;n<64;n++)if(match(h,&h->u[n],a)) {
            if(t)return NULL;
            t=&h->u[n];
        }
        if(t) {
            if(write&&!(t->d&0x20))return NULL;
            unsigned mask=page_size(t->d)-1;
            pa=P1((t->d&0x1ffffc00u&~mask)|(a&mask));
        }
    } else if(h && a<0x80000000u)pa=P1(a&0x1fffffff);
    if(pa>=0xa0000000u&&pa<0xc0000000u)pa-=0x20000000u;
    uint8_t *p=(write?m->wr:m->rd)[pa>>PAGE_SHIFT];
    return p?p+(pa&(PAGE_SIZE-1)):NULL;
}
bool probe_hw_init(void *ptr,bool enable)
{
    Emu *e=ptr;probe_hw_destroy(&e->mem);
    if(!enable)return true;
    Hardware *h=calloc(1,sizeof *h);if(!h)return false;
    e->mem.probe_hw=h;h->emu=e;h->ccr=0x105;h->mmucr=0x00fc0101;
    /* HLE starts with known OS pages. More OS pages refill on demand. */
    for(unsigned k=0;k<2;k++)os_refill(h,ADDIN_BASE+k*4096);
    for(unsigned k=0;k<e->layout->uram_size/4096 && k<32;k++)os_refill(h,URAM_BASE+k*4096);
    return true;
}
void probe_hw_destroy(Memory *m){free(m->probe_hw);m->probe_hw=NULL;}
void probe_hw_register_quit(Cpu *cpu,uint32_t fn)
{ Hardware *h=cpu->mem->probe_hw;if(h)h->quit=fn; }
bool probe_hw_quit(void *ptr)
{
    Emu *e=ptr;Hardware *h=e->mem.probe_hw;
    if(!h||!h->quit||h->exiting)return true;
    uint32_t fn=h->quit;h->quit=0;h->exiting=true;
    bool ok=cpu_call(&e->cpu,fn,100000000u);
    h->exiting=false;
    if(!ok&&e->cpu.state!=CPU_ERROR) {
        cpu_report(&e->cpu,"quit handler did not return within HLE budget");e->cpu.state=CPU_ERROR;
    }
    return ok;
}
bool probe_hw_exit(Cpu *cpu)
{
    Hardware *h=cpu->mem->probe_hw;
    return !h||probe_hw_quit(h->emu);
}
