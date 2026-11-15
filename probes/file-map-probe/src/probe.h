#ifndef FX_FILE_PROBE_H
#define FX_FILE_PROBE_H
#include <stdint.h>
#include <stddef.h>
/* Build service copies project sources; these two small headers are vendored
 * into this project by the preparation script, with equality checked in tests. */
#include "os-map-profile.h"
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define BYTE(a) (*(volatile uint8_t *)(uintptr_t)(a))
#define BARRIER() __asm__ volatile(".word 0x00ab\nnop\nnop\nnop\nnop\nnop\nnop\nnop\nnop":::"memory")
#define LOG_BYTES 65536
#define BUFFER_BYTES 2048
#define IMAGE_BYTES 2094444u
#define BASE 0x00300000u
static inline uint32_t sr_get(void){uint32_t x;__asm__ volatile("stc sr,%0":"=r"(x));return x;}
static inline void sr_set(uint32_t x){__asm__ volatile("ldc %0,sr"::"r"(x):"memory");}
static inline void purge(uintptr_t x){__asm__ volatile("ocbp @%0"::"r"(x):"memory");}
static inline void invalidate(uintptr_t x){__asm__ volatile(".word 0x00e3"::"z"(x):"memory");}
typedef struct Context Context;
struct Context {
 void (*finalize)(Context *);
 void *runner_alloc,*shadow_alloc;
 uintptr_t resident,shadow;
 FxOsMapProfile os;
 uint32_t pages[512],original[512],hashes[512];
 uint32_t image_fnv,loops,hold_ms,old_cursor,mmucr,pteh,ptel,ptea,runner_bytes;
 unsigned log_used,log_saved,failed,active,previous,in_callback,auto_done;
 int io_error,timer_id;
 volatile uint32_t ticks,timer_calls,timer_skipped,timer_bad,quit_seen,file_busy;
 uint16_t log_path[32],bin_path[32],work_path[32];
 char log[BUFFER_BYTES];
 unsigned char buffer[4096];
};
extern const unsigned char resident_begin[],resident_end[];
extern const uint32_t resident_fixups[];
extern Context *resident_context;
int resident_main(Context *,int);
void resident_quit_entry(void);
void resident_quit_work(Context *);
void r_clear(void);void r_print(int,int,const unsigned char *,int);void r_display(void);
int r_getkey(int *);void r_quit(void (*)(void));void *r_malloc(unsigned);void r_free(void *);
int r_version(unsigned char *,unsigned char *,unsigned short *,unsigned short *);
int r_open(const uint16_t *,int,int);int r_close(int);int r_size(int);int r_read(int,void *,int,int);
int r_seek(int,int);int r_create(const uint16_t *,int,int *);int r_write(int,const void *,int);
int r_ticks(void);void r_sleep(int);int r_timer_install(int,void (*)(void),int);
int r_timer_start(int);int r_timer_stop(int);int r_timer_remove(int);
#endif
