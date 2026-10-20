/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/*******************************************************************************
 * e2Unit - minimal Cortex-M startup for standalone test firmware
 *
 * Only the core exceptions are populated: the test firmware uses no interrupt.
 * A fault while running a function under test is reported to the host
 * through the mailbox (status EUNIT_ERR_FAULT + faulting PC).
 ******************************************************************************/
#include <stdint.h>
#include "eunit.h"

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;

int main(void);
void Reset_Handler(void);
void Default_Handler(void);
void HardFault_Handler(void);
void eunit_hardfault_c(const uint32_t *frame);

void NMI_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void)  __attribute__((weak, alias("HardFault_Handler")));
void BusFault_Handler(void)   __attribute__((weak, alias("HardFault_Handler")));
void UsageFault_Handler(void) __attribute__((weak, alias("HardFault_Handler")));
void SecureFault_Handler(void)__attribute__((weak, alias("HardFault_Handler")));
void SVC_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void)     __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void)    __attribute__((weak, alias("Default_Handler")));

typedef void (*eunit_vector_t)(void);

__attribute__((section(".vectors"), used))
const eunit_vector_t eunit_vectors[16] = {
    (eunit_vector_t)(uintptr_t)&_estack,
    Reset_Handler,
    NMI_Handler,
    HardFault_Handler,
    MemManage_Handler,
    BusFault_Handler,
    UsageFault_Handler,
    SecureFault_Handler,
    0, 0, 0,
    SVC_Handler,
    DebugMon_Handler,
    0,
    PendSV_Handler,
    SysTick_Handler,
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    for (uint32_t *dst = &_sdata; dst < &_edata;) {
        *dst++ = *src++;
    }
    for (uint32_t *dst = &_sbss; dst < &_ebss;) {
        *dst++ = 0u;
    }
#if defined(__ARM_FP)
    /* enable CP10/CP11 (FPU) before any floating point code */
    *(volatile uint32_t *)0xE000ED88u |= (0xFu << 20);
    __asm volatile("dsb\n\tisb" ::: "memory");
#endif
    (void)main();
    for (;;) {
    }
}

void Default_Handler(void)
{
    for (;;) {
    }
}

/* Select the stacked frame (MSP/PSP), compatible with ARMv6-M/ARMv8-M baseline. */
__attribute__((naked)) void HardFault_Handler(void)
{
    __asm volatile(
        "movs r0, #4            \n"
        "mov  r1, lr            \n"
        "tst  r0, r1            \n"
        "beq  1f                \n"
        "mrs  r0, psp           \n"
        "b    2f                \n"
        "1:                     \n"
        "mrs  r0, msp           \n"
        "2:                     \n"
        "ldr  r1, =eunit_hardfault_c \n"
        "bx   r1                \n");
}

void eunit_hardfault_c(const uint32_t *frame)
{
    eunit_fault(frame[6]); /* stacked PC */
    for (;;) {
        /* the host resets the target */
    }
}
