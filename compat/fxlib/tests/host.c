/* SPDX-License-Identifier: MIT; actual core with deterministic device doubles. */
#include "fxlib.h"
#include "fxlib_platform.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>

static unsigned char vram[1024], screen[1024], pressed[256];
static uint32_t now;
static int menus,poweroffs,presents,file_calls,last_op,last_size,last_value,last_handle,file_result;
static const uint16_t *last_path;
static struct { uint32_t at; int key,type; } events[100];
static unsigned event_count,event_next;
void fxc_init(void) { }
unsigned char *fxc_vram(void) { return vram; }
void fxc_present(const unsigned char *pixels) { memcpy(screen,pixels,1024); presents++; }
void fxc_glyph(unsigned char c,unsigned char rows[7]) { memset(rows,c==' '?0:0xf8,7); }
uint32_t fxc_ticks(void) { return now; }
void fxc_sleep(int ms) { (void)ms; now=(now+1)%(24u*3600u*128u); }
int fxc_event(int *key)
{
    if(event_next==event_count || events[event_next].at>now) return 0;
    int type=events[event_next].type; *key=events[event_next++].key;
    pressed[*key]=type==1; return type;
}
int fxc_keydown(int key) { return pressed[key]; }
void fxc_menu(void) { menus++; }
void fxc_poweroff(void) { poweroffs++; }
int fxc_file(int op,const uint16_t *path,int h,void *data,int size,int value)
{
    (void)data; file_calls++; last_op=op; last_path=path; last_handle=h;
    last_size=size; last_value=value; return file_result;
}
static void reset(void)
{
    now=0; menus=poweroffs=presents=file_calls=0; event_count=event_next=0;
    memset(pressed,0,sizeof pressed); memset(screen,0,sizeof screen);
    fxlib_compat_init();
}
static void event(uint32_t at,int key,int type)
{ events[event_count].at=at; events[event_count].key=key; events[event_count++].type=type; }
static void drawing(void)
{
    reset();
    Bdisp_SetPoint_VRAM(0,0,1); assert(vram[0]==0x80 && screen[0]==0);
    Bdisp_SetPoint_DD(1,0,1); assert(vram[0]==0x80 && screen[0]==0x40);
    Bdisp_PutDisp_DD(); assert(screen[0]==0x80);
    Bdisp_AllClr_DD(); assert(vram[0]==0x80 && screen[0]==0);
    DISPBOX box={0,0,0,0}; Bdisp_PutDispArea_DD(&box); assert(screen[0]==0x80);
    Bdisp_AllClr_DDVRAM();
    Bdisp_DrawLineVRAM(0,0,127,63); assert(Bdisp_GetPoint_VRAM(0,0)); assert(Bdisp_GetPoint_VRAM(127,63));
    Bdisp_ClearLineVRAM(0,0,127,63); assert(!Bdisp_GetPoint_VRAM(127,63));
    Bdisp_AreaReverseVRAM(-10,-10,0,0); assert(vram[0]==0x80);
    Bdisp_SetPoint_VRAM(INT_MIN,INT_MAX,1); assert(vram[0]==0x80);
    const unsigned char bitmap[]={0xa0,0x80};
    DISPGRAPH g={0,0,{9,1,bitmap},IMB_WRITEMODIFY_NORMAL,IMB_WRITEKIND_OVER};
    Bdisp_WriteGraph_VRAM(&g); assert(vram[0]==0xa0 && vram[1]==0x80);
    g.WriteKind=IMB_WRITEKIND_XOR; Bdisp_WriteGraph_VRAM(&g); assert(vram[0]==0 && vram[1]==0);
    g.WriteKind=IMB_WRITEKIND_OR; Bdisp_WriteGraph_VRAM(&g); assert(vram[0]==0xa0);
    g.WriteModify=IMB_WRITEMODIFY_REVERSE; g.WriteKind=IMB_WRITEKIND_AND;
    Bdisp_WriteGraph_VRAM(&g); assert(vram[0]==0 && vram[1]==0);
    g.WriteKind=99; Bdisp_WriteGraph_DDVRAM(&g); assert(fxlib_compat_last_error()==FXLIB_ERR_UNSUPPORTED);
    assert(vram[0]==0 && screen[0]==0);
    fxlib_compat_clear_error(); g.WriteKind=1; g.WriteModify=1; g.x=-1;
    Bdisp_WriteGraph_DDVRAM(&g); assert(vram[0]==0x41 && screen[0]==0x41);
    unsigned char packed[3]={0xcc,0xcc,0xcc}; DISPBOX read={0,0,7,0};
    Bdisp_ReadArea_VRAM(&read,packed+1); assert(packed[0]==0xcc && packed[1]==0x41 && packed[2]==0xcc);
    read.right=128; Bdisp_ReadArea_VRAM(&read,packed); assert(packed[0]==0xcc);
    assert(fxlib_compat_last_error()==FXLIB_ERR_ARGUMENT);
    fxlib_compat_clear_error(); Bdisp_AllClr_VRAM(); locate(1,1); Print((const unsigned char *)"A");
    assert(vram[0]==0xf8); PrintRev((const unsigned char *)" "); assert(Bdisp_GetPoint_VRAM(6,0));
    PrintMini(20,20,(const unsigned char *)"A",MINI_OVER); assert(Bdisp_GetPoint_VRAM(20,20));
    PrintXY(0,0,(const unsigned char *)"\x80",0); assert(fxlib_compat_last_error()==FXLIB_ERR_UNSUPPORTED);
}
static int a,b,nested;
static void timer_a(void) { a++; }
static void timer_b(void) { b++; KillTimer(2); }
static void timer_nested(void) { nested++; Sleep(20); }
static void timing(void)
{
    reset(); a=b=nested=0;
    assert(SetTimer(1,10,timer_a)==0 && SetTimer(2,20,timer_b)==0);
    now=3; fxlib_compat_poll(); assert(a==1 && b==1);
    now=30; fxlib_compat_poll(); assert(a==2 && b==1); /* coalesced missed deadlines */
    KillTimer(1); assert(SetTimer(6,10,timer_a)<0); assert(SetTimer(1,0,timer_a)<0);
    now=24u*3600u*128u-2; SetTimer(5,20,timer_a); now=2; fxlib_compat_poll(); assert(a==3);
    KillTimer(5); now=10; SetTimer(3,8,timer_nested); now=12; fxlib_compat_poll(); assert(nested==1);
    KillTimer(3); int start=RTC_GetTicks(); Sleep(20); assert(RTC_Elapsed_ms(start,20)==1);
    assert(RTC_Elapsed_ms(-1,10)<0);
}
static void keyboard(void)
{
    reset(); unsigned int key=0; int col=99,row=99; short unused=4;
    assert(Bkey_GetKeyWait(&col,&row,1,0,1,&unused)==0 && col==0 && row==0 && unused==0);
    assert(Bkey_GetKeyWait(&col,&row,2,1,1,&unused)==2 && now==128);
    event(now,0x11,1); assert(IsKeyDown(KEY_CHAR_0)==1);
    assert(Bkey_GetKeyWait(&col,&row,1,0,1,&unused)==1 && col==7 && row==2); /* retained queued press */
    event(now,0x07,1); assert(Bkey_GetKeyWait(&col,&row,1,0,1,&unused)==1 && col==1 && row==1);
    reset(); event(0,0x84,1); event(1,0x15,1);
    assert(GetKey(&key)==0 && key==KEY_CTRL_EXE && menus==1);
    reset(); event(0,0x84,1); assert(Bkey_GetKeyWait(&col,&row,1,0,0,&unused)==1 && menus==0 && col==4 && row==9);
    reset(); event(0,0x71,1); event(0,0x61,1); assert(GetKey(&key)==1 && key=='A');
    reset(); event(0,0x81,1); event(0,0x84,1);
    assert(GetKey(&key)==0 && key==KEY_CTRL_SETUP && menus==0);
    reset(); event(0,0x81,1); event(0,0x07,1); event(1,0x74,1);
    assert(GetKey(&key)==0 && key==KEY_CTRL_EXIT && poweroffs==1);
    reset(); assert(GetKeyWait(2,0,1,&key)==KEYREP_TIMEREVENT);
    assert(fxlib_keycode_to_gint(KEY_CTRL_LEFT)==0x85);
    assert(fxlib_keycode_from_gint(0x24,0,0)==KEY_CHAR_PLUS);
    assert(fxlib_keycode_to_gint(9999)<0);
    assert(Bkey_GetKeyWait(NULL,&row,1,0,1,&unused)<0);
    reset(); for(int i=0;i<40;i++) event(0,0x11,1);
    IsKeyDown(KEY_CHAR_0); assert(fxlib_compat_last_error()==FXLIB_ERR_QUEUE_FULL);
    reset(); a=0; SetTimer(4,10,timer_a); event(10,0x15,1);
    GetKey(&key); assert(a>0); /* wait pumps timers */
}
static void files(void)
{
    reset(); const FONTCHARACTER path[]={'\\','\\','f','l','s','0','\\','x',0};
    char data[10]; file_result=12;
    assert(Bfile_OpenFile(path,_OPENMODE_READWRITE)==12 && last_op==FXC_OPEN && last_value==3 && last_path==path);
    assert(Bfile_ReadFile(12,data,10,4)==12 && last_op==FXC_READ && last_handle==12 && last_size==10 && last_value==4);
    Bfile_WriteFile(12,data,3); assert(last_op==FXC_WRITE && last_size==3);
    Bfile_SeekFile(12,4); assert(last_op==FXC_SEEK && last_value==4);
    Bfile_CreateFile(path,32); assert(last_op==FXC_CREATE && last_size==32);
    Bfile_CreateDirectory(path); assert(last_op==FXC_MKDIR);
    Bfile_DeleteDirectory(path); assert(last_op==FXC_REMOVE);
    Bfile_GetFileSize(12); assert(last_op==FXC_SIZE);
    Bfile_CloseFile(12); assert(last_op==FXC_CLOSE);
    int before=file_calls; assert(Bfile_ReadFile(12,NULL,1,0)<0 && file_calls==before);
    file_result=-8; assert(Bfile_OpenFile(path,1)==-8 && fxlib_compat_last_error()==-8);
    FONTCHARACTER wide[6]; unsigned char narrow[6];
    Bfile_StrToName_ncpy(wide,(const unsigned char *)"abc",6);
    assert(wide[0]=='a' && wide[3]==0 && wide[5]==0);
    Bfile_NameToStr_ncpy(narrow,wide,6); assert(!strcmp((const char *)narrow,"abc"));
}
int main(void)
{
    drawing(); timing(); keyboard(); files();
    puts("fxlib host semantics passed: display, text, keys, timing, file contracts");
    return 0;
}
