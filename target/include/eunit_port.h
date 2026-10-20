/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/*******************************************************************************
 * e2Unit - porting interface
 *
 * A port provides a cycle counter, a memory barrier and an idle hook.
 * Available ports: target/port/host, target/port/cortex-m.
 ******************************************************************************/
#ifndef EUNIT_PORT_H
#define EUNIT_PORT_H

#include <stdint.h>

/* Initialise the cycle counter. */
void eunit_port_init(void);

/* Free running cycle counter (0 if the port has none). */
uint32_t eunit_port_cycles(void);

/* Elapsed cycles between two eunit_port_cycles() samples (handles wrap). */
uint32_t eunit_port_elapsed(uint32_t t0, uint32_t t1);

/* Data memory barrier: orders mailbox accesses with respect to the host. */
void eunit_port_barrier(void);

/* Called while waiting for a request. */
void eunit_port_idle(void);

#endif /* EUNIT_PORT_H */
