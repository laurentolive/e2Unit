# 7. Integration

**English** | [Français](../tutoriels/07-integration.md)

Organise the suites of a project, run them in continuous integration, and run the tests inside an
existing application rather than in the test firmware.

## Organising the suites

The example follows a layout that carries over to a project:

```
examples/emath/
  Makefile             runs a goal on every suite
  src/                 the code under test
  tests/
    emath_ref.py       shared reference models
    sin/  mulq15/  atan2/  pow/  isqrt/  rms/     one suite per module
    all/               global suite (includes the others)
```

The top `Makefile` ([`examples/emath`](../../examples/emath)) applies a goal to each suite:

```
make test              # every suite on the PC
make -k test-emu       # every suite, in the emulator, without stopping at the first failure
make target            # one firmware per suite, plus the global firmware
make test/rms          # a single suite
```

To add a suite, create its folder and add it to the `SUITES` list of this Makefile.

## Continuous integration

The exit code gives the verdict (0 PASS, 1 FAIL, 2 error) and every run writes a `junit.xml`.
Example of a Jenkins stage on a Windows agent:

```groovy
stage('Unit tests') {
    steps {
        bat 'make -C examples/emath -k test test-emu'
    }
    post {
        always {
            junit 'examples/emath/tests/**/build/report/**/junit.xml'
            archiveArtifacts artifacts: 'examples/emath/tests/**/build/report/**/*.xlsx', allowEmptyArchive: true
        }
    }
}
```

- `test` (PC) and `test-emu` (emulated ARM binary) need no board: they run on any agent.
- `test-target` needs an agent with a board and a J-Link probe plugged in.
- The name of each JUnit suite carries the runner (`sin.host`, `sin.emu`): PC and target results
  show up separately.

The tool paths of the agent go into its own `eunit.local.mk`.

## Testing inside an existing application

The e2Unit test firmware is minimal: no clock set-up, no peripheral, no RTOS. To test a function
**in its real environment** (configured clocks, caches, other tasks), add the runtime to the application.

### Files to add to the project (e² studio, CubeIDE...)

| File | Role |
|---|---|
| `target/src/eunit_runtime.c` | runtime |
| `target/port/cortex-m/eunit_port_cortexm.c` | cycle counter, memory barrier |
| `build/gen/eunit_suite.c` | adapters generated from the specification |
| your adapters (`EUNIT_ADAPTER`), if any | stateful functions |

Include path: `target/include`. The generated file is produced with:

```
python eunit_cli.py gen suite.yaml --out build/gen
```

Do **not** add `eunit_startup.c` nor `eunit_main.c`: the application has its own.

### Call in the main loop

```c
#include "eunit.h"

void hal_entry(void)
{
    /* ... application initialisation ... */
    eunit_init();
    for (;;) {
        eunit_poll();          /* serves a request from the PC, if any */
        /* ... rest of the loop ... */
    }
}
```

`eunit_poll()` returns at once when there is nothing to do. When a batch arrives, it runs it
entirely before returning: reduce `EUNIT_BUF_WORDS` (compiler option, 2048 words by default) if a
watchdog or a real-time task cannot stand it.

Optionally, in the `HardFault_Handler` of the application, call `eunit_fault(pc)`: the PC then
sees the fault (`CPU fault at PC ...`) instead of a timeout.

### Running

```
python eunit_cli.py run suite.yaml --runner jlink --elf Debug/app.elf --device R7FA4E10D
```

The application is flashed and started as usual (e² studio, J-Flash...), then the debug session is
closed to free the probe. e2Unit resets the board before each test: `eunit_init()` must be reached
within 5 seconds after the reset.

## Command summary

| Command | Effect |
|---|---|
| `make` / `make test` | PC build + tests on the PC |
| `make test-sim` | tests through the target protocol, on the PC |
| `make target` | test firmware for the board (`BOARD=ra4e1` by default) |
| `make test-emu` | firmware in the emulator, compared with the PC |
| `make flash` | programs the firmware through J-Link |
| `make test-target` | flash + tests on the board, compared with the PC |
| `make list` | functions and tests of the suite |
| `make clean` | deletes `build/` |
| `EUNIT_RUN_OPTS="-v --plot build/plots"` | check details, plots |
| `JLINK_OPTS="--serial N --speed 12000"` | probe choice and speed |
