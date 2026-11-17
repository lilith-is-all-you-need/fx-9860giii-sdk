/* SPDX-License-Identifier: MIT
 * A legacy-style source file: no gint calls and no main() rewrite needed. */
#include "fxlib.h"
#include <stdio.h>

static int count, timer_pulses;
static const unsigned char cross[]={0x18,0x18,0x18,0xff,0xff,0x18,0x18,0x18};
static void tick(void) { timer_pulses++; }

int AddIn_main(int isAppli,unsigned short OptionNum)
{
    unsigned int key;
    (void)isAppli; (void)OptionNum;
    SetTimer(1,250,tick);
    for(;;) {
        unsigned char text[24];
        Bdisp_AllClr_VRAM();
        locate(1,1); Print((const unsigned char *)"Legacy fxlib -> gint");
        PrintMini(2,13,(const unsigned char *)"EXE +1   EXIT quit",MINI_OVER);
        sprintf((char *)text,"Count %d",count);
        PrintXY(2,27,text,0);
        sprintf((char *)text,"Timer %d",timer_pulses);
        PrintXY(2,39,text,0);
        DISPGRAPH graph={112,27,{8,8,cross},IMB_WRITEMODIFY_NORMAL,IMB_WRITEKIND_OVER};
        Bdisp_WriteGraph_VRAM(&graph);
        Bdisp_DrawLineVRAM(0,55,127,55);
        Bdisp_PutDisp_DD();
        if(GetKey(&key)<0) return 1;
        if(key==KEY_CTRL_EXIT) break;
        if(key==KEY_CTRL_EXE) count++;
    }
    KillTimer(1);
    return 0;
}
