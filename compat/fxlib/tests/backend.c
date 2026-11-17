/* SPDX-License-Identifier: MIT; runs the actual gint backend against call spies. */
#include "fake_gint.h"
#include "fxlib_platform.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint32_t buffer[256];
uint32_t *gint_vram=buffer;
int gint[1]={HWFS_FUGUE};
static int os_world,world_calls,operations,restart_flag,last_size,last_mode;
static const uint16_t *last_path;
static const font_t *current_font;
void gint_setrestart(int restart) { restart_flag=restart; }
void dupdate(void) { }
font_t const *dfont(font_t const *font) { const font_t *old=current_font; current_font=font; return old; }
void dtext(int x,int y,int color,const char *text)
{ (void)x;(void)y;(void)color;(void)text; ((unsigned char *)gint_vram)[0]=0xf8; }
uint32_t rtc_ticks(void) { return 42; }
void sleep_ms(int milliseconds) { assert(milliseconds>0); }
key_event_t pollevent(void) { return (key_event_t){0,KEYEV_NONE}; }
int keydown(int key) { return key==0x15; }
void gint_osmenu(void) { }
void gint_poweroff(bool show_logo) { assert(show_logo); }
int gint_world_switch(gint_call_t call)
{
    assert(!os_world); os_world=1; world_calls++;
    int result=call.function(call.argument);
    os_world=0; return result;
}
static int checked(void) { assert(os_world); operations++; return 17; }
int BFile_Open(const uint16_t *path,int mode) { last_path=path;last_mode=mode;return checked(); }
int BFile_Close(int h) { assert(h==7);return checked(); }
int BFile_Read(int h,void *p,int n,int position) { assert(h==7 && p && position==2);last_size=n;return checked(); }
int BFile_Write(int h,const void *p,int n) { assert(h==7 && p);last_size=n;return checked(); }
int BFile_Seek(int h,int offset) { assert(h==7 && offset==2);return checked(); }
int BFile_Size(int h) { assert(h==7);return checked(); }
int BFile_Create(const uint16_t *path,int type,int *size)
{ last_path=path;last_mode=type;last_size=size?*size:-1;return checked(); }
int BFile_Remove(const uint16_t *path) { last_path=path;return checked(); }
int main(void)
{
    const uint16_t path[]={'x',0}; unsigned char data[8]={0};
    fxc_init(); assert(restart_flag==1);
    for(int op=FXC_OPEN;op<=FXC_MKDIR;op++) {
        assert(fxc_file(op,path,7,data,8,2)==17);
        assert(!os_world && world_calls==op+1 && operations==op+1);
    }
    assert(last_path==path && last_mode==BFile_Folder && last_size==-1);
    gint[HWFS]=0; assert(fxc_file(FXC_WRITE,path,7,data,3,0)==-1001);
    assert(world_calls==9 && operations==9);
    gint[HWFS]=HWFS_FUGUE;
    assert(fxc_file(FXC_WRITE,path,7,data,3,0)==17 && last_size==3);
    unsigned char rows[7]; font_t before={0}; current_font=&before;
    fxc_glyph('A',rows); assert(rows[0]==0xf8 && current_font==&before && gint_vram==buffer);
    uint32_t other[256]={0}; fxc_present((const unsigned char *)other); assert(gint_vram==buffer);
    assert(fxc_ticks()==42 && fxc_keydown(0x15)==1);
    puts("fxlib gint backend passed: world-switch isolation and display state restoration");
    return 0;
}
