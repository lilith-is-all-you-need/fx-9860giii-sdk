/* SPDX-License-Identifier: MIT
 * Source compatibility for the documented subset; no OS binary emulation. */
#include "fxlib.h"
#include "fxlib_platform.h"
#include <limits.h>
#include <stddef.h>
#include <string.h>

#define DAY_TICKS (24u*60u*60u*128u)
static union { uint32_t alignment[256]; unsigned char bytes[1024]; } display;
static int last_error, cursor_x=1, cursor_y=1;
static const char *last_function="";
static fxlib_error_handler_t error_handler;
static struct { void (*call)(void); uint32_t period, last; } timers[5];
static int dispatching;
static unsigned char keys[32];
static unsigned qfirst, qcount;
static int repeat_key, repeat_started, modifier_shift, modifier_alpha;
static uint32_t repeat_at, repeat_first=64, repeat_next=16;

int fxc_error(const char *name,int error)
{
    last_error=error; last_function=name;
    if(error_handler) error_handler(name,error);
    return error;
}
int fxlib_compat_last_error(void) { return last_error; }
const char *fxlib_compat_last_function(void) { return last_function; }
void fxlib_compat_clear_error(void) { last_error=0; last_function=""; }
void fxlib_compat_set_error_handler(fxlib_error_handler_t h) { error_handler=h; }
static uint32_t elapsed(uint32_t start)
{ uint32_t now=fxc_ticks(); return now>=start ? now-start : DAY_TICKS-start+now; }
static uint32_t ticks_ms(int milliseconds)
{ return (uint32_t)(((uint64_t)(unsigned)milliseconds*128u+999u)/1000u); }
void fxlib_compat_init(void)
{
    memset(timers,0,sizeof timers); memset(display.bytes,0,1024);
    dispatching=0; qfirst=qcount=0; repeat_key=0;
    modifier_shift=modifier_alpha=0; cursor_x=cursor_y=1;
    repeat_first=64; repeat_next=16; fxlib_compat_clear_error(); fxc_init();
    memset(fxc_vram(),0,1024);
}
void fxlib_compat_poll(void)
{
    if(dispatching) return;
    dispatching=1;
    for(int i=0;i<5;i++) {
        if(timers[i].call && elapsed(timers[i].last)>=timers[i].period) {
            void (*callback)(void)=timers[i].call;
            timers[i].last=fxc_ticks();
            callback(); /* Callback may replace or cancel any timer. */
        }
    }
    dispatching=0;
}
int SetTimer(int id,int ms,void (*callback)(void))
{
    if(id<1 || id>5 || ms<=0 || ms>=86400000 || !callback)
        return fxc_error("SetTimer",FXLIB_ERR_ARGUMENT);
    timers[id-1].period=ticks_ms(ms); timers[id-1].last=fxc_ticks();
    timers[id-1].call=callback; return 0;
}
int KillTimer(int id)
{
    if(id<1 || id>5) return fxc_error("KillTimer",FXLIB_ERR_ARGUMENT);
    timers[id-1].call=NULL; return 0;
}
void Sleep(int ms)
{
    if(ms<0 || ms>=86400000) { fxc_error("Sleep",FXLIB_ERR_ARGUMENT); return; }
    uint32_t start=fxc_ticks(), duration=ticks_ms(ms);
    do { fxlib_compat_poll(); if(elapsed(start)>=duration) break; fxc_sleep(2); } while(1);
}
int RTC_GetTicks(void) { return (int)fxc_ticks(); }
int RTC_Elapsed_ms(int start,int ms)
{
    if(start<0 || (unsigned)start>=DAY_TICKS || ms<0 || ms>=86400000)
        return fxc_error("RTC_Elapsed_ms",FXLIB_ERR_ARGUMENT);
    return elapsed((uint32_t)start)>=ticks_ms(ms);
}

static int getpixel(const unsigned char *buf,int x,int y)
{ return x>=0 && x<128 && y>=0 && y<64 ? !!(buf[y*16+x/8] & (0x80u>>(x&7))) : 0; }
static void putpixel(unsigned char *buf,int x,int y,int value)
{
    if(x<0 || x>=128 || y<0 || y>=64) return;
    unsigned char mask=(unsigned char)(0x80u>>(x&7));
    if(value) buf[y*16+x/8]|=mask; else buf[y*16+x/8]&=(unsigned char)~mask;
}
/* Inclusive rectangles. Clip before loops, including hostile integer inputs. */
static int box_valid(const DISPBOX *b)
{ return b && b->left<=b->right && b->top<=b->bottom; }
static void fill(unsigned char *buf,const DISPBOX *b,int reverse)
{
    int left=b->left<0 ? 0:b->left, right=b->right>127 ? 127:b->right;
    int top=b->top<0 ? 0:b->top, bottom=b->bottom>63 ? 63:b->bottom;
    for(int y=top;y<=bottom;y++) for(int x=left;x<=right;x++)
        putpixel(buf,x,y,reverse ? !getpixel(buf,x,y):0);
}
static void area(const DISPBOX *b,int targets)
{
    if(!box_valid(b)) { fxc_error("Bdisp_AreaClr",FXLIB_ERR_ARGUMENT); return; }
    if(targets&1) fill(fxc_vram(),b,0);
    if(targets&2) { fill(display.bytes,b,0); fxc_present(display.bytes); }
}
void Bdisp_AllClr_DD(void) { memset(display.bytes,0,1024); fxc_present(display.bytes); }
void Bdisp_AllClr_VRAM(void) { memset(fxc_vram(),0,1024); }
void Bdisp_AllClr_DDVRAM(void) { Bdisp_AllClr_VRAM(); Bdisp_AllClr_DD(); }
void Bdisp_AreaClr_DD(const DISPBOX *b) { area(b,2); }
void Bdisp_AreaClr_VRAM(const DISPBOX *b) { area(b,1); }
void Bdisp_AreaClr_DDVRAM(const DISPBOX *b) { area(b,3); }
void Bdisp_AreaReverseVRAM(int a,int b,int c,int d)
{
    DISPBOX box={a,b,c,d};
    if(!box_valid(&box)) { fxc_error("Bdisp_AreaReverseVRAM",FXLIB_ERR_ARGUMENT); return; }
    fill(fxc_vram(),&box,1);
}
void Bdisp_GetDisp_DD(unsigned char *out)
{ if(out) memcpy(out,display.bytes,1024); else fxc_error("Bdisp_GetDisp_DD",FXLIB_ERR_ARGUMENT); }
void Bdisp_GetDisp_VRAM(unsigned char *out)
{ if(out) memcpy(out,fxc_vram(),1024); else fxc_error("Bdisp_GetDisp_VRAM",FXLIB_ERR_ARGUMENT); }
void Bdisp_PutDisp_DD(void)
{ memcpy(display.bytes,fxc_vram(),1024); fxc_present(display.bytes); fxlib_compat_poll(); }
void Bdisp_PutDispArea_DD(const DISPBOX *b)
{
    if(!box_valid(b)) { fxc_error("Bdisp_PutDispArea_DD",FXLIB_ERR_ARGUMENT); return; }
    int left=b->left<0?0:b->left,right=b->right>127?127:b->right;
    int top=b->top<0?0:b->top,bottom=b->bottom>63?63:b->bottom;
    for(int y=top;y<=bottom;y++) for(int x=left;x<=right;x++)
        putpixel(display.bytes,x,y,getpixel(fxc_vram(),x,y));
    fxc_present(display.bytes); fxlib_compat_poll();
}
void Bdisp_SetPoint_DD(int x,int y,unsigned char p)
{ putpixel(display.bytes,x,y,p); fxc_present(display.bytes); }
void Bdisp_SetPoint_VRAM(int x,int y,unsigned char p) { putpixel(fxc_vram(),x,y,p); }
void Bdisp_SetPoint_DDVRAM(int x,int y,unsigned char p)
{ Bdisp_SetPoint_VRAM(x,y,p); Bdisp_SetPoint_DD(x,y,p); }
int Bdisp_GetPoint_VRAM(int x,int y) { return getpixel(fxc_vram(),x,y); }
unsigned char *GetVRAMAddress(void) { return fxc_vram(); }
static void graph(const DISPGRAPH *g,int targets)
{
    if(!g || !g->GraphData.pBitmap || g->GraphData.width<=0 || g->GraphData.height<=0 ||
       g->GraphData.width>16384 || g->GraphData.height>16384) {
        fxc_error("Bdisp_WriteGraph",FXLIB_ERR_ARGUMENT); return;
    }
    if((g->WriteModify!=1 && g->WriteModify!=2) || g->WriteKind<1 || g->WriteKind>4) {
        fxc_error("Bdisp_WriteGraph",FXLIB_ERR_UNSUPPORTED); return;
    }
    int stride=(g->GraphData.width+7)/8;
    for(int y=0;y<64;y++) for(int x=0;x<128;x++) {
        int64_t sx=(int64_t)x-g->x,sy=(int64_t)y-g->y;
        if(sx<0 || sy<0 || sx>=g->GraphData.width || sy>=g->GraphData.height) continue;
        int value=!!(g->GraphData.pBitmap[(size_t)sy*stride+(size_t)sx/8] & (0x80u>>(sx&7)));
        if(g->WriteModify==IMB_WRITEMODIFY_REVERSE) value=!value;
        for(int target=1;target<=2;target++) if(targets&target) {
            unsigned char *buf=target==1 ? fxc_vram():display.bytes;
            int old=getpixel(buf,x,y), next=value;
            if(g->WriteKind==IMB_WRITEKIND_OR) next=old|value;
            if(g->WriteKind==IMB_WRITEKIND_AND) next=old&value;
            if(g->WriteKind==IMB_WRITEKIND_XOR) next=old^value;
            putpixel(buf,x,y,next);
        }
    }
    if(targets&2) fxc_present(display.bytes);
}
void Bdisp_WriteGraph_DD(const DISPGRAPH *g) { graph(g,2); }
void Bdisp_WriteGraph_VRAM(const DISPGRAPH *g) { graph(g,1); }
void Bdisp_WriteGraph_DDVRAM(const DISPGRAPH *g) { graph(g,3); }
static void read_area(const unsigned char *buf,const DISPBOX *b,unsigned char *out)
{
    /* The legacy API has no output capacity; restrict to a screen rectangle. */
    if(!box_valid(b) || !out || b->left<0 || b->top<0 || b->right>127 || b->bottom>63) {
        fxc_error("Bdisp_ReadArea",FXLIB_ERR_ARGUMENT); return;
    }
    int w=b->right-b->left+1,h=b->bottom-b->top+1,stride=(w+7)/8;
    memset(out,0,(size_t)stride*h);
    for(int y=0;y<h;y++) for(int x=0;x<w;x++) if(getpixel(buf,b->left+x,b->top+y))
        out[y*stride+x/8]|=(unsigned char)(0x80u>>(x&7));
}
void Bdisp_ReadArea_DD(const DISPBOX *b,unsigned char *out) { read_area(display.bytes,b,out); }
void Bdisp_ReadArea_VRAM(const DISPBOX *b,unsigned char *out) { read_area(fxc_vram(),b,out); }
static void line(int x0,int y0,int x1,int y1,int value)
{
    /* Documented legacy coordinates are within the screen; reject rather than
       iterate billions of points or overflow Bresenham on malformed input. */
    if(x0<0 || x0>127 || x1<0 || x1>127 || y0<0 || y0>63 || y1<0 || y1>63) {
        fxc_error("Bdisp_LineVRAM",FXLIB_ERR_ARGUMENT); return;
    }
    int dx=x1>x0?x1-x0:x0-x1,sx=x0<x1?1:-1;
    int dy=y1>y0?y0-y1:y1-y0,sy=y0<y1?1:-1,err=dx+dy;
    for(;;) { putpixel(fxc_vram(),x0,y0,value); if(x0==x1 && y0==y1) break;
        int e2=2*err; if(e2>=dy) { err+=dy; x0+=sx; } if(e2<=dx) { err+=dx; y0+=sy; } }
}
void Bdisp_DrawLineVRAM(int a,int b,int c,int d) { line(a,b,c,d,1); }
void Bdisp_ClearLineVRAM(int a,int b,int c,int d) { line(a,b,c,d,0); }

static void glyph(int x,int y,unsigned char c,int reverse,int transparent,int mini)
{
    unsigned char rows[7];
    if(c<32 || c>126) { fxc_error("Print",FXLIB_ERR_UNSUPPORTED); c='?'; }
    fxc_glyph(c,rows);
    int w=mini?4:6,h=mini?6:8;
    for(int py=0;py<h;py++) for(int px=0;px<w;px++) {
        int bit=0;
        if(px<w-1 && py<h-1) {
            int gx=mini ? px*4/2:px,gy=mini ? py*6/4:py;
            bit=!!(rows[gy] & (0x80u>>gx));
        }
        if(reverse) bit=!bit;
        if(bit || !transparent) putpixel(fxc_vram(),x+px,y+py,bit);
    }
}
static int text(int x,int y,const unsigned char *s,int reverse,int transparent,int mini,int count)
{
    if(!s) { fxc_error("Print",FXLIB_ERR_ARGUMENT); return 0; }
    /* Off-screen text is clipped, including cursor advance. */
    int n=0,advance=mini?4:6;
    while((count<0 || n<count) && *s && x<128) {
        if(x>=-6 && y>=-8 && y<64) glyph(x,y,*s,reverse,transparent,mini);
        s++; n++; x+=advance;
    }
    return n;
}
void locate(int x,int y)
{
    if(x<1 || x>21 || y<1 || y>8) { fxc_error("locate",FXLIB_ERR_ARGUMENT); return; }
    cursor_x=x; cursor_y=y;
}
static void print_cursor(const unsigned char *s,int reverse,int count)
{ cursor_x+=text((cursor_x-1)*6,(cursor_y-1)*8,s,reverse,0,0,count); }
void Print(const unsigned char *s) { print_cursor(s,0,-1); }
void PrintRev(const unsigned char *s) { print_cursor(s,1,-1); }
void PrintC(const unsigned char *s) { print_cursor(s,0,1); }
void PrintRevC(const unsigned char *s) { print_cursor(s,1,1); }
static void print_line(const unsigned char *s,int last,int reverse)
{
    if(!s || last<1 || last>21) { fxc_error("PrintLine",FXLIB_ERR_ARGUMENT); return; }
    while(cursor_x<=last) { unsigned char c=*s?*s++:' ';
        glyph((cursor_x-1)*6,(cursor_y-1)*8,c,reverse,0,0); cursor_x++; }
}
void PrintLine(const unsigned char *s,int last) { print_line(s,last,0); }
void PrintRLine(const unsigned char *s,int last) { print_line(s,last,1); }
void PrintXY(int x,int y,const unsigned char *s,int reverse)
{
    if(reverse!=0 && reverse!=1) { fxc_error("PrintXY",FXLIB_ERR_ARGUMENT); return; }
    text(x,y,s,reverse,0,0,-1);
}
void PrintMini(int x,int y,const unsigned char *s,int mode)
{
    if(mode<MINI_OVER || mode>MINI_REVOR) { fxc_error("PrintMini",FXLIB_ERR_UNSUPPORTED); return; }
    text(x,y,s,(mode&2)!=0,(mode&1)!=0,1,-1);
}

/* Public logical key values, not a copy of the proprietary SDK key header. */
typedef struct { unsigned char matrix; int plain,shift,alpha; } key_mapping;
static const key_mapping mapping[]={
    {0x91,30009,0,0},{0x92,30010,0,0},{0x93,30011,0,0},
    {0x94,30012,0,0},{0x95,30013,0,0},{0x96,30014,0,0},
    {0x81,30006,0,0},{0x82,30008,0,0},{0x83,30016,30028,0},
    {0x84,30003,30037,0},{0x85,30020,0,0},{0x86,30018,30052,0},
    {0x71,30007,0,0},{0x72,0x8b,0x86,0xcd},{0x73,0xa8,0xb8,0xce},
    {0x74,30002,30029,0},{0x75,30023,30053,0},{0x76,30021,0,0},
    {0x61,30001,0x7f54,'A'},{0x62,0x95,0xb5,'B'},{0x63,0x85,0xa5,'C'},
    {0x64,0x81,0x91,'D'},{0x65,0x82,0x92,'E'},{0x66,0x83,0x93,'F'},
    {0x51,0xbb,0, 'G'},{0x52,30046,30026,'H'},{0x53,'(',0x96,'I'},
    {0x54,')',0x9b,'J'},{0x55,',',0,'K'},{0x56,0x0e,0,'L'},
    {0x41,'7',0,'M'},{0x42,'8',30050,'N'},{0x43,'9',30036,'O'},{0x44,30025,30033,0},
    {0x31,'4',0,'P'},{0x32,'5',0,'Q'},{0x33,'6',0,'R'},{0x34,0xa9,'{','S'},{0x35,0xb9,'}','T'},
    {0x21,'1',0x7f51,'U'},{0x22,'2',0x7f40,'V'},{0x23,'3',0,'W'},
    {0x24,0x89,'[','X'},{0x25,0x99,']','Y'},
    {0x11,'0',0x7f50,'Z'},{0x12,'.','=',' '},{0x13,0x0f,0xd0,'"'},
    {0x14,0x87,0xc0,0},{0x15,30004,0x0d,0},{0x07,30015,0,0}
};
int fxlib_keycode_to_gint(int code)
{
    for(unsigned i=0;i<sizeof mapping/sizeof *mapping;i++) if(mapping[i].plain==code) return mapping[i].matrix;
    return fxc_error("fxlib_keycode_to_gint",FXLIB_ERR_UNSUPPORTED);
}
int fxlib_keycode_from_gint(int code,int shift,int alpha)
{
    for(unsigned i=0;i<sizeof mapping/sizeof *mapping;i++) if(mapping[i].matrix==code) {
        if(shift && mapping[i].shift) return mapping[i].shift;
        if(alpha && mapping[i].alpha) return mapping[i].alpha;
        return mapping[i].plain;
    }
    return fxc_error("fxlib_keycode_from_gint",FXLIB_ERR_UNSUPPORTED);
}
static void scan(void)
{
    int type,key;
    while((type=fxc_event(&key))!=0) {
        if(type==1) {
            if(qcount==sizeof keys) fxc_error("keyboard queue",FXLIB_ERR_QUEUE_FULL);
            else { keys[(qfirst+qcount)%sizeof keys]=(unsigned char)key; qcount++; }
            repeat_key=key; repeat_at=fxc_ticks(); repeat_started=0;
        } else if(type==2 && key==repeat_key) repeat_key=0;
    }
}
static int next_key(int repeat_all)
{
    scan();
    if(qcount) { int key=keys[qfirst]; qfirst=(qfirst+1)%sizeof keys; qcount--; return key; }
    if(repeat_key && (repeat_all || repeat_key==0x85 || repeat_key==0x86 || repeat_key==0x75 || repeat_key==0x76)
       && fxc_keydown(repeat_key) && elapsed(repeat_at)>=(repeat_started?repeat_next:repeat_first)) {
        repeat_at=fxc_ticks(); repeat_started=1; return repeat_key;
    }
    return 0;
}
static int wait_key(int mode,int seconds,int menu,int logical,unsigned int *out)
{
    if(!out || mode<0 || mode>2 || seconds<0 || seconds>3600 || menu<0 || menu>1)
        return fxc_error("GetKeyWait",FXLIB_ERR_ARGUMENT);
    *out=0; uint32_t start=fxc_ticks();
    for(;;) {
        fxlib_compat_poll(); int raw=next_key(!logical);
        if(raw) {
            if(raw==0x84 && menu==0 && mode!=KEYWAIT_HALTOFF_TIMEROFF && (!logical || !modifier_shift)) {
                modifier_shift=modifier_alpha=0; fxc_menu(); fxc_present(display.bytes); continue;
            }
            if(!logical) { *out=(unsigned int)raw; return KEYREP_KEYEVENT; }
            if(raw==0x81) { modifier_shift=!modifier_shift; continue; }
            if(raw==0x71) { modifier_alpha=!modifier_alpha; continue; }
            if(raw==0x07 && modifier_shift) {
                modifier_shift=modifier_alpha=0; fxc_poweroff(); fxc_present(display.bytes); continue;
            }
            int code=fxlib_keycode_from_gint(raw,modifier_shift,modifier_alpha);
            modifier_shift=modifier_alpha=0;
            if(code<0) return code;
            *out=(unsigned int)code; return KEYREP_KEYEVENT;
        }
        if(mode==KEYWAIT_HALTOFF_TIMEROFF) return KEYREP_NOEVENT;
        if(mode==KEYWAIT_HALTON_TIMERON && elapsed(start)>=(unsigned)seconds*128u) return KEYREP_TIMEREVENT;
        fxc_sleep(2);
    }
}
int GetKey(unsigned int *key)
{
    Bdisp_PutDisp_DD();
    int result=wait_key(KEYWAIT_HALTON_TIMEROFF,0,0,1,key);
    return result<0 ? result : (*key<30000 ? 1:0);
}
int GetKeyWait(int mode,int seconds,int menu,unsigned int *key) { return wait_key(mode,seconds,menu,1,key); }
int Bkey_GetKeyWait(int *column,int *row,int mode,int seconds,int menu,short *unused)
{
    if(!column || !row) return fxc_error("Bkey_GetKeyWait",FXLIB_ERR_ARGUMENT);
    *column=*row=0; if(unused) *unused=0;
    unsigned int key; int result=wait_key(mode,seconds,menu,0,&key);
    if(result==KEYREP_KEYEVENT) { *column=8-(key&15); *row=(key>>4)+1; }
    return result;
}
int IsKeyDown(int key)
{
    fxlib_compat_poll(); scan(); int matrix=fxlib_keycode_to_gint(key);
    return matrix<0 ? matrix : !!fxc_keydown(matrix);
}
int IsKeyUp(int key) { int down=IsKeyDown(key); return down<0?down:!down; }
void Bkey_Set_RepeatTime(long first,long next)
{
    /* Legacy repeat parameters are 25-ms units. */
    if(first<1 || next<1 || first>3600 || next>3600) { fxc_error("Bkey_Set_RepeatTime",FXLIB_ERR_ARGUMENT); return; }
    repeat_first=ticks_ms((int)first*25); repeat_next=ticks_ms((int)next*25);
}
void Bkey_Get_RepeatTime(long *first,long *next)
{
    if(!first || !next) { fxc_error("Bkey_Get_RepeatTime",FXLIB_ERR_ARGUMENT); return; }
    *first=(long)(repeat_first*1000u/128u/25u); *next=(long)(repeat_next*1000u/128u/25u);
}
void Bkey_Set_RepeatTime_Default(void) { repeat_first=64; repeat_next=16; }

static int file(int op,const FONTCHARACTER *path,int handle,void *data,int size,int value,const char *name)
{
    int result=fxc_file(op,path,handle,data,size,value);
    return result<0 ? fxc_error(name,result):result;
}
int Bfile_OpenFile(const FONTCHARACTER *path,int mode)
{
    if(!path || (mode!=1 && mode!=2 && mode!=3 && mode!=0x81 && mode!=0x83))
        return fxc_error("Bfile_OpenFile",FXLIB_ERR_ARGUMENT);
    return file(FXC_OPEN,path,0,NULL,0,mode,"Bfile_OpenFile");
}
int Bfile_CloseFile(int h) { return file(FXC_CLOSE,NULL,h,NULL,0,0,"Bfile_CloseFile"); }
int Bfile_ReadFile(int h,void *data,int size,int position)
{
    if((!data && size) || size<0 || position< -1) return fxc_error("Bfile_ReadFile",FXLIB_ERR_ARGUMENT);
    return file(FXC_READ,NULL,h,data,size,position,"Bfile_ReadFile");
}
int Bfile_WriteFile(int h,const void *data,int size)
{
    if((!data && size) || size<0) return fxc_error("Bfile_WriteFile",FXLIB_ERR_ARGUMENT);
    return file(FXC_WRITE,NULL,h,(void *)data,size,0,"Bfile_WriteFile");
}
int Bfile_SeekFile(int h,int position)
{
    if(position<0) return fxc_error("Bfile_SeekFile",FXLIB_ERR_ARGUMENT);
    return file(FXC_SEEK,NULL,h,NULL,0,position,"Bfile_SeekFile");
}
int Bfile_GetFileSize(int h) { return file(FXC_SIZE,NULL,h,NULL,0,0,"Bfile_GetFileSize"); }
int Bfile_CreateFile(const FONTCHARACTER *path,int size)
{
    if(!path || size<0) return fxc_error("Bfile_CreateFile",FXLIB_ERR_ARGUMENT);
    return file(FXC_CREATE,path,0,NULL,size,0,"Bfile_CreateFile");
}
int Bfile_DeleteFile(const FONTCHARACTER *path)
{
    if(!path) return fxc_error("Bfile_DeleteFile",FXLIB_ERR_ARGUMENT);
    return file(FXC_REMOVE,path,0,NULL,0,0,"Bfile_DeleteFile");
}
int Bfile_CreateDirectory(const FONTCHARACTER *path)
{
    if(!path) return fxc_error("Bfile_CreateDirectory",FXLIB_ERR_ARGUMENT);
    return file(FXC_MKDIR,path,0,NULL,0,0,"Bfile_CreateDirectory");
}
int Bfile_DeleteDirectory(const FONTCHARACTER *path) { return Bfile_DeleteFile(path); }
void Bfile_StrToName_ncpy(FONTCHARACTER *dst,const unsigned char *src,int length)
{
    if(!dst || !src || length<0) { fxc_error("Bfile_StrToName_ncpy",FXLIB_ERR_ARGUMENT); return; }
    int ended=0; for(int i=0;i<length;i++) { unsigned char c=ended?0:*src++;
        if(c==0) ended=1;
        if(c>127) { fxc_error("Bfile_StrToName_ncpy",FXLIB_ERR_UNSUPPORTED); dst[i]=0; return; }
        dst[i]=c;
    }
}
void Bfile_NameToStr_ncpy(unsigned char *dst,const FONTCHARACTER *src,int length)
{
    if(!dst || !src || length<0) { fxc_error("Bfile_NameToStr_ncpy",FXLIB_ERR_ARGUMENT); return; }
    int ended=0; for(int i=0;i<length;i++) { uint16_t c=ended?0:*src++;
        if(c==0 || c==0xffff) { ended=1; c=0; }
        if(c>127) { fxc_error("Bfile_NameToStr_ncpy",FXLIB_ERR_UNSUPPORTED); dst[i]=0; return; }
        dst[i]=(unsigned char)c;
    }
}
