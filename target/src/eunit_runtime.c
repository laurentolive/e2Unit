/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/*******************************************************************************
 * e2Unit - runtime: batch execution and mailbox server
 ******************************************************************************/
#include "eunit.h"
#include "eunit_port.h"

/* The host relies on these offsets: fail the build if the layout drifts. */
typedef char eunit_check_buf_offset[(offsetof(eunit_mailbox_t, buf) == EUNIT_MAILBOX_BUF_OFFSET) ? 1 : -1];
typedef char eunit_check_req_offset[(offsetof(eunit_mailbox_t, req) == 24u) ? 1 : -1];

#ifndef EUNIT_MAILBOX_ATTR
#define EUNIT_MAILBOX_ATTR __attribute__((used))
#endif

EUNIT_MAILBOX_ATTR eunit_mailbox_t eunit_mailbox;

static uint32_t eunit_overhead; /* cost of the measurement itself */

/*----------------------------------------------------------------------------*/
static void eunit_calibrate(void)
{
    uint32_t best = 0xFFFFFFFFu;
    for (uint32_t i = 0u; i < 8u; i++) {
        uint32_t t0 = eunit_port_cycles();
        uint32_t t1 = eunit_port_cycles();
        uint32_t dt = eunit_port_elapsed(t0, t1);
        if (dt < best) {
            best = dt;
        }
    }
    eunit_overhead = best;
}

/*----------------------------------------------------------------------------*/
uint32_t eunit_exec(uint32_t fn, uint32_t count, int32_t *buf, uint32_t buf_words,
                    eunit_cycles_t *cycles)
{
    if (fn >= eunit_suite_count) {
        return EUNIT_ERR_FN;
    }
    const eunit_entry_t *e = &eunit_suite_table[fn];
    const uint32_t nin = e->nin;
    const uint32_t nout = e->nout;

    if (((uint64_t)count * (uint64_t)(nin + nout)) > (uint64_t)buf_words) {
        return EUNIT_ERR_SIZE;
    }

    const int32_t *in = buf;
    int32_t *out = &buf[count * nin];
    uint32_t cmin = 0xFFFFFFFFu;
    uint32_t cmax = 0u;
    uint64_t csum = 0u;

    for (uint32_t i = 0u; i < count; i++) {
        uint32_t t0 = eunit_port_cycles();
        e->fn(&in[i * nin], &out[i * nout]);
        uint32_t t1 = eunit_port_cycles();
        uint32_t dt = eunit_port_elapsed(t0, t1);
        dt = (dt > eunit_overhead) ? (dt - eunit_overhead) : 0u;
        cmin = (dt < cmin) ? dt : cmin;
        cmax = (dt > cmax) ? dt : cmax;
        csum += dt;
    }

    if (cycles != NULL) {
        cycles->calls = count;
        cycles->min = (count > 0u) ? cmin : 0u;
        cycles->max = cmax;
        cycles->sum_lo = (uint32_t)csum;
        cycles->sum_hi = (uint32_t)(csum >> 32);
    }
    return EUNIT_OK;
}

/*----------------------------------------------------------------------------*/
void eunit_init(void)
{
    volatile eunit_mailbox_t *mb = &eunit_mailbox;

    eunit_port_init();
    eunit_calibrate();

    mb->magic = 0u;
    eunit_port_barrier();
    mb->version = EUNIT_PROTO_VERSION;
    mb->hash = eunit_suite_hash;
    mb->fn_count = eunit_suite_count;
    mb->buf_words = EUNIT_BUF_WORDS;
    mb->cpu_hz = EUNIT_CPU_HZ;
    mb->req = 0u;
    mb->ack = 0u;
    mb->cmd = EUNIT_CMD_NONE;
    mb->status = EUNIT_OK;
    mb->fault_pc = 0u;
    eunit_port_barrier();
    mb->magic = EUNIT_MAGIC; /* published last: the host may start */
    eunit_port_barrier();
}

/*----------------------------------------------------------------------------*/
int eunit_poll(void)
{
    volatile eunit_mailbox_t *mb = &eunit_mailbox;

    eunit_port_barrier();
    const uint32_t req = mb->req;
    if (req == mb->ack) {
        return 0;
    }
    eunit_port_barrier();

    uint32_t status;
    switch (mb->cmd) {
    case EUNIT_CMD_PING:
        status = EUNIT_OK;
        break;
    case EUNIT_CMD_BATCH:
        status = eunit_exec(mb->fn, mb->count, eunit_mailbox.buf, EUNIT_BUF_WORDS,
                            &eunit_mailbox.cycles);
        break;
    default:
        status = EUNIT_ERR_CMD;
        break;
    }

    mb->status = status;
    eunit_port_barrier();
    mb->ack = req; /* published last: results are complete */
    eunit_port_barrier();
    return 1;
}

/*----------------------------------------------------------------------------*/
void eunit_run(void)
{
    eunit_init();
    for (;;) {
        if (eunit_poll() == 0) {
            eunit_port_idle();
        }
    }
}

/*----------------------------------------------------------------------------*/
void eunit_fault(uint32_t pc)
{
    volatile eunit_mailbox_t *mb = &eunit_mailbox;

    mb->fault_pc = pc;
    mb->status = EUNIT_ERR_FAULT;
    eunit_port_barrier();
    mb->ack = mb->req;
    eunit_port_barrier();
}
