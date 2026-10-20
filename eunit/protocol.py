"""Mailbox protocol constants, mirror of target/include/eunit.h."""

MAGIC = 0x54494E55
VERSION = 1

# word offsets in eunit_mailbox_t
W_MAGIC = 0
W_VERSION = 1
W_HASH = 2
W_FN_COUNT = 3
W_BUF_WORDS = 4
W_CPU_HZ = 5
W_REQ = 6
W_ACK = 7
W_CMD = 8
W_FN = 9
W_COUNT = 10
W_STATUS = 11
W_CYCLES = 12      # calls, min, max, sum_lo, sum_hi
W_FAULT_PC = 17
W_BUF = 20
HEADER_WORDS = W_BUF

CMD_PING = 1
CMD_BATCH = 2

STATUS_OK = 0
STATUS_TEXT = {
    0: "ok",
    1: "unknown command",
    2: "function index out of table",
    3: "batch does not fit the buffer",
    4: "CPU fault",
}
STATUS_FAULT = 4
