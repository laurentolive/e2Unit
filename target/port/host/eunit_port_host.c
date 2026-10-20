/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/*******************************************************************************
 * e2Unit - host port (shared library loaded by the Python runner)
 *
 * Two execution modes use the same library:
 *  - direct : Python calls eunit_exec() (fast, no protocol)
 *  - sim    : Python runs eunit_sim_run() in a thread and talks through the
 *             mailbox exactly as with a real target, which validates the
 *             protocol without hardware.
 ******************************************************************************/
#include "eunit.h"
#include "eunit_port.h"

#if defined(_WIN32)
#include <windows.h>
#else
#include <sched.h>
#endif

void eunit_port_init(void)
{
}

uint32_t eunit_port_cycles(void)
{
    return 0u; /* no meaningful cycle count on host */
}

uint32_t eunit_port_elapsed(uint32_t t0, uint32_t t1)
{
    return t1 - t0;
}

void eunit_port_barrier(void)
{
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
}

void eunit_port_idle(void)
{
#if defined(_WIN32)
    (void)SwitchToThread();
#else
    (void)sched_yield();
#endif
}

/* Mailbox server loop for the simulated target, stopped by *stop != 0. */
void eunit_sim_run(volatile uint32_t *stop);

void eunit_sim_run(volatile uint32_t *stop)
{
    eunit_init();
    while (*stop == 0u) {
        if (eunit_poll() == 0) {
            eunit_port_idle();
        }
    }
}
