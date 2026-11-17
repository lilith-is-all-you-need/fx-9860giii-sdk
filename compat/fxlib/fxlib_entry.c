/* SPDX-License-Identifier: MIT */
#include "fxlib.h"
extern int AddIn_main(int isAppli, unsigned short OptionNum);
int main(void)
{
    fxlib_compat_init();
    return AddIn_main(1, 0);
}
