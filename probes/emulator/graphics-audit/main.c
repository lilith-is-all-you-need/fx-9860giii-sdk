#include <gint/clock.h>
#include <gint/display.h>
#include <gint/gray.h>
#include <gint/keyboard.h>

extern bopti_image_t audit_sprite;
extern font_t audit_digits;
volatile unsigned graphics_checks;
volatile int gray_start_result = -100;

__attribute__((noinline)) void audit_mono_ready(void) { __asm__ volatile ("nop"); }
__attribute__((noinline)) void audit_gray_ready(void) { __asm__ volatile ("nop"); }
__attribute__((noinline)) void audit_off_ready(void) { __asm__ volatile ("nop"); }

int main(void)
{
    dclear(C_WHITE);
    struct dwindow old = dwindow_set((struct dwindow){8, 8, 32, 24});
    drect(-30, -30, 150, 80, C_BLACK);
    dwindow_set(old);
    if(dgetpixel(8, 8) == C_BLACK && dgetpixel(31, 23) == C_BLACK &&
        dgetpixel(7, 8) == C_WHITE && dgetpixel(32, 23) == C_WHITE)
        graphics_checks |= 1;

    int xs[] = {42, 58, 50}, ys[] = {3, 3, 19};
    dpoly(xs, ys, 3, C_BLACK, C_BLACK);
    if(dgetpixel(50, 7) == C_BLACK) graphics_checks |= 2;
    dcircle(74, 11, 8, C_NONE, C_BLACK);
    if(dgetpixel(82, 11) == C_BLACK) graphics_checks |= 4;
    dellipse(88, 3, 110, 19, C_NONE, C_BLACK);
    if(dgetpixel(110, 11) == C_BLACK) graphics_checks |= 8;
    dline(-10, 31, 140, 31, C_BLACK);
    if(dgetpixel(0, 31) == C_BLACK && dgetpixel(127, 31) == C_BLACK)
        graphics_checks |= 16;

    dimage(0, 40, &audit_sprite);
    dsubimage(20, 40, &audit_sprite, 0, 0, 8, 8, DIMAGE_NONE);
    if(dgetpixel(1, 41) == C_WHITE && dgetpixel(2, 42) == C_BLACK &&
        dgetpixel(22, 42) == C_BLACK) graphics_checks |= 32;
    font_t const *previous = dfont(&audit_digits);
    dtext(48, 40, C_BLACK, "0123456789");
    if(dgetpixel(48, 40) == C_BLACK && dgetpixel(49, 41) == C_WHITE)
        graphics_checks |= 64;
    dfont(previous);
    dtext(1, 54, C_BLACK, "CLIP POLY IMG FONT");
    dupdate();
    audit_mono_ready();

    gray_start_result = dgray(DGRAY_ON);
    dclear(C_WHITE);
    int shades[] = {C_WHITE, C_LIGHT, C_DARK, C_BLACK};
    for(int i = 0; i < 4; i++) drect(i*32, 8, i*32+31, 51, shades[i]);
    dtext(1, 0, C_BLACK, "GRAY 4 SHADES");
    dupdate();
    sleep_ms(300);
    audit_gray_ready();

    dgray(DGRAY_OFF);
    dclear(C_WHITE);
    dtext(1, 20, C_BLACK, "GRAY OFF OK");
    dupdate();
    audit_off_ready();
    while(getkey().key != KEY_EXIT) { }
    return 0;
}
