#ifndef LOADER_PROBE_H
#define LOADER_PROBE_H
#include <stdint.h>
#include <stddef.h>
#define LOG_BYTES 16384
#define IMAGE_BYTES 16384
#define MAP_COUNT 6
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define BARRIER() __asm__ volatile(".word 0x00ab\nnop\nnop\nnop\nnop\nnop\nnop\nnop\nnop":::"memory")
static inline uint32_t sr_get(void){uint32_t x;__asm__ volatile("stc sr,%0":"=r"(x));return x;}
static inline void sr_set(uint32_t x){__asm__ volatile("ldc %0,sr"::"r"(x):"memory");}
static inline void purge(uintptr_t x){__asm__ volatile("ocbp @%0"::"r"(x):"memory");}
static inline void invalidate(uintptr_t x){__asm__ volatile(".word 0x00e3"::"z"(x):"memory");}
typedef struct { uint32_t addr,data,ext; } Entry;
typedef struct Context Context;
typedef struct {
 volatile uint32_t ticks, calls, resource_sum, data_seen, bss_seen, heap_ok, timer_during_payload;
 uint32_t target_quit, target_quit_calls;
} PayloadState;
struct Context {
 void (*finalize)(Context *); /* callback.S relies on offset zero */
 void *allocations[5];
 uintptr_t resident, image, ram;
 unsigned loops, hold_ms, log_used;
 int io_error, previous, active, pinned, failed, timer_id, in_callback;
 uint32_t original_mmucr,pteh,ptel,ptea;
 Entry old[64]; uint8_t touched[64];
 unsigned slot[MAP_COUNT], reserve;
 uint32_t expected[MAP_COUNT],image_hash,completed,menu_resumed,quit_seen,image_va,ram_va;
 volatile uint32_t timer_bad;
 PayloadState payload;
 uint16_t log_path[32], bin_path[32];
 char log[LOG_BYTES];
};
extern const unsigned char resident_begin[],resident_end[];
extern const uint32_t resident_fixups[];
extern Context *resident_context;
void resident_quit_entry(void);
void resident_quit_work(Context *);
void resident_timer(void);
int resident_main(Context *,int);
void r_clear(void);
void r_print(int,int,const unsigned char *,int);
void r_display(void);
int r_getkey(int *);
void r_quit(void (*)(void));
void *r_malloc(unsigned);
void r_free(void *);
int r_version(unsigned char *,unsigned char *,unsigned short *,unsigned short *);
int r_open(const uint16_t *,int,int);
int r_close(int);
int r_size(int);
int r_read(int,void *,int,int);
int r_create(const uint16_t *,int,int *);
int r_write(int,const void *,int);
int r_ticks(void);
void r_sleep(int);
int r_timer_install(int,void (*)(void),int);
int r_timer_start(int);
int r_timer_stop(int);
int r_timer_remove(int);
#endif
