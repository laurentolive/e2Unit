/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/* Renesas RA4E1 (R7FA4E10D) - 512 KiB code flash, 128 KiB SRAM */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 512K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}

INCLUDE eunit_sections.ld
