#################################
# e2Unit - common build and run rules
#
# A suite makefile only needs:
#   EUNIT_ROOT := ../../../..
#   SUITE      := sin.yaml
#   include $(EUNIT_ROOT)/mk/eunit.mk
#
# Targets:
#   make / make test   build the host library, run the suite on host
#   make test-sim      same library driven through the mailbox protocol
#   make target        build the flashable test firmware (BOARD=ra4e1)
#   make test-emu      run the firmware in an ARM emulator (no hardware)
#   make flash         flash it with J-Link
#   make test-target   flash, run on target and compare with host
#   make list          list functions and tests
#   make clean
#
# Variables: BOARD, BUILD, EUNIT_RUN_OPTS (e.g. "-v --plot build/plots"),
#            JLINK_OPTS (e.g. "--serial 123456 --speed 12000").
# Tool paths come from $(EUNIT_ROOT)/eunit.local.mk (see eunit.local.mk.example).
#################################

ifndef EUNIT_ROOT
$(error EUNIT_ROOT must be set before including eunit.mk)
endif
ifndef SUITE
$(error SUITE must be set before including eunit.mk)
endif

-include $(EUNIT_ROOT)/eunit.local.mk

PY             ?= python
HOST_CC        ?= gcc
ARM_PREFIX     ?= arm-none-eabi-
BOARD          ?= ra4e1
BUILD          ?= build
EUNIT_RUN_OPTS ?=
JLINK_OPTS     ?=

.DEFAULT_GOAL := test

EUNIT   := "$(PY)" $(EUNIT_ROOT)/eunit_cli.py
NAME    := $(basename $(notdir $(SUITE)))
GEN_DIR := $(BUILD)/gen
REPORT  := $(BUILD)/report

include $(EUNIT_ROOT)/boards/$(BOARD)/board.mk

#################################
# Generated from the specification: adapter table + source list
ifeq ($(filter clean list,$(MAKECMDGOALS)),)
-include $(GEN_DIR)/suite.mk
endif

$(GEN_DIR)/suite.mk: $(SUITE) $(EUNIT_SUITE_DEPS) $(EUNIT_ROOT)/eunit/codegen.py $(EUNIT_ROOT)/eunit/spec.py
	@$(EUNIT) gen $(SUITE) --out $(GEN_DIR)

$(GEN_DIR)/eunit_suite.c: $(GEN_DIR)/suite.mk ;

#################################
RT_DIR     := $(EUNIT_ROOT)/target
RT_INCS    := -I$(RT_DIR)/include
SUITE_INCS := $(addprefix -I,$(EUNIT_SUITE_INCS)) -I$(GEN_DIR)
SUITE_HDRS := $(wildcard $(addsuffix /*.h,$(EUNIT_SUITE_INCS))) $(wildcard $(RT_DIR)/include/*.h)
ALL_SRCS   := $(EUNIT_SUITE_SRCS) $(GEN_DIR)/eunit_suite.c $(RT_DIR)/src/eunit_runtime.c

WARN := -Wall -Wextra -Wconversion -Wshadow -Wpointer-arith -Wstrict-prototypes -Wundef

#################################
# Host shared library (direct and simulated runners)
ifeq ($(OS),Windows_NT)
HOST_LIB_EXT := dll
HOST_PIC     :=
else
HOST_LIB_EXT := so
HOST_PIC     := -fPIC
endif

HOST_LIB    := $(BUILD)/host/$(NAME).$(HOST_LIB_EXT)
HOST_SRCS   := $(ALL_SRCS) $(RT_DIR)/port/host/eunit_port_host.c
HOST_CFLAGS ?= -std=c11 -O2 -g $(WARN)

host: $(HOST_LIB)

$(HOST_LIB): $(HOST_SRCS) $(SUITE_HDRS)
	@echo eunit: building $@
	@$(EUNIT) fs mkdir $(@D)
	@"$(HOST_CC)" $(HOST_CFLAGS) $(HOST_PIC) -shared -static-libgcc -DEUNIT_HOST \
		$(RT_INCS) $(SUITE_INCS) $(EUNIT_SUITE_DEFS) -o $@ $(HOST_SRCS)

#################################
# Target firmware (standalone, flashable)
TGT_DIR       := $(BUILD)/$(BOARD)
TARGET_ELF    := $(TGT_DIR)/$(NAME).elf
TARGET_HEX    := $(TGT_DIR)/$(NAME).hex
CM_DIR        := $(RT_DIR)/port/cortex-m
CM_SRCS       := $(CM_DIR)/eunit_port_cortexm.c $(CM_DIR)/eunit_startup.c $(CM_DIR)/eunit_main.c
TARGET_SRCS   := $(ALL_SRCS) $(CM_SRCS) $(BOARD_SRCS)
TARGET_CFLAGS ?= -std=c11 -O2 -g3 $(WARN) -ffunction-sections -fdata-sections
TARGET_LDFLAGS = -nostartfiles -Wl,--gc-sections -Wl,-Map=$(TGT_DIR)/$(NAME).map \
                 --specs=nano.specs --specs=nosys.specs -L$(CM_DIR) -T$(BOARD_LDSCRIPT)

target: $(TARGET_ELF)

$(TARGET_ELF): $(TARGET_SRCS) $(SUITE_HDRS) $(BOARD_LDSCRIPT) $(CM_DIR)/eunit_sections.ld
	@echo eunit: building $@ for $(BOARD)
	@$(EUNIT) fs mkdir $(@D)
	@"$(ARM_PREFIX)gcc" $(BOARD_CPU_FLAGS) $(TARGET_CFLAGS) $(BOARD_DEFS) \
		$(RT_INCS) $(SUITE_INCS) $(EUNIT_SUITE_DEFS) $(TARGET_LDFLAGS) -o $@ $(TARGET_SRCS)
	@"$(ARM_PREFIX)objcopy" -O ihex $@ $(TARGET_HEX)
	@"$(ARM_PREFIX)size" $@

#################################
# Runs (the exit code is the verdict: 0 pass, 1 fail, 2 error)
test: test-host

test-host: $(HOST_LIB)
	@$(EUNIT) run $(SUITE) --runner host --lib $(HOST_LIB) --report-dir $(REPORT)/host $(EUNIT_RUN_OPTS)

test-sim: $(HOST_LIB)
	@$(EUNIT) run $(SUITE) --runner sim --lib $(HOST_LIB) --report-dir $(REPORT)/sim $(EUNIT_RUN_OPTS)

test-emu: $(TARGET_ELF) $(HOST_LIB)
	@$(EUNIT) run $(SUITE) --runner emu --elf $(TARGET_ELF) --cpu $(BOARD_EMU_CPU) \
		--compare-host $(HOST_LIB) --report-dir $(REPORT)/emu-$(BOARD) $(EUNIT_RUN_OPTS)

flash: $(TARGET_ELF)
	@$(EUNIT) flash $(TARGET_HEX) --device $(JLINK_DEVICE) $(JLINK_OPTS)

test-target: $(TARGET_ELF) $(HOST_LIB)
	@$(EUNIT) run $(SUITE) --runner jlink --elf $(TARGET_ELF) --flash --device $(JLINK_DEVICE) \
		$(JLINK_OPTS) --compare-host $(HOST_LIB) --report-dir $(REPORT)/$(BOARD) $(EUNIT_RUN_OPTS)

list:
	@$(EUNIT) list $(SUITE)

clean:
	@$(EUNIT) fs rm $(BUILD)

.PHONY: host target test test-host test-sim test-emu flash test-target list clean
