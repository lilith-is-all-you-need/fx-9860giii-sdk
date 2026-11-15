#include "probe.h"
/* This entire translation unit, strings, syscall stubs and pointer word are
 * relocated from retained ELF relocations into P2. No guessed pointer scan. */
Context *resident_context=(Context *)(uintptr_t)1;
static void text(Context *c,const char *s)
{
 while(*s&&c->log_used<LOG_BYTES-2)c->log[c->log_used++]=*s++;
 if(*s)c->io_error=-1007;
}
static void hex(Context *c,uint32_t n)
{
 for(int k=7;k>=0;k--){unsigned x=(n>>(k*4))&15;char b[2]={(char)(x<10?'0'+x:'A'+x-10),0};text(c,b);}
}
static void event(Context *c,const char *s,uint32_t a,uint32_t b)
{text(c,s);text(c,"=");hex(c,a);text(c,",");hex(c,b);text(c,"\n");}
static int has(Context *c,const char *s)
{
 for(unsigned i=0;i<c->log_used;i++){unsigned j=0;while(s[j]&&i+j<c->log_used&&c->log[i+j]==s[j])j++;if(!s[j])return 1;}return 0;
}
static int save(Context *c)
{
 if(c->io_error)return 0;
 for(unsigned i=c->log_used;i<LOG_BYTES;i++)c->log[i]=' ';
 int fd=r_open(c->log_path,2,0);if(fd<0){c->io_error=fd;return 0;}
 int n=r_write(fd,c->log,LOG_BYTES),rc=r_close(fd);
 if(n!=LOG_BYTES||rc<0){c->io_error=n<0?n:rc<0?rc:-1001;return 0;}
 char tail[32];unsigned count=c->log_used<32?c->log_used:32;
 fd=r_open(c->log_path,1,0);if(fd<0){c->io_error=fd;return 0;}
 n=r_read(fd,tail,count,c->log_used-count);rc=r_close(fd);
 if(n!=(int)count||rc<0){c->io_error=-1002;return 0;}
 for(unsigned i=0;i<count;i++)if(tail[i]!=c->log[c->log_used-count+i]){c->io_error=-1003;return 0;}
 return 1;
}
static void screen(const char *a,const char *b,const char *d)
{
 r_clear();r_print(0,0,(const unsigned char *)"Loader Probe 2",0);
 r_print(0,13,(const unsigned char *)a,0);r_print(0,26,(const unsigned char *)b,0);
 r_print(0,39,(const unsigned char *)d,0);r_print(0,53,(const unsigned char *)"Probe2.txt / EXIT",0);r_display();
}
static unsigned page_size(uint32_t d)
{unsigned x=((d>>6)&2)|((d>>4)&1);return x==0?1024:x==1?4096:x==2?65536:1048576;}
static uint32_t va(Context *c,unsigned n)
{return n<4?c->image_va+n*4096:c->ram_va+(n-4)*4096;}
static int overlaps(Context *c,uint32_t addr,uint32_t data)
{
 unsigned size=page_size(data);uint32_t start=addr&~(size-1);
 return ((uint64_t)start<c->image_va+IMAGE_BYTES&&(uint64_t)start+size>c->image_va)||
        ((uint64_t)start<c->ram_va+8192&&(uint64_t)start+size>c->ram_va);
}
static void drop_itlb(Context *c)
{
 for(unsigned i=0;i<4;i++){
  uintptr_t aa=0xf2000000+(i<<8),dd=0xf3000000+(i<<8);
  if(overlaps(c,REG(aa),REG(dd))){REG(aa)&=~0x100u;REG(dd)&=~0x100u;}
 }BARRIER();
}
/* Pure MMIO check: safe in a timer and before dereferencing the test window. */
static uint32_t guard(Context *c)
{
 uint32_t bad=0;
 if(!c->active)return 0x80000000;
 for(unsigned n=0;n<MAP_COUNT;n++){
  unsigned slot=c->slot[n];uint32_t a=REG(0xf6000000+(slot<<8)),d=REG(0xf7000000+(slot<<8));
  if((a&0xfffffd00)!=(va(c,n)|0x100)||(d&0x1ffffdff)!=(c->expected[n]|0x17e))bad|=1u<<n;
 }
 if(c->pinned&&((REG(0xff000010)>>18)&63)!=c->reserve)bad|=0x100;
 for(unsigned i=0;i<64;i++){
  uint32_t a=REG(0xf6000000+(i<<8)),d=REG(0xf7000000+(i<<8));
  if(!(a&0x100)||!overlaps(c,a,d))continue;
  unsigned own=0;for(unsigned n=0;n<MAP_COUNT;n++)own|=c->slot[n]==i;
  if(!own)bad|=0x200;
 }
 return bad;
}
static void synchronize(uintptr_t p,unsigned bytes)
{for(unsigned n=0;n<bytes;n+=32)purge(p+n);BARRIER();for(unsigned n=0;n<bytes;n+=32)invalidate(p+n);BARRIER();}
static int install(Context *c,int pinned,int original)
{
 c->image_va=original?0x00300000:0x12000000;c->ram_va=original?0x08100000:0x12100000;
 c->pinned=pinned;c->reserve=64;
 uint32_t sr=sr_get();sr_set(sr|0xf0);BARRIER();
 c->original_mmucr=REG(0xff000010);c->pteh=REG(0xff000000);c->ptel=REG(0xff000004);c->ptea=REG(0xff000034);
 if(!(c->original_mmucr&1)||(c->original_mmucr&0x80)){sr_set(sr);text(c,"SKIP_MMU_MODE\n");return 0;}
 unsigned count=0;
 for(unsigned i=0;i<64;i++){
  c->old[i]=(Entry){REG(0xf6000000+(i<<8)),REG(0xf7000000+(i<<8)),REG(0xf7800000+(i<<8))};
  c->touched[i]=0;
 }
 unsigned bound=(c->original_mmucr>>18)&63;if(!bound)bound=64;
 for(int i=(int)bound-1;i>=0&&count<MAP_COUNT;i--)
  if(!((c->old[i].addr|c->old[i].data)&0x100)){c->slot[count++]=(unsigned)i;c->reserve=(unsigned)i;}
 if(count<MAP_COUNT||c->reserve<8){sr_set(sr);text(c,"SKIP_FREE_TLB_SLOTS\n");return 0;}
 c->active=1;
 for(unsigned i=0;i<64;i++)if((c->old[i].addr&0x100)&&overlaps(c,c->old[i].addr,c->old[i].data)){
  c->touched[i]=1;REG(0xf6000000+(i<<8))&=~0x100u;REG(0xf7000000+(i<<8))&=~0x100u;
 }
 drop_itlb(c);
 uint32_t control=c->original_mmucr&~0xfc00u;
 if(pinned)control=(control&~0xfc0000u)|(c->reserve<<18);
 for(unsigned n=0;n<MAP_COUNT;n++){
  unsigned slot=c->slot[n];c->touched[slot]=1;
  uintptr_t p=n<4?c->image+n*4096:c->ram+(n-4)*4096;
  c->expected[n]=p&0x1fffffff;
  REG(0xff000000)=va(c,n)|(c->pteh&255);REG(0xff000004)=c->expected[n]|0x17e;
  REG(0xff000034)=0;REG(0xff000010)=control|(slot<<10);
  __asm__ volatile("ldtlb":::"memory");BARRIER();
 }
 REG(0xff000010)=control;BARRIER();
 uint32_t bad=guard(c);sr_set(sr);BARRIER();
 event(c,pinned?"PIN_INSTALL":"UNPIN_INSTALL",c->reserve,bad);
 if(bad)c->failed|=1;
 return bad==0;
}
static void stop_timer(Context *c)
{
 if(c->timer_id>0){
  int a=r_timer_stop(c->timer_id),b=r_timer_remove(c->timer_id);
  event(c,a<0||b<0?"FAIL_TIMER_STOP":"TIMER_STOP",a,b);
  if(a<0||b<0)c->failed|=128;
  if(b>=0)c->timer_id=0;
 }
}
static void restore(Context *c)
{
 if(!c->active)return;
 uint32_t sr=sr_get();sr_set(sr|0xf0);BARRIER();drop_itlb(c);
 unsigned bad=0;
 for(unsigned i=0;i<64;i++)if(c->touched[i]){
  REG(0xf6000000+(i<<8))=0;REG(0xf7000000+(i<<8))=c->old[i].data;
  REG(0xf7800000+(i<<8))=c->old[i].ext;REG(0xf6000000+(i<<8))=c->old[i].addr;
  if(REG(0xf6000000+(i<<8))!=c->old[i].addr||REG(0xf7000000+(i<<8))!=c->old[i].data||REG(0xf7800000+(i<<8))!=c->old[i].ext)bad++;
 }
 REG(0xff000000)=c->pteh;REG(0xff000004)=c->ptel;REG(0xff000034)=c->ptea;
 REG(0xff000010)=c->original_mmucr;BARRIER();c->active=0;sr_set(sr);BARRIER();
 event(c,bad?"FAIL_RESTORE":"PASS_RESTORE",bad,REG(0xff000010));if(bad)c->failed|=2;
}
void resident_timer(void)
{
 Context *c=resident_context;c->payload.ticks++;
 if(c->active)c->timer_bad|=guard(c);
}
static void target_quit(Context *c)
{
 if(!c->payload.target_quit)return;
 uint32_t bad=guard(c),before=c->payload.target_quit_calls;
 if(!bad)((void(*)(PayloadState *))(uintptr_t)c->payload.target_quit)(&c->payload);
 event(c,bad||c->payload.target_quit_calls!=before+1?"FAIL_TARGET_QUIT":"PASS_TARGET_QUIT",bad,c->payload.target_quit_calls);
 if(bad||c->payload.target_quit_calls!=before+1)c->failed|=4;
 c->payload.target_quit=0;
}
void resident_quit_work(Context *c)
{
 if(c->in_callback)return;
 c->in_callback=1;c->quit_seen++;
 event(c,"OS_CALLBACK",c->active,sr_get());
 stop_timer(c);
 if(c->active){event(c,"CALLBACK_MAP_GUARD",guard(c),c->payload.ticks);target_quit(c);}
 restore(c);event(c,"CALLBACK_CLEANED",c->failed,c->quit_seen);save(c);
 /* callback.S tail-calls finalize only after this returns to physical RAM. */
}
static int checkpoint(Context *c,const char *name)
{text(c,name);text(c,"\n");return save(c);}
static void init_data(Context *c)
{
 for(unsigned i=0;i<8192;i++)((volatile unsigned char *)c->ram)[i]=0;
 REG(c->ram)=8192;REG(c->ram+4)=REG(c->image+8192);synchronize(c->ram,8192);
}
static int payload(Context *c)
{
 uint32_t bad=guard(c);if(bad){event(c,"FAIL_BEFORE_PAYLOAD",bad,0);c->failed|=8;return 0;}
 uint32_t result=((uint32_t(*)(PayloadState *))(uintptr_t)0x00300200)(&c->payload);
 bad=guard(c);event(c,"PAYLOAD_RETURN",result,bad);
 event(c,"PAYLOAD_RESOURCE_DATA",c->payload.resource_sum,c->payload.data_seen);
 event(c,"PAYLOAD_BSS_HEAP",c->payload.bss_seen,c->payload.heap_ok);
 uint32_t first=REG(c->ram+8),last=REG(c->ram+8+4096);
 event(c,"PAYLOAD_RAM_ALIAS",first,last);
 event(c,"PAYLOAD_TIMER",c->payload.timer_during_payload,c->timer_bad);
 int ok=result==0x600d0001&&!bad&&c->payload.resource_sum==2080&&c->payload.data_seen==0x1234abcd&&
  !c->payload.bss_seen&&c->payload.heap_ok&&c->payload.timer_during_payload&&!c->timer_bad&&
  first==c->payload.calls&&last==c->payload.calls;
 if(!ok)c->failed|=16;
 return ok;
}
static int load_log(Context *c)
{
 int fd=r_open(c->log_path,1,0);
 if(fd<0){if(fd!=-1){c->io_error=fd;return -1;}
  int size=LOG_BYTES,rc=r_create(c->log_path,1,&size);if(rc<0){c->io_error=rc;return -1;}
  text(c,"FXPROBE2\nFormat=2\n");return save(c)?0:-1;
 }
 int size=r_size(fd),n=size==LOG_BYTES?r_read(fd,c->log,LOG_BYTES,0):-1,rc=r_close(fd);
 if(n!=LOG_BYTES||rc<0){c->io_error=-1010;return -1;}
 const char *magic="FXPROBE2\n";for(unsigned i=0;magic[i];i++)if(c->log[i]!=magic[i]){c->io_error=-1011;return -1;}
 c->log_used=LOG_BYTES;while(c->log_used&&c->log[c->log_used-1]==' ')c->log_used--;
 if(c->log_used>LOG_BYTES-1024){c->io_error=-1007;return -1;}return 1;
}
int resident_main(Context *c,int mode)
{
 resident_context=c;
 if(mode==0){target_quit(c);stop_timer(c);restore(c);checkpoint(c,"EXIT_MAIN_RETURN");return 0;}
 r_quit(resident_quit_entry);
 int previous=load_log(c);c->previous=previous;
 if(previous<0)return -1;
 if(previous){
  event(c,"REENTERED_NEW_STARTUP",REG(0xff000010),REG(0xff00001c));
  c->failed=has(c,"FAIL_");c->completed=has(c,"AUTO_DONE");
  checkpoint(c,has(c,"CALLBACK_CLEANED")?"CALLBACK_OBSERVED":"CALLBACK_NOT_OBSERVED");
  r_quit(resident_quit_entry);return 0;
 }
 event(c,"CONFIG_LOOPS_HOLD",c->loops,c->hold_ms);event(c,"IMAGE_BYTES_FNV",IMAGE_BYTES,c->image_hash);
 event(c,"CPU",REG(0xff000030),REG(0xff000044));event(c,"MMUCR_CCR",REG(0xff000010),REG(0xff00001c));
 unsigned char major=0,minor=0;unsigned short release=0,build=0;
 int version=r_version(&major,&minor,&release,&build);
 event(c,"OS_VERSION",((uint32_t)major<<24)|((uint32_t)minor<<16)|release,((uint32_t)build<<16)|(version&65535));
 uint32_t sp,vbr;__asm__ volatile("mov r15,%0":"=r"(sp));__asm__ volatile("stc vbr,%0":"=r"(vbr));event(c,"SP_VBR",sp,vbr);
 event(c,"RESIDENT_IMAGE",c->resident,c->image);event(c,"RAM_CONTEXT",c->ram,(uintptr_t)c);
 if(REG(0xff000030)!=0x10300b00||REG(0xff000044)!=0x2c00||(sp&0xe0000000)!=0x80000000){checkpoint(c,"SKIP_CPU_OR_STACK");return 0;}
 r_quit(resident_quit_entry);
 if(!checkpoint(c,"UNPIN_PENDING"))return -1;
 init_data(c);synchronize(c->image,IMAGE_BYTES);
 if(install(c,0,0)){
  r_sleep(c->hold_ms);event(c,"UNPIN_AFTER_SLEEP",guard(c),r_ticks());
  int fd=r_open(c->bin_path,1,0);unsigned word=0;int n=fd<0?fd:r_read(fd,&word,4,0);if(fd>=0)r_close(fd);
  event(c,"UNPIN_AFTER_BFILE",guard(c),n);
 }restore(c);if(!checkpoint(c,"UNPIN_DONE"))return -1;
 for(unsigned n=0;n<c->loops;n++){
  event(c,"CYCLE_PENDING",n,0);if(!save(c))break;
  init_data(c);c->timer_bad=0;
  if(!install(c,1,1)){restore(c);break;}
  c->timer_id=r_timer_install(0,resident_timer,80);
  int start=c->timer_id>0?r_timer_start(c->timer_id):-1;
  event(c,"TIMER_START",c->timer_id,start);
  if(c->timer_id<=0||start<0){c->failed|=32;text(c,"FAIL_TIMER_START\n");}
  int ok=payload(c);target_quit(c);stop_timer(c);restore(c);
  if(ok)c->completed++;
  event(c,ok?"PASS_CYCLE":"FAIL_CYCLE",n,c->completed);if(!save(c)||!ok)break;
 }
 event(c,"AUTO_DONE",c->completed,c->failed);if(!save(c))return -1;
 if(c->failed||c->completed!=c->loops){text(c,"FAIL_AUTO_INCOMPLETE\n");save(c);return 0;}
 /* Keep the module active while GetKey invokes the real OS menu. */
 if(!checkpoint(c,"MENU_PENDING"))return -1;
 init_data(c);c->timer_bad=0;
 if(!install(c,1,1)){restore(c);checkpoint(c,"FAIL_MENU_INSTALL");return 0;}
 c->timer_id=r_timer_install(0,resident_timer,80);if(c->timer_id>0)r_timer_start(c->timer_id);
 if(!payload(c)){target_quit(c);stop_timer(c);restore(c);save(c);return 0;}
 screen("Auto tests passed","MENU: switch app","Then reopen Probe2");
 event(c,"MENU_READY",guard(c),c->payload.ticks);if(!save(c)){target_quit(c);stop_timer(c);restore(c);return -1;}
 for(;;){
  int key=0;r_getkey(&key);uint32_t bad=guard(c);
  event(c,"GETKEY_RESUMED",key,bad);event(c,"TIMER_AFTER_GETKEY",c->payload.ticks,c->timer_bad);
  if(bad){c->failed|=64;text(c,"FAIL_MENU_MAPPING\n");}
  if(key==30002||key==30010||bad||c->io_error)break;
  c->menu_resumed++;save(c);
 }
 target_quit(c);stop_timer(c);restore(c);checkpoint(c,"MENU_RETURNED_TO_LOADER");return 2;
}
