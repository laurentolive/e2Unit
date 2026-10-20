/* SPDX-License-Identifier: MIT - Copyright (c) 2026 Laurent Olive */
/*******************************************************************************
 * e2Unit - unit test runtime for C functions, on host and on target
 *
 * The runtime exposes a table of "adapters" (one per function under test) and
 * executes them in batches. On target, batches are requested by the host via a
 * mailbox in RAM accessed through the debug probe (SWD); on host, the same
 * entry point is called directly from Python (ctypes).
 *
 * Adapter ABI: every argument and every result is carried in a 32-bit word.
 *   void adapter(const int32_t *in, int32_t *out);
 * The adapter table is generated from the test specification (eunit gen).
 ******************************************************************************/
#ifndef EUNIT_H
#define EUNIT_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

/*----------------------------------------------------------------------------*/
/* Protocol constants (keep in sync with eunit/protocol.py)                   */
#define EUNIT_MAGIC          0x54494E55u /* "UNIT" */
#define EUNIT_PROTO_VERSION  1u

#ifndef EUNIT_BUF_WORDS
#define EUNIT_BUF_WORDS      2048u       /* exchange buffer size, 32-bit words */
#endif

#ifndef EUNIT_CPU_HZ
#define EUNIT_CPU_HZ         0u          /* 0 = unknown */
#endif

typedef enum {
    EUNIT_CMD_NONE  = 0u,
    EUNIT_CMD_PING  = 1u,
    EUNIT_CMD_BATCH = 2u
} eunit_cmd_t;

typedef enum {
    EUNIT_OK        = 0u,
    EUNIT_ERR_CMD   = 1u,  /* unknown command                 */
    EUNIT_ERR_FN    = 2u,  /* function index out of the table */
    EUNIT_ERR_SIZE  = 3u,  /* batch does not fit the buffer   */
    EUNIT_ERR_FAULT = 4u   /* CPU fault while executing       */
} eunit_status_t;

/*----------------------------------------------------------------------------*/
/* Adapter table (generated)                                                  */
typedef void (*eunit_adapter_t)(const int32_t *in, int32_t *out);

typedef struct {
    eunit_adapter_t fn;
    uint8_t         nin;   /* number of input words  */
    uint8_t         nout;  /* number of output words */
} eunit_entry_t;

extern const eunit_entry_t eunit_suite_table[];
extern const uint32_t      eunit_suite_count;
extern const uint32_t      eunit_suite_hash;

/* Declare / define a custom adapter, e.g.
 *   EUNIT_ADAPTER(rms_update) { out[0] = emath_rms_update(&ctx, (int16_t)in[0]); }
 */
#define EUNIT_ADAPTER(name) void eunit_adapter_##name(const int32_t *in, int32_t *out)

/* Word <-> float conversions for adapters */
static inline float eunit_w2f(int32_t w) { float f; memcpy(&f, &w, sizeof f); return f; }
static inline int32_t eunit_f2w(float f) { int32_t w; memcpy(&w, &f, sizeof w); return w; }

/*----------------------------------------------------------------------------*/
/* Mailbox: shared between target and host, all fields are 32-bit words so the
 * layout is identical on every architecture. Word offsets are part of the
 * protocol (see eunit/protocol.py).                                          */
typedef struct {
    uint32_t calls;
    uint32_t min;
    uint32_t max;
    uint32_t sum_lo;
    uint32_t sum_hi;
} eunit_cycles_t;

typedef struct {
    uint32_t       magic;      /* [0]  EUNIT_MAGIC once the target is ready  */
    uint32_t       version;    /* [1]  EUNIT_PROTO_VERSION                   */
    uint32_t       hash;       /* [2]  suite hash (firmware/spec matching)   */
    uint32_t       fn_count;   /* [3]  number of adapters                    */
    uint32_t       buf_words;  /* [4]  capacity of buf[]                     */
    uint32_t       cpu_hz;     /* [5]  core clock, 0 if unknown              */
    uint32_t       req;        /* [6]  host -> target request sequence       */
    uint32_t       ack;        /* [7]  target -> host acknowledged sequence  */
    uint32_t       cmd;        /* [8]  eunit_cmd_t                           */
    uint32_t       fn;         /* [9]  adapter index                         */
    uint32_t       count;      /* [10] number of calls in the batch          */
    uint32_t       status;     /* [11] eunit_status_t                        */
    eunit_cycles_t cycles;     /* [12..16] cycle statistics of the batch     */
    uint32_t       fault_pc;   /* [17] PC of the faulting instruction        */
    uint32_t       reserved[2];/* [18..19]                                   */
    int32_t        buf[EUNIT_BUF_WORDS]; /* [20..] inputs then outputs       */
} eunit_mailbox_t;

#define EUNIT_MAILBOX_BUF_OFFSET 80u

extern eunit_mailbox_t eunit_mailbox;

/*----------------------------------------------------------------------------*/
/* Runtime API                                                                */

/* Execute `count` calls of adapter `fn`. buf holds count*nin input words,
 * followed by room for count*nout output words. `cycles` may be NULL. */
uint32_t eunit_exec(uint32_t fn, uint32_t count, int32_t *buf, uint32_t buf_words,
                    eunit_cycles_t *cycles);

/* Initialise the mailbox; the host starts talking once magic is published. */
void eunit_init(void);

/* Serve one pending request, if any. Returns 1 if a request was served.
 * Call it from the main loop of an existing application to embed e2Unit. */
int eunit_poll(void);

/* eunit_init() then serve requests forever (standalone test firmware). */
void eunit_run(void);

/* Report a CPU fault to the host (called from the fault handler). */
void eunit_fault(uint32_t pc);

#ifdef __cplusplus
}
#endif

#endif /* EUNIT_H */
