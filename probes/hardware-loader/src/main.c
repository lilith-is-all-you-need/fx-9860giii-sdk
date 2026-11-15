#include "probe.h"
static void show(const char *a,const char *b)
{
 r_clear();r_print(0,0,(const unsigned char *)"Loader Probe 2.1",0);
 r_print(0,15,(const unsigned char *)a,0);r_print(0,29,(const unsigned char *)b,0);
 r_print(0,52,(const unsigned char *)"EXIT: quit",0);r_display();
}
static void wide(uint16_t *out,const char *in){while(*in)*out++=(unsigned char)*in++;*out=0;}
static uintptr_t align(void *p,unsigned n){return ((uintptr_t)p+n-1)&~(uintptr_t)(n-1);}
static int p1(void *p){return ((uintptr_t)p&0xe0000000)==0x80000000;}
static int same(const char *a,const char *b){while(*a&&*a==*b){a++;b++;}return *a==*b;}
/* Preflight evidence lives on the physical OS stack; it needs no heap. */
typedef struct { char data[1024]; unsigned used; } Boot;
static void boot_text(Boot *b,const char *s)
{while(*s&&b->used<sizeof b->data)b->data[b->used++]=*s++;}
static void boot_hex(Boot *b,uint32_t n)
{for(int i=7;i>=0;i--){unsigned d=(n>>(i*4))&15;char s[2]={(char)(d<10?'0'+d:'A'+d-10),0};boot_text(b,s);}}
static void boot_event(Boot *b,const char *name,uint32_t bytes,uintptr_t address)
{boot_text(b,name);boot_text(b,"=");boot_hex(b,bytes);boot_text(b,",");boot_hex(b,address);boot_text(b,"\n");}
static int boot_save(Boot *b)
{
 uint16_t path[32];wide(path,"\\\\fls0\\P2Alloc.txt");
 int fd=r_open(path,1,0),rc;
 if(fd>=0){
  char magic[10];int size=r_size(fd),n=r_read(fd,magic,10,0);rc=r_close(fd);
  const char *expected="FXP2ALLOC\n";
  if(size!=sizeof b->data||n!=10||rc<0)return -1030;
  for(unsigned i=0;i<10;i++)if(magic[i]!=expected[i])return -1031;
 }else{
  if(fd!=-1)return fd;
  int size=sizeof b->data;rc=r_create(path,1,&size);if(rc<0)return rc;
 }
 fd=r_open(path,2,0);if(fd<0)return fd;
 int n=r_write(fd,b->data,sizeof b->data);rc=r_close(fd);
 if(n!=sizeof b->data||rc<0)return -1032;
 char tail[32];unsigned count=b->used<32?b->used:32;
 fd=r_open(path,1,0);if(fd<0)return fd;
 n=r_read(fd,tail,count,b->used-count);rc=r_close(fd);
 if(n!=(int)count||rc<0)return -1033;
 for(unsigned i=0;i<count;i++)if(tail[i]!=b->data[b->used-count+i])return -1034;
 return 0;
}
static int number(const char *s,unsigned base,uint32_t *out)
{
 uint32_t n=0;if(!*s)return 0;
 while(*s){unsigned d=*s>='0'&&*s<='9'?*s-'0':*s>='A'&&*s<='F'?*s-'A'+10:99;
  if(d>=base)return 0;
  if(base==16?n>0x0fffffffu:(n>429496729u||(n==429496729u&&d>5)))return 0;
  n=n*base+d;s++;}
 *out=n;return 1;
}
static int config(Context *c)
{
 uint16_t name[32];wide(name,"\\\\fls0\\Probe2.cfg");
 char data[256];int fd=r_open(name,1,0);if(fd<0)return 0;
 int size=r_size(fd),n=size>0&&size<255?r_read(fd,data,size,0):-1;r_close(fd);
 if(n!=size||n<0)return 0;
 data[n]=0;
 char *s=data;unsigned seen=0,line=0;
 while(*s){char *key=s;while(*s&&*s!='\n'&&*s!='\r')s++;if(*s){*s++=0;while(*s=='\r'||*s=='\n')s++;}
  if(!line++){if(!same(key,"FXPROBE2"))return 0;continue;}
  char *v=key;while(*v&&*v!='=')v++;if(!*v)return 0;*v++=0;
  uint32_t value;unsigned bit;
  if(same(key,"image_bytes")){bit=1;if(!number(v,10,&value)||value!=IMAGE_BYTES)return 0;}
  else if(same(key,"image_fnv")){bit=2;if(!number(v,16,&value))return 0;c->image_hash=value;}
  else if(same(key,"loops")){bit=4;if(!number(v,10,&value)||value<1||value>16)return 0;c->loops=value;}
  else if(same(key,"hold_ms")){bit=8;if(!number(v,10,&value)||value<160||value>2000)return 0;c->hold_ms=value;}
  else return 0;
  if(seen&bit)return 0;
  seen|=bit;
 }
 return seen==15;
}
static void release(Context *c)
{
 void *a[5];for(unsigned i=0;i<5;i++)a[i]=c->allocations[i];
 for(unsigned i=0;i<5;i++)if(a[i])r_free(a[i]);
 r_free(c);
}
/* Executed in the original image only after callback.S restored its mappings. */
static void finalize(Context *c)
{
 r_quit(0);
 /* A timer whose removal failed may still reference resident RAM. Retain it
  * for diagnosis rather than freeing live callback code. */
 if(c->timer_id<=0)release(c);
}
int main(void)
{
 Context *c=0;const char *problem="Not started";
 Boot boot;boot.used=0;
 for(unsigned i=0;i<sizeof boot.data;i++)boot.data[i]=' ';
 boot_text(&boot,"FXP2ALLOC\nBuild=2.1\n");
 show("Loading configuration","Please wait");
 c=r_malloc(sizeof *c);boot_event(&boot,"ALLOC_CONTEXT",sizeof *c,(uintptr_t)c);
 if(!c){problem="No heap: context";goto failed;}
 if(!p1(c)){r_free(c);c=0;problem="Unsupported OS heap";goto failed;}
 for(unsigned i=0;i<sizeof *c;i++)((unsigned char *)c)[i]=0;
 c->finalize=finalize;wide(c->log_path,"\\\\fls0\\Probe2.txt");wide(c->bin_path,"\\\\fls0\\Probe2.bin");
 if(!config(c)){problem="Check Probe2.cfg";goto failed;}
 unsigned bytes=(unsigned)(resident_end-resident_begin);
 /* The image and RAM share one 8 KiB alignment allowance. */
 unsigned pool_bytes=IMAGE_BYTES+8192+8191;
 c->allocations[1]=r_malloc(pool_bytes);
 boot_event(&boot,"ALLOC_IMAGE_RAM",pool_bytes,(uintptr_t)c->allocations[1]);
 if(!c->allocations[1]){problem="No heap: image/RAM";goto failed;}
 if(!p1(c->allocations[1])){problem="Pool address not P1";goto failed;}
 c->allocations[0]=r_malloc(bytes+32);
 boot_event(&boot,"ALLOC_RUNNER",bytes+32,(uintptr_t)c->allocations[0]);
 if(!c->allocations[0]){problem="No heap: runner";goto failed;}
 if(!p1(c->allocations[0])){problem="Runner address not P1";goto failed;}
 uintptr_t runner=align(c->allocations[0],32);c->resident=runner|0x20000000;
 /* Match virtual bits [12:5] for P1/P0 data-cache aliases (32 KiB / 4 way). */
 c->image=align(c->allocations[1],8192);c->ram=c->image+IMAGE_BYTES;
 boot_event(&boot,"IMAGE_RAM",c->image,c->ram);
 boot_event(&boot,"REQUEST_TOTAL",sizeof *c+pool_bytes+bytes+32,0);
 int fd=r_open(c->bin_path,1,0);if(fd<0){problem="Missing Probe2.bin";goto failed;}
 int size=r_size(fd),n=size==IMAGE_BYTES?r_read(fd,(void *)c->image,IMAGE_BYTES,0):-1,closed=r_close(fd);
 if(n!=IMAGE_BYTES||closed<0){problem="BIN read/size failed";goto failed;}
 uint32_t hash=2166136261u;for(unsigned i=0;i<IMAGE_BYTES;i++)hash=(hash^((const unsigned char *)c->image)[i])*16777619u;
 if(hash!=c->image_hash){problem="BIN checksum failed";goto failed;}
 for(unsigned i=0;i<bytes;i+=32)purge(runner+i);
 BARRIER();
 for(unsigned i=0;i<bytes;i++)((volatile unsigned char *)c->resident)[i]=resident_begin[i];
 if(resident_fixups[0]>1023){problem="Bad resident fixups";goto failed;}
 for(unsigned i=1;i<=resident_fixups[0];i++){
  uint32_t off=resident_fixups[i];if(off+4>bytes||(off&3)){problem="Bad resident offset";goto failed;}
  uint32_t v=REG(c->resident+off);
  if(v<(uintptr_t)resident_begin||v>=(uintptr_t)resident_end){problem="Bad resident pointer";goto failed;}
  REG(c->resident+off)=v-(uintptr_t)resident_begin+c->resident;
 }BARRIER();
 boot_text(&boot,"RESULT=READY\n");
 if(boot_save(&boot)<0){problem="Alloc log I/O failed";goto failed;}
 int (*run)(Context *,int)=(int(*)(Context *,int))(c->resident+(uintptr_t)resident_main-(uintptr_t)resident_begin);
 int result=run(c,1);
 if(result==2){run(c,0);return 1;}
 if(c->io_error)show("File write failed","Keep Probe2.txt");
 else if(c->previous)show(c->failed?"Saved: NEED REVIEW":"Saved: results ready","Send Probe2.txt back");
 else show(c->failed||c->completed!=c->loops?"Tests: NEED REVIEW":"Auto tests: SUCCESS","Send Probe2.txt back");
 int key=0;while(key!=30002&&key!=30010)r_getkey(&key);
 run(c,0);
 /* Resident callback owns release after OS has invoked it. */
 return 1;
failed:
 if(c)release(c);
 boot_text(&boot,"RESULT=FAILED\nDETAIL=");boot_text(&boot,problem);boot_text(&boot,"\n");
 int report=boot_save(&boot);
 show("Probe not run",problem);
 r_print(0,41,(const unsigned char *)(report<0?"Alloc log unavailable":"P2Alloc.txt saved"),0);r_display();
 {int key=0;while(key!=30002)r_getkey(&key);}
 return 1;
}
