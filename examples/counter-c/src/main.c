#include <gint/display.h>
#include <gint/gint.h>
#include <gint/keyboard.h>

typedef struct { int value; unsigned updates; } Counter;
Counter counter = {0, 0};

__attribute__((noinline)) int clamp_counter(int value)
{
    int bounded = value;
    if (bounded > 99) bounded = 99;
    if (bounded < -99) bounded = -99;
    return bounded;
}

__attribute__((noinline)) void change_counter(Counter *state, int delta)
{
    int previous = state->value;
    int candidate = previous + delta;
    state->value = clamp_counter(candidate);
    state->updates += 1;
}

static void draw_counter(const Counter *state)
{
    dclear(C_WHITE);
    drect(0, 0, 127, 10, C_BLACK);
    dtext(3, 2, C_WHITE, "FX STUDIO / C");
    dprint(5, 17, C_BLACK, "Counter: %d", state->value);
    dprint(5, 29, C_BLACK, "Updates: %u", state->updates);
    dtext(5, 42, C_BLACK, "+ / - : change");
    dtext(5, 54, C_BLACK, "F1:reset  EXIT:menu");
    dupdate();
}

int main(void)
{
    gint_setrestart(1); // Allow direct re-entry after EXIT on the calculator.
    draw_counter(&counter);
    for (;;) {
        key_event_t event = getkey();
        if (event.key == KEY_EXIT) break;
        if (event.key == KEY_PLUS || event.key == KEY_RIGHT) change_counter(&counter, 1);
        if (event.key == KEY_MINUS || event.key == KEY_LEFT) change_counter(&counter, -1);
        if (event.key == KEY_F1) { counter.value = 0; counter.updates = 0; }
        draw_counter(&counter);
    }
    return 0;
}
