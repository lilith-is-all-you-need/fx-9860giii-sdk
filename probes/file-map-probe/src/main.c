#include "probe.h"
static void screen(const char *a,const char *b)
{r_clear();r_print(0,0,(const unsigned char *)"File Map Probe 3",0);r_print(0,18,(const unsigned char *)a,0);r_print(0,32,(const unsigned char *)b,0);r_print(0,53,(const unsigned char *)"EXIT: return",0);r_display();}
static void wide(uint16_t *out,const char *s){while(*s)*out++=(unsigned char)*s++;*out=0;}
static int p1(void *p){return ((uintptr_t)p&0xe0000000u)==0x80000000u;}
static void release(Context *c)
{void *r=c->runner_alloc,*s=c->shadow_alloc;if(r)r_free(r);if(s)r_free(s);r_free(c);}
static void finalize(Context *c){r_quit(0);if(c->timer_id<=0)release(c);}
static void startup_report(const char *why)
{
 uint16_t path[32];wide(path,"\\\\fls0\\P3Start.txt");char b[512];const char *magic="FXP3START\n";
 int fd=r_open(path,1,0),rc;
 if(fd>=0){int n=r_read(fd,b,10,0),size=r_size(fd);r_close(fd);if(size!=512||n!=10)return;for(int i=0;i<10;i++)if(b[i]!=magic[i])return;}
 else {if(fd!=-1)return;int size=512;rc=r_create(path,1,&size);if(rc<0)return;}
 for(unsigned i=0;i<sizeof b;i++){b[i]=' ';}
 unsigned n=0;while(magic[n]){b[n]=magic[n];n++;}
 while(*why&&n<400){b[n++]=*why++;}
 b[n++]='\n';
 fd=r_open(path,2,0);if(fd<0)return;r_write(fd,b,sizeof b);r_close(fd);
}
static int config(Context *c)
{
 uint16_t path[32];wide(path,"\\\\fls0\\Probe3.cfg");char b[160];int fd=r_open(path,1,0);if(fd<0)return 0;
 int n=r_size(fd),got=n>0&&n<(int)sizeof b?r_read(fd,b,n,0):-1,closed=r_close(fd);if(got!=n||got<0||closed<0)return 0;
 int clean=0;for(int j=0;j<n;j++){if(b[j]=='\r'&&j+1<n&&b[j+1]=='\n')continue;b[clean++]=b[j];}n=clean;
 /* Fixed binary-independent ASCII envelope avoids ambiguous paths/options. */
 const char *head="FXPROBE3\nbytes=2094444\nfnv=";unsigned i=0;
 while(head[i]){if(i>=(unsigned)n||b[i]!=head[i])return 0;i++;}
 uint32_t h=0;for(int k=0;k<8;k++){if(i>=(unsigned)n)return 0;char ch=b[i++];unsigned d=ch>='0'&&ch<='9'?ch-'0':ch>='A'&&ch<='F'?ch-'A'+10:99;if(d>15)return 0;h=(h<<4)|d;}
 const char *tail="\nloops=2\nhold_ms=240\n";unsigned k=0;while(tail[k])if(i>=(unsigned)n||b[i++]!=tail[k++])return 0;
 if(i!=(unsigned)n)return 0;
 c->image_fnv=h;c->loops=2;c->hold_ms=240;return 1;
}
int main(void)
{
 Context *c=0;const char *why="Allocation failed";screen("Starting probe","Please wait");
 c=r_malloc(sizeof *c);if(!c)goto fail;if(!p1(c)){r_free(c);c=0;why="Heap is not P1";goto fail;}
 for(unsigned i=0;i<sizeof *c;i++)((unsigned char *)c)[i]=0;
 c->finalize=finalize;wide(c->log_path,"\\\\fls0\\Probe3.txt");wide(c->bin_path,"\\\\fls0\\Probe3.bin");wide(c->work_path,"\\\\fls0\\P3Work.tmp");
 if(!config(c)){why="Check Probe3.cfg";goto fail;}
 unsigned bytes=resident_end-resident_begin;c->runner_bytes=bytes;c->runner_alloc=r_malloc(bytes+31);c->shadow_alloc=r_malloc(4096+8191);
 if(!c->runner_alloc||!c->shadow_alloc){why="Not enough heap";goto fail;}
 if(!p1(c->runner_alloc)||!p1(c->shadow_alloc)){why="Heap is not P1";goto fail;}
 uintptr_t runner=((uintptr_t)c->runner_alloc+31)&~31u;c->resident=runner|0x20000000u;
 c->shadow=((uintptr_t)c->shadow_alloc+8191)&~8191u;
 for(unsigned i=0;i<bytes;i+=32){purge(runner+i);}
 BARRIER();
 for(unsigned i=0;i<bytes;i++)BYTE(c->resident+i)=resident_begin[i];
 if(resident_fixups[0]>1023){why="Bad fixup count";goto fail;}
 for(unsigned i=1;i<=resident_fixups[0];i++){
  uint32_t off=resident_fixups[i],v;if(off+4>bytes||(off&3)){why="Bad fixup offset";goto fail;}
  v=REG(c->resident+off);if(v<(uintptr_t)resident_begin||v>=(uintptr_t)resident_end){why="Bad fixup value";goto fail;}
  REG(c->resident+off)=v-(uintptr_t)resident_begin+c->resident;
 }BARRIER();
 int (*run)(Context *,int)=(int(*)(Context *,int))(c->resident+(uintptr_t)resident_main-(uintptr_t)resident_begin);
 int result=run(c,1);if(result==2){run(c,0);return 1;}
 /* MENU replacement uses resident callback.S; ordinary EXIT restores in run. */
 if(c->io_error)screen("Report I/O failed","Keep Probe3.txt");
 else if(c->previous)screen(c->failed||!c->auto_done?"Saved: NEED REVIEW":"Saved: SUCCESS","Send Probe3.txt back");
 else screen(c->failed?"Saved: NEED REVIEW":"Auto checks passed","Send Probe3.txt back");
 int key=0;while(key!=30002&&key!=30010)r_getkey(&key);
 run(c,0);return 1;
fail:
 if(c)release(c);
 startup_report(why);screen("Probe not started",why);
 {int key=0;while(key!=30002&&key!=30010)r_getkey(&key);}return 1;
}
