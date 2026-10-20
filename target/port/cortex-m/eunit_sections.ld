/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/*******************************************************************************
 * e2Unit - generic Cortex-M sections. The board linker script defines the
 * FLASH and RAM regions then INCLUDEs this file.
 ******************************************************************************/
ENTRY(Reset_Handler)

_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
    .text :
    {
        KEEP(*(.vectors))
        *(.text*)
        *(.rodata*)
        . = ALIGN(4);
    } > FLASH

    .ARM.exidx :
    {
        *(.ARM.exidx* .gnu.linkonce.armexidx.*)
    } > FLASH

    _sidata = LOADADDR(.data);

    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > RAM AT > FLASH

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > RAM

    /* keep at least 4 KiB for the stack */
    ASSERT(_ebss + 0x1000 <= _estack, "RAM overflow: reduce EUNIT_BUF_WORDS")
}
