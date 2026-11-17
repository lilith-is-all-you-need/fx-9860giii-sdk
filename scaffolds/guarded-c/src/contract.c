/* SPDX-License-Identifier: MIT
 * Same checks run natively and as SuperH instructions in the demo.
 */
#include "model.h"
#define CHECK(x) do { if (!(x)) failures++; } while (0)
unsigned fx_contract_test(void)
{
    unsigned failures = 0;
    unsigned char storage[256];
    fx_arena arena;
    fx_model model = {7, 0};
    fx_arena_init(&arena, storage + 1, sizeof(storage) - 2);
    storage[0] = 0x5a;
    storage[255] = 0xa5;
    void *aligned = fx_arena_take(&arena, 1, 8);
    CHECK(aligned && ((uintptr_t)aligned % 8) == 0);
    size_t mark = arena.used;
    CHECK(!fx_arena_take(&arena, SIZE_MAX, 4) && arena.used == mark);
    CHECK(!fx_arena_take(&arena, 8, 3) && arena.used == mark);
    CHECK(!fx_arena_take(&arena, 0, 4) && arena.used == mark);
    CHECK(!fx_arena_rewind(&arena, mark + 1) && arena.used == mark);
    CHECK(fx_arena_rewind(&arena, 0));
    for (size_t point = 1; point <= 2; point++) {
        fx_arena_fail_at(&arena, point);
        CHECK(fx_model_apply(&model, &arena, 0) == FX_NO_MEMORY);
        CHECK(model.value == 7 && model.runs == 0 && arena.used == 0);
    }
    fx_arena_fail_at(&arena, 0);
    for (unsigned i = 0; i < 50; i++) {
        CHECK(fx_model_apply(&model, &arena, 3) == FX_CANCELLED);
        CHECK(model.value == 7 && model.runs == 0 && arena.used == 0);
    }
    for (unsigned i = 0; i < 50; i++) {
        CHECK(fx_model_apply(&model, &arena, 0) == FX_OK);
        CHECK(model.value == 120 && model.runs == i + 1 && arena.used == 0);
    }
    CHECK(arena.peak <= arena.capacity);
    CHECK(storage[0] == 0x5a && storage[255] == 0xa5);
    fx_arena_init(&arena, storage, 16);
    fx_model previous = model;
    CHECK(fx_model_apply(&model, &arena, 0) == FX_NO_MEMORY);
    CHECK(model.value == previous.value && model.runs == previous.runs && arena.used == 0);
    fx_arena_init(&arena, NULL, 256);
    CHECK(!fx_arena_take(&arena, 1, 1));
    return failures;
}
