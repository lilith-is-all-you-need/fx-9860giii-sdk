/* SPDX-License-Identifier: MIT
 * Temporary monotonic arena. No malloc replacement, individual free, or paging.
 * Pointers allocated after a mark must not escape a rewind to that mark.
 */
#ifndef FX_ARENA_H
#define FX_ARENA_H
#include <stddef.h>
#include <stdint.h>
typedef struct {
    unsigned char *data;
    size_t capacity, used, peak, attempts, fail_at;
} fx_arena;
void fx_arena_init(fx_arena *arena, void *data, size_t bytes);
void fx_arena_fail_at(fx_arena *arena, size_t ordinal);
void *fx_arena_take(fx_arena *arena, size_t bytes, size_t alignment);
int fx_arena_rewind(fx_arena *arena, size_t mark);
#endif
