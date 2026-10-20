/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/*******************************************************************************
 * e2Unit - Cortex-M port
 *
 * Cycle counter: DWT->CYCCNT on ARMv7-M / ARMv8-M mainline (M3/M4/M7/M33/M55),
 * SysTick (24-bit, core clock) on ARMv6-M / ARMv8-M baseline (M0/M0+/M23).
 ******************************************************************************/
#include "eunit.h"
#include "eunit_port.h"

#define EUNIT_REG(addr) (*(volatile uint32_t *)(addr))

#if defined(__ARM_ARCH_7M__) || defined(__ARM_ARCH_7EM__) || defined(__ARM_ARCH_8M_MAIN__) || \
    defined(__ARM_ARCH_8_1M_MAIN__)
#define EUNIT_USE_DWT 1
#else
#define EUNIT_USE_DWT 0
#endif

#define DEMCR        EUNIT_REG(0xE000EDFCu)
#define DEMCR_TRCENA (1u << 24)
#define DWT_CTRL     EUNIT_REG(0xE0001000u)
#define DWT_CYCCNT   EUNIT_REG(0xE0001004u)
#define DWT_LAR      EUNIT_REG(0xE0001FB0u)
#define SYST_CSR     EUNIT_REG(0xE000E010u)
#define SYST_RVR     EUNIT_REG(0xE000E014u)
#define SYST_CVR     EUNIT_REG(0xE000E018u)
#define SYST_MASK    0x00FFFFFFu

void eunit_port_init(void)
{
#if EUNIT_USE_DWT
    DEMCR |= DEMCR_TRCENA;
    DWT_LAR = 0xC5ACCE55u; /* unlock (Cortex-M7), ignored elsewhere */
    DWT_CYCCNT = 0u;
    DWT_CTRL |= 1u;        /* CYCCNTENA */
#else
    SYST_RVR = SYST_MASK;
    SYST_CVR = 0u;
    SYST_CSR = 0x5u;       /* core clock, no interrupt, enable */
#endif
}

uint32_t eunit_port_cycles(void)
{
#if EUNIT_USE_DWT
    return DWT_CYCCNT;
#else
    return SYST_MASK - (SYST_CVR & SYST_MASK); /* count up */
#endif
}

uint32_t eunit_port_elapsed(uint32_t t0, uint32_t t1)
{
#if EUNIT_USE_DWT
    return t1 - t0;
#else
    return (t1 - t0) & SYST_MASK;
#endif
}

void eunit_port_barrier(void)
{
    __asm volatile("dmb" ::: "memory");
}

void eunit_port_idle(void)
{
}
