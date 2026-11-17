/* SPDX-License-Identifier: MIT */
#include <gint/display.h>
#include <gint/gint.h>
#include <gint/keyboard.h>
#include "model.h"
static unsigned char scratch_bytes[512]; /* Example budget, not device RAM measurement. */
fx_arena scratch;
fx_model app;
volatile unsigned selftest_failures;
volatile int last_status;
__attribute__((noinline)) void demo_ready(void) { __asm__ volatile("" ::: "memory"); }
static void draw(void)
{
    dclear(C_WHITE);
    dtext(1, 1, C_BLACK, "GUARDED / C");
    dprint(1, 12, C_BLACK, "Tests:%s Value:%d", selftest_failures ? "FAIL" : "OK", app.value);
    dprint(1, 23, C_BLACK, "Runs:%u Peak:%u", app.runs, (unsigned)scratch.peak);
    dprint(1, 34, C_BLACK, "Status:%s", last_status == FX_OK ? "OK" : last_status == FX_NO_MEMORY ? "NO MEMORY" : "CANCELLED");
    dtext(1, 45, C_BLACK, "EXE:run F1:OOM");
    dtext(1, 56, C_BLACK, "F2:cancel EXIT:menu");
    dupdate();
}
int main(void)
{
    gint_setrestart(1);
    fx_arena_init(&scratch, scratch_bytes, sizeof scratch_bytes);
    app = (fx_model){0, 0};
    last_status = FX_OK;
    selftest_failures = fx_contract_test();
    draw();
    demo_ready(); /* Stable breakpoint after rendering, independent of line numbers. */
    for (;;) {
        key_event_t event = getkey();
        if (event.key == KEY_EXIT) break;
        if (event.key != KEY_EXE && event.key != KEY_F1 && event.key != KEY_F2) continue;
        fx_arena_fail_at(&scratch, event.key == KEY_F1 ? 2 : 0);
        last_status = fx_model_apply(&app, &scratch, event.key == KEY_F2 ? 3 : 0);
        draw();
        demo_ready();
    }
    return 0;
}
