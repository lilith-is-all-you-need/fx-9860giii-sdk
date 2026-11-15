#include <gint/display.h>
#include <gint/keyboard.h>

static int increment(int value) { return value + 1; }

int main(void)
{
    int count = 0;
    for (;;) {
        dclear(C_WHITE);
        dtext(4, 4, C_BLACK, "FX IDE - C");
        dprint(4, 20, C_BLACK, "Counter: %d", count);
        dtext(4, 42, C_BLACK, "EXE: add   EXIT: quit");
        dupdate();
        int key = getkey().key;
        if (key == KEY_EXIT) return 0;
        if (key == KEY_EXE) count = increment(count);
    }
}
