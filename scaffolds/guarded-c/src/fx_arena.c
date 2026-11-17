/* SPDX-License-Identifier: MIT */
#include "fx_arena.h"
void fx_arena_init(fx_arena *arena, void *data, size_t bytes)
{
    *arena = (fx_arena){ .data = data, .capacity = data ? bytes : 0 };
}
void fx_arena_fail_at(fx_arena *arena, size_t ordinal)
{
    arena->attempts = 0;
    arena->fail_at = ordinal; /* 0 disables injection; 1 fails the first request. */
}
void *fx_arena_take(fx_arena *arena, size_t bytes, size_t alignment)
{
    if (!bytes || !alignment || (alignment & (alignment - 1)) ||
        !arena->data || arena->used > arena->capacity) return NULL;
    if (arena->attempts == SIZE_MAX) return NULL;
    arena->attempts++;
    if (arena->fail_at && arena->attempts == arena->fail_at) return NULL;
    uintptr_t start = (uintptr_t)arena->data;
    if (arena->used > UINTPTR_MAX - start) return NULL;
    start += arena->used;
    size_t mask = alignment - 1;
    if (mask > UINTPTR_MAX - start) return NULL;
    uintptr_t aligned = (start + mask) & ~(uintptr_t)mask;
    size_t padding = (size_t)(aligned - start);
    size_t available = arena->capacity - arena->used;
    if (padding > available || bytes > available - padding) return NULL;
    arena->used += padding + bytes;
    if (arena->used > arena->peak) arena->peak = arena->used;
    return (void *)aligned;
}
int fx_arena_rewind(fx_arena *arena, size_t mark)
{
    if (mark > arena->used) return 0;
    arena->used = mark;
    return 1;
}
