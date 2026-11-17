/* SPDX-License-Identifier: MIT */
#include <gint/display.h>
#include <gint/keyboard.h>
#include <gint/clock.h>
#include <gint/rtc.h>
#include <gint/gint.h>
#include <gint/bfile.h>
#include <gint/hardware.h>
#include "fxlib_platform.h"
#include <string.h>

static uint32_t glyph_buffer[256];
void fxc_init(void) { gint_setrestart(1); }
unsigned char *fxc_vram(void) { return (unsigned char *)gint_vram; }
void fxc_present(const unsigned char *pixels)
{
    uint32_t *saved=gint_vram;
    gint_vram=(uint32_t *)pixels; dupdate(); gint_vram=saved;
}
void fxc_glyph(unsigned char c,unsigned char rows[7])
{
    uint32_t *saved=gint_vram;
    gint_vram=glyph_buffer; memset(glyph_buffer,0,sizeof glyph_buffer);
    font_t const *saved_font=dfont(NULL);
    char text[2]={(char)c,0}; dtext(0,0,C_BLACK,text);
    for(int y=0;y<7;y++) rows[y]=((unsigned char *)glyph_buffer)[y*16];
    dfont(saved_font); gint_vram=saved;
}
uint32_t fxc_ticks(void) { return rtc_ticks(); }
void fxc_sleep(int milliseconds) { sleep_ms(milliseconds); }
int fxc_event(int *key)
{
    for(;;) {
        key_event_t event=pollevent(); *key=event.key;
        if(event.type==KEYEV_NONE) return 0;
        if(event.type==KEYEV_DOWN) return 1;
        if(event.type==KEYEV_UP) return 2;
    }
}
int fxc_keydown(int key) { return keydown(key); }
void fxc_menu(void) { gint_osmenu(); }
void fxc_poweroff(void) { gint_poweroff(true); }

typedef struct { int op; const uint16_t *path; int handle; void *data; int size,value; } file_request;
static int file_os(file_request *r)
{
    switch(r->op) {
    case FXC_OPEN: return BFile_Open(r->path,r->value);
    case FXC_CLOSE: return BFile_Close(r->handle);
    case FXC_READ: return BFile_Read(r->handle,r->data,r->size,r->value);
    case FXC_WRITE: return BFile_Write(r->handle,r->data,r->size);
    case FXC_SEEK: return BFile_Seek(r->handle,r->value);
    case FXC_SIZE: return BFile_Size(r->handle);
    case FXC_CREATE: return BFile_Create(r->path,BFile_File,&r->size);
    case FXC_REMOVE: return BFile_Remove(r->path);
    case FXC_MKDIR: return BFile_Create(r->path,BFile_Folder,NULL);
    default: return -1001;
    }
}
int fxc_file(int op,const uint16_t *path,int handle,void *data,int size,int value)
{
    /* GIII/Fugue only: CASIOWIN has incompatible seek/read/write semantics.
       Reject it explicitly, including potentially unsafe odd-sized writes. */
    if(gint[HWFS]!=HWFS_FUGUE) return -1001;
    file_request request={op,path,handle,data,size,value};
    return gint_world_switch(GINT_CALL(file_os,(void *)&request));
}
