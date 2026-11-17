/* SPDX-License-Identifier: MIT; private backend contract, not a legacy API. */
#ifndef FXSTUDIO_FXLIB_PLATFORM_H
#define FXSTUDIO_FXLIB_PLATFORM_H
#include <stdint.h>
void fxc_init(void);
unsigned char *fxc_vram(void);
void fxc_present(const unsigned char *pixels);
void fxc_glyph(unsigned char character,unsigned char rows[7]);
uint32_t fxc_ticks(void);
void fxc_sleep(int milliseconds);
/* 0=no event, 1=press, 2=release; codes use gint's physical matrix. */
int fxc_event(int *key);
int fxc_keydown(int key);
void fxc_menu(void);
void fxc_poweroff(void);
enum { FXC_OPEN, FXC_CLOSE, FXC_READ, FXC_WRITE, FXC_SEEK, FXC_SIZE,
       FXC_CREATE, FXC_REMOVE, FXC_MKDIR };
int fxc_file(int operation,const uint16_t *path,int handle,void *data,int size,int value);
int fxc_error(const char *function,int error);
#endif
