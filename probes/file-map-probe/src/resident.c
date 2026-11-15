#include "probe.h"
Context *resident_context=(Context *)(uintptr_t)1;
static void text(Context *c,const char *s)
{while(*s&&c->log_used<LOG_BYTES-2&&c->log_used-c->log_saved<BUFFER_BYTES)c->log[c->log_used++-c->log_saved]=*s++;if(*s)c->io_error=-1007;}
static void hex(Context *c,uint32_t x)
{for(int i=7;i>=0;i--){unsigned d=(x>>(i*4))&15;char b[2]={(char)(d<10?'0'+d:'A'+d-10),0};text(c,b);}}
static void event(Context *c,const char *s,uint32_t a,uint32_t b)
{text(c,s);text(c,"=");hex(c,a);text(c,",");hex(c,b);text(c,"\n");}
static uint32_t hash(const volatile unsigned char *p,unsigned n)
{uint32_t h=2166136261u;while(n--)h=(h^*p++)*16777619u;return h;}
static int prefix(const char *p,const char *s){while(*s)if(*p++!=*s++)return 0;return 1;}
static void screen(const char *a,const char *b)
{r_clear();r_print(0,0,(const unsigned char *)"File Map Probe 3",0);r_print(0,17,(const unsigned char *)a,0);r_print(0,31,(const unsigned char *)b,0);r_print(0,53,(const unsigned char *)"Probe3.txt / EXIT",0);r_display();}
static int save(Context *c)
{
 if(c->active||c->io_error)return 0;
 unsigned pending=c->log_used-c->log_saved;if(!pending)return 1;
 unsigned bytes=(pending+511)&~511u;if(bytes>LOG_BYTES-c->log_saved)bytes=LOG_BYTES-c->log_saved;
 for(unsigned i=pending;i<bytes;i++)c->log[i]=' ';
 int fd=r_open(c->log_path,2,0);if(fd<0){c->io_error=fd;return 0;}
 int seek=r_seek(fd,c->log_saved),n=seek<0?seek:r_write(fd,c->log,bytes),rc=r_close(fd);
 if(n!=(int)bytes||rc<0){c->io_error=n<0?n:rc<0?rc:-1001;return 0;}
 char tail[32];unsigned count=pending<32?pending:32;fd=r_open(c->log_path,1,0);if(fd<0){c->io_error=fd;return 0;}
 n=r_read(fd,tail,count,c->log_used-count);rc=r_close(fd);
 if(n!=(int)count||rc<0){c->io_error=-1002;return 0;}
 for(unsigned i=0;i<count;i++)if(tail[i]!=c->log[pending-count+i]){c->io_error=-1003;return 0;}
 char last=c->log[pending-1];c->log_saved=c->log_used&~1u;if(c->log_used&1)c->log[0]=last;return 1;
}
static int checkpoint(Context *c,const char *s){text(c,s);text(c,"\n");return save(c);}
static int load_log(Context *c)
{
 int fd=r_open(c->log_path,1,0);
 if(fd<0){
  if(fd!=-1){c->io_error=fd;return -1;}
  int size=LOG_BYTES,rc=r_create(c->log_path,1,&size);if(rc<0){c->io_error=rc;return -1;}
  fd=r_open(c->log_path,2,0);if(fd<0){c->io_error=fd;return -1;}
  for(unsigned i=0;i<BUFFER_BYTES;i++)c->log[i]=' ';
  for(unsigned i=0;i<LOG_BYTES;i+=BUFFER_BYTES)if(r_write(fd,c->log,BUFFER_BYTES)!=BUFFER_BYTES){c->io_error=-1010;break;}
  rc=r_close(fd);if(rc<0)c->io_error=rc;text(c,"FXPROBE3\nBuild=3.0\n");return save(c)?0:-1;
 }
 if(r_size(fd)!=LOG_BYTES){r_close(fd);c->io_error=-1011;return -1;}
 char line[96],last=0;unsigned used=0;
 for(unsigned off=0;off<LOG_BYTES;off+=BUFFER_BYTES){
  if(r_read(fd,c->log,BUFFER_BYTES,off)!=BUFFER_BYTES){c->io_error=-1012;break;}
  if(!off&&!prefix(c->log,"FXPROBE3\n")){c->io_error=-1013;break;}
  for(unsigned i=0;i<BUFFER_BYTES;i++){
   char ch=c->log[i];if(ch!=' '){c->log_used=off+i+1;last=ch;}
   if(ch=='\n'){line[used]=0;if(prefix(line,"AUTO_DONE="))c->auto_done=1;if(prefix(line,"FAIL_")||prefix(line,"SKIP_")||(prefix(line,"CALLBACK_RESTORED=")&&!prefix(line,"CALLBACK_RESTORED=00000000,")))c->failed=1;used=0;}
   else if(used<sizeof line-1)line[used++]=ch;
  }
 }
 int rc=r_close(fd);if(rc<0)c->io_error=rc;if(c->io_error)return -1;
 if(c->log_used>LOG_BYTES-1024){c->io_error=-1014;return -1;}
 c->log_saved=c->log_used&~1u;if(c->log_used&1)c->log[0]=last;return 1;
}
static uint8_t rom_read(void *unused,uint32_t a){(void)unused;return BYTE(a);}
static unsigned page_size(uint32_t d){unsigned x=((d>>6)&2)|((d>>4)&1);return x==0?1024:x==1?4096:x==2?65536:1048576;}
static int overlap(uint32_t a,uint32_t d)
{unsigned sz=page_size(d);uint32_t va=a&~(sz-1);return (uint64_t)va<0x00500000u&&(uint64_t)va+sz>BASE;}
static void flush_window(void)
{
 for(unsigned i=0;i<64;i++){uint32_t a=0xf6000000u+(i<<8),d=0xf7000000u+(i<<8);if(overlap(REG(a),REG(d))){REG(a)&=~0x100u;REG(d)&=~0x100u;}}
 for(unsigned i=0;i<4;i++){uint32_t a=0xf2000000u+(i<<8),d=0xf3000000u+(i<<8);if(overlap(REG(a),REG(d))){REG(a)&=~0x100u;REG(d)&=~0x100u;}}
 BARRIER();
}
static unsigned guard(Context *c)
{unsigned diff=0;for(unsigned i=0;i<512;i++)diff+=REG(c->os.pages+4*i)!=c->pages[i];return diff;}
static void snapshot(Context *c)
{for(unsigned i=0;i<512;i++)c->original[i]=REG(c->os.pages+i*4);c->old_cursor=REG(c->os.cursor);c->mmucr=REG(0xff000010);c->pteh=REG(0xff000000);c->ptel=REG(0xff000004);c->ptea=REG(0xff000034);}
static void install(Context *c)
{
 uint32_t sr=sr_get();sr_set(sr|0xf0);BARRIER();
 for(unsigned i=0;i<512;i++)REG(c->os.pages+i*4)=c->pages[i];
 REG(c->os.cursor)=0;flush_window();c->active=1;sr_set(sr);BARRIER();
}
static void restore(Context *c)
{
 if(!c->active)return;
 uint32_t sr=sr_get();sr_set(sr|0xf0);BARRIER();
 for(unsigned i=0;i<512;i++)REG(c->os.pages+i*4)=c->original[i];
 REG(c->os.cursor)=c->old_cursor;flush_window();
 REG(0xff000000)=c->pteh;REG(0xff000004)=c->ptel;REG(0xff000034)=c->ptea;REG(0xff000010)=c->mmucr;
 BARRIER();c->active=0;sr_set(sr);BARRIER();
}
static int address(Context *c,int fd,unsigned offset,uint32_t *out)
{return ((int(*)(int,int,uint32_t *))(uintptr_t)c->os.query)(fd,offset,out);}
static int scan_file(Context *c,int detailed)
{
 int fd=r_open(c->bin_path,1,0);if(fd<0){event(c,"FAIL_OPEN_BIN",fd,0);return 0;}
 if(r_size(fd)!=(int)IMAGE_BYTES){event(c,"FAIL_BIN_SIZE",r_size(fd),IMAGE_BYTES);r_close(fd);return 0;}
 uint32_t overall=2166136261u;unsigned differences=0,fragments=0,previous=0,ok=1;
 for(unsigned i=0;i<512;i++){
  unsigned off=i*4096,n=IMAGE_BYTES-off;if(n>4096)n=4096;
  uint32_t pa=0;int span=address(c,fd,off,&pa);uint32_t physical=pa&0x1fffffffu;
  if(span!=4096||(physical&4095)||physical<0x10000||physical>0x01fff000u){event(c,"FAIL_FILE_ADDRESS",i,pa);event(c,"ADDRESS_RESULT",span,off);ok=0;break;}
  if(r_read(fd,c->buffer,n,off)!=(int)n){event(c,"FAIL_FILE_READ",i,n);ok=0;break;}
  uint32_t a=hash(c->buffer,n),b=hash((const volatile unsigned char *)(uintptr_t)(physical|0xa0000000u),n);
  if(a!=b){event(c,"FAIL_PHYSICAL_COMPARE",i,physical);event(c,"HASHES",a,b);ok=0;break;}
  for(unsigned k=0;k<n;k++)overall=(overall^c->buffer[k])*16777619u;
  if(i&&physical!=previous+4096)fragments++;
  previous=physical;
  if(c->pages[i]&&c->pages[i]!=physical)differences++;
  c->pages[i]=physical;c->hashes[i]=a;
  if(detailed){event(c,"PAGE",i,physical);event(c,"HASH",a,n);}
  if(c->log_used-c->log_saved>1500&&!save(c)){ok=0;break;}
 }
 int closed=r_close(fd);if(closed<0)ok=0;
 event(c,"SCAN_CHANGED_FRAGMENTS",differences,fragments);event(c,"BIN_FNV",overall,c->image_fnv);
 if(overall!=c->image_fnv){event(c,"FAIL_BIN_HASH",overall,c->image_fnv);ok=0;}
 return ok&&save(c);
}
static int offsets(Context *c)
{
 static const unsigned values[]={0,1,4095,4096,4097,8191,8192,2094443};
 int fd=r_open(c->bin_path,1,0);if(fd<0)return 0;int good=1;
 for(unsigned i=0;i<sizeof values/sizeof values[0];i++){
  unsigned x=values[i];uint32_t a=0;int n=address(c,fd,x,&a);unsigned expected=4096-(x&4095);
  uint32_t pa=a&0x1fffffff;
  int ok=n==(int)expected&&(pa&4095)==(x&4095)&&pa>=0x10000&&pa<=0x01ffffffu;
  if(ok)ok=r_read(fd,c->buffer,1,x)==1&&BYTE(pa|0xa0000000u)==c->buffer[0];
  event(c,ok?"PASS_OFFSET":"FAIL_OFFSET",x,n);if(!ok)good=0;
 }r_close(fd);return good&&save(c);
}
static int edge_files(Context *c)
{
 static const char *const names[]={"\\\\fls0\\P3e4095.bin","\\\\fls0\\P3e4096.bin","\\\\fls0\\P3e4097.bin"};
 int good=1;
 for(unsigned k=0;k<3;k++){
  uint16_t path[32];unsigned j=0;do{path[j]=(unsigned char)names[k][j];}while(names[k][j++]);
  int fd=r_open(path,1,0),size=4095+k;if(fd<0)return 0;
  if(r_size(fd)!=size){r_close(fd);return 0;}
  for(unsigned off=0;off<(unsigned)size;){
   unsigned n=size-off;if(n>4096)n=4096;uint32_t address_value=0;
   int span=address(c,fd,off,&address_value);uint32_t pa=address_value&0x1fffffff;
   if(span!=4096||(pa&4095)||pa<0x10000||pa>0x01fff000u||r_read(fd,c->buffer,n,off)!=(int)n){good=0;break;}
   uint32_t a=hash(c->buffer,n),b=hash((const volatile unsigned char *)(uintptr_t)(pa|0xa0000000u),n);
   if(a!=b)good=0;
   event(c,a==b?"PASS_EDGE_FILE":"FAIL_EDGE_FILE",size,off);off+=n;
  }r_close(fd);
 }return good&&save(c);
}
static unsigned execute_pages(Context *c,unsigned seed)
{
 unsigned bad=0;
 for(unsigned k=0;k<512;k++){
  unsigned page=(k*73+seed)&511,n=IMAGE_BYTES-page*4096;if(n>4096)n=4096;
  if(hash((const volatile unsigned char *)(uintptr_t)(BASE+page*4096),n)!=c->hashes[page]){bad=page+1;break;}
  uint32_t result=((uint32_t(*)(void))(uintptr_t)(BASE+page*4096+32))();
  if(result!=(0x50670000u|page)){bad=page+1;break;}
 }
 return bad;
}
/* Query after all preceding log writes. No writes occur before install.
 * Execute paths hash their page before jumping; callbacks use checked_page. */
static int refresh_addresses(Context *c)
{
 int fd=r_open(c->bin_path,1,0);if(fd<0)return 0;int ok=r_size(fd)==(int)IMAGE_BYTES;unsigned changed=0;
 for(unsigned i=0;i<512&&ok;i++){
  uint32_t a=0;int span=address(c,fd,i*4096,&a);uint32_t pa=a&0x1fffffff;
  if(span!=4096||(pa&4095)||pa<0x10000||pa>0x01fff000u){ok=0;break;}
  changed+=pa!=c->pages[i];c->pages[i]=pa;
 }
 if(r_close(fd)<0)ok=0;
 event(c,"ADDRESS_REFRESH",ok,changed);return ok;
}
static int checked_page(Context *c,unsigned page)
{
 unsigned n=IMAGE_BYTES-page*4096;if(n>4096)n=4096;
 return hash((const volatile unsigned char *)(uintptr_t)(c->pages[page]|0xa0000000u),n)==c->hashes[page];
}
static int ready(Context *c,unsigned page)
{
 if(refresh_addresses(c)&&(page==512||checked_page(c,page)))return 1;
 c->failed|=64;checkpoint(c,"FAIL_ADDRESS_REFRESH");return 0;
}
static void timer_callback(void)
{
 Context *c=resident_context;c->ticks++;if(!c->active)return;
 if(c->file_busy||guard(c)){c->timer_skipped++;return;}
 uint32_t r=((uint32_t(*)(void))(uintptr_t)(BASE+511*4096+32))();c->timer_calls++;
 if(r!=0x506701ffu)c->timer_bad++;
}
static void stop_timer(Context *c)
{if(c->timer_id>0){int a=r_timer_stop(c->timer_id),b=r_timer_remove(c->timer_id);event(c,"TIMER_STOP",a,b);if(a<0||b<0)c->failed|=16;if(b>=0)c->timer_id=0;}}
static int work_file(Context *c)
{
 int fd=r_open(c->work_path,1,0),rc;const char *magic="FXPROBE3-WORK";
 if(fd>=0){int n=r_read(fd,c->buffer,16,0),size=r_size(fd);r_close(fd);if(size!=512||n!=16||!prefix((char *)c->buffer,magic))return 0;}
 else {if(fd!=-1)return 0;int n=512;rc=r_create(c->work_path,1,&n);if(rc<0)return 0;fd=r_open(c->work_path,2,0);if(fd<0)return 0;for(unsigned i=0;i<512;i++)c->buffer[i]=0;for(unsigned i=0;magic[i];i++)c->buffer[i]=magic[i];int n2=r_write(fd,c->buffer,512);rc=r_close(fd);if(n2!=512||rc<0)return 0;}
 return 1;
}
static int file_operation(Context *c)
{
 if(!checkpoint(c,"FILE_OPERATION_PENDING"))return 0;
 if(!ready(c,511))return 0;
 c->timer_id=r_timer_install(0,timer_callback,80);int started=c->timer_id>0?r_timer_start(c->timer_id):-1;
 if(started<0){stop_timer(c);return 0;}c->file_busy=1;snapshot(c);install(c);
 unsigned before=guard(c);int fd=r_open(c->work_path,3,0),n=-1,rc=-1;
 unsigned after_open=guard(c),after_read=0,after_write=0;
 if(fd>=0){n=r_read(fd,c->buffer,512,0);after_read=guard(c);r_seek(fd,32);c->buffer[0]=0x33;c->buffer[1]=0xa5;n=n==512?r_write(fd,c->buffer,2):-1;after_write=guard(c);rc=r_close(fd);}
 unsigned after_close=guard(c);r_sleep(c->hold_ms);restore(c);stop_timer(c);c->file_busy=0;
 event(c,"FILE_TIMER_CALLS_SKIPPED",c->timer_calls,c->timer_skipped);
 event(c,"MAP_BEFORE_OPEN",before,after_open);event(c,"MAP_AFTER_READ_WRITE",after_read,after_write);event(c,"MAP_AFTER_CLOSE",after_close,rc);
 if(n!=2||rc<0){event(c,"FAIL_WORK_IO",n,rc);return 0;}
 if(!save(c)||!scan_file(c,0)||!ready(c,512))return 0;
 snapshot(c);install(c);unsigned bad=execute_pages(c,17),g=guard(c);restore(c);
 event(c,bad||g?"FAIL_AFTER_BFILE":"PASS_AFTER_BFILE",bad,g);return !bad&&!g&&save(c);
}
void resident_quit_work(Context *c)
{
 if(c->in_callback)return;
 c->in_callback=1;c->quit_seen++;
 unsigned was_active=c->active;event(c,"OS_QUIT_CALLBACK",was_active,was_active?guard(c):0);stop_timer(c);restore(c);
 if(was_active){
  /* Bfile runs in the OS quit callback, never inside a TLB miss handler.
   * Re-query addresses after menu activity before executing the tiny target. */
  if(refresh_addresses(c)&&checked_page(c,470)&&BYTE(c->os.enabled)&&(REG(0xff000010)&1)){
   snapshot(c);install(c);uint32_t r=((uint32_t(*)(void))(uintptr_t)(BASE+470*4096+32))();restore(c);
   event(c,"TARGET_QUIT_RESULT",r,0);if(r!=0x506701d6)c->failed|=32;
  }else {c->failed|=32;text(c,"FAIL_QUIT_REFRESH\n");}
 }
 event(c,"CALLBACK_RESTORED",c->failed,c->quit_seen);save(c);
}
int resident_main(Context *c,int mode)
{
 resident_context=c;
 if(!mode){stop_timer(c);restore(c);checkpoint(c,"EXIT_REQUESTED");return 0;}
 r_quit(resident_quit_entry);
 int previous=load_log(c);c->previous=previous;if(previous<0)return -1;
 if(previous){event(c,"REENTERED",c->auto_done,c->failed);save(c);return 0;}
 unsigned char major=0,minor=0;unsigned short rel=0,build=0;r_version(&major,&minor,&rel,&build);
 event(c,"OS_VERSION",((uint32_t)major<<24)|((uint32_t)minor<<16)|rel,build);
 uint32_t sp;__asm__ volatile("mov r15,%0":"=r"(sp));event(c,"SP_RESIDENT",sp,c->resident);event(c,"CONTEXT_SHADOW",(uintptr_t)c,c->shadow);
 event(c,"MEMORY_BUDGET",sizeof *c,c->runner_bytes);
 if(REG(0xff000030)!=0x10300b00||REG(0xff000044)!=0x2c00||(sp&0xe0000000)!=0x80000000u){c->failed=1;checkpoint(c,"SKIP_CPU_OR_STACK");return 0;}
 int profile=fx_os_profile(rom_read,0,&c->os);event(c,"PROFILE_STATUS",profile,c->os.refill);
 if(profile){
  if(fx_rom(c->os.refill,0x72))event(c,"OBSERVED_REFILL_HASH",fx_fingerprint(rom_read,0,c->os.refill,0x72),c->os.refill);
  if(fx_rom(c->os.map,0x220)){event(c,"OBSERVED_MAP_HEAD",fx_fingerprint(rom_read,0,c->os.map,0x132),c->os.map);event(c,"OBSERVED_MAP_TAIL",fx_fingerprint(rom_read,0,c->os.map+0x13e,0xe2),0);}
  if(fx_rom(c->os.query,0x8a))event(c,"OBSERVED_QUERY_HASH",fx_fingerprint(rom_read,0,c->os.query,0x8a),c->os.query);
  c->failed=1;checkpoint(c,"SKIP_UNRECOGNIZED_OS");return 0;
 }
 event(c,"PAGE_TABLE_QUERY",c->os.pages,c->os.query);event(c,"CURSOR_ENABLED",c->os.cursor,BYTE(c->os.enabled));
 if(!(REG(0xff000010)&1)||!BYTE(c->os.enabled)||REG(c->os.cursor)>54){c->failed=1;checkpoint(c,"SKIP_MMU_STATE");return 0;}
 r_quit(resident_quit_entry);
 if(!checkpoint(c,"SCAN_PENDING")||!scan_file(c,1)||!offsets(c)||!edge_files(c)||!work_file(c)){c->failed|=1;checkpoint(c,"FAIL_PREFLIGHT");return 0;}
 for(unsigned loop=0;loop<c->loops;loop++){
  event(c,"MAP_CYCLE_PENDING",loop,0);if(!save(c))break;
  if(!ready(c,512))break;
  snapshot(c);install(c);unsigned bad=execute_pages(c,loop*47),g=guard(c);uint32_t cursor=REG(c->os.cursor);restore(c);
  event(c,bad||g?"FAIL_MAP_CYCLE":"PASS_MAP_CYCLE",bad,g);event(c,"REFILL_CURSOR",loop,cursor);
  if(bad||g){c->failed|=2;break;}if(!save(c))break;
 }
 if(!c->failed&&!c->io_error&&!file_operation(c))c->failed|=4;
 /* One patched RAM page; P1 and virtual cache index bits are both aligned. */
 if(!c->failed&&!c->io_error){
  if(!checkpoint(c,"SHADOW_PENDING"))return -1;
  if(!ready(c,0))return 0;
  for(unsigned i=0;i<4096;i+=32){purge(c->shadow+i);}
  BARRIER();
  for(unsigned i=0;i<4096;i++)BYTE((c->shadow|0x20000000u)+i)=BYTE(c->pages[0]|0xa0000000u|i);
  REG((c->shadow|0x20000000u)+40)=0x5067abcd;BARRIER();
  uint32_t old=c->pages[0];c->pages[0]=c->shadow&0x1fffffff;snapshot(c);install(c);
  for(unsigned i=0;i<4096;i+=32){invalidate(BASE+i);}
  BARRIER();
  uint32_t result=((uint32_t(*)(void))(uintptr_t)(BASE+32))();restore(c);c->pages[0]=old;
  event(c,result==0x5067abcdu?"PASS_SHADOW":"FAIL_SHADOW",result,c->shadow);if(result!=0x5067abcdu)c->failed|=8;save(c);
 }
 if(!c->failed&&!c->io_error){
  if(!checkpoint(c,"TIMER_PENDING"))return -1;
  if(!ready(c,511))return 0;
  snapshot(c);install(c);c->timer_id=r_timer_install(0,timer_callback,80);int started=c->timer_id>0?r_timer_start(c->timer_id):-1;
  r_sleep(c->hold_ms);unsigned g=guard(c);restore(c);stop_timer(c);
  event(c,"TIMER_RESULTS",c->ticks,c->timer_calls);event(c,"TIMER_SKIPPED_BAD",c->timer_skipped,c->timer_bad);event(c,"TIMER_START_GUARD",started,g);
  if(started<0||!c->timer_calls||c->timer_bad||g)c->failed|=16;
  save(c);
 }
 if(c->failed||c->io_error){checkpoint(c,"FAIL_AUTO_INCOMPLETE");return 0;}
 c->auto_done=1;event(c,"AUTO_DONE",512,c->failed);if(!save(c))return -1;
 if(!checkpoint(c,"MENU_PENDING"))return -1;
 if(!ready(c,512))return 0;
 snapshot(c);install(c);screen("Auto checks passed","MENU: switch app");
 /* No Bfile writes while a borrowed mapping is active. Checkpoint is above. */
 for(;;){int key=0;r_getkey(&key);unsigned g=guard(c);restore(c);event(c,"GETKEY_RETURNED",key,g);if(!save(c))break;
  if(key==30002||key==30010)break;
  if(!scan_file(c,0)||!ready(c,512)){c->failed|=64;break;}snapshot(c);install(c);
 }
 restore(c);checkpoint(c,"MENU_PHASE_RETURNED");return 2;
}
