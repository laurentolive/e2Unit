/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/*******************************************************************************
 * e2Unit - main of the standalone test firmware
 ******************************************************************************/
#include "eunit.h"

/* Board hook (clocks, watchdog...): override it in the board directory. */
void eunit_board_init(void);
__attribute__((weak)) void eunit_board_init(void)
{
}

int main(void)
{
    eunit_board_init();
    eunit_run();
    return 0;
}
