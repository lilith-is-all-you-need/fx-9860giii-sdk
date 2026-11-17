/* SPDX-License-Identifier: MIT; test declarations, never installed. */
#ifndef TEST_FAKE_GINT_H
#define TEST_FAKE_GINT_H
#include <stdint.h>
#include <stdbool.h>
typedef struct { int unused; } font_t;
typedef struct { int key,type; } key_event_t;
typedef struct { int (*function)(void *); void *argument; } gint_call_t;
#define GINT_CALL(function,argument) ((gint_call_t){(int (*)(void *))(function),(argument)})
enum { C_BLACK=3,KEYEV_NONE=0,KEYEV_DOWN=1,KEYEV_UP=2,HWFS=0,HWFS_FUGUE=2 };
enum { BFile_File=1,BFile_Folder=5 };
extern uint32_t *gint_vram;
extern int gint[1];
void gint_setrestart(int restart);
void dupdate(void);
font_t const *dfont(font_t const *font);
void dtext(int x,int y,int color,const char *text);
uint32_t rtc_ticks(void);
void sleep_ms(int milliseconds);
key_event_t pollevent(void);
int keydown(int key);
void gint_osmenu(void);
void gint_poweroff(bool show_logo);
int gint_world_switch(gint_call_t call);
int BFile_Open(const uint16_t *,int);
int BFile_Close(int);
int BFile_Read(int,void *,int,int);
int BFile_Write(int,const void *,int);
int BFile_Seek(int,int);
int BFile_Size(int);
int BFile_Create(const uint16_t *,int,int *);
int BFile_Remove(const uint16_t *);
#endif
