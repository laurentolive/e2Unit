#################################
# Renesas RA4E1 (Cortex-M33 + FPU), e.g. R7FA4E10D2CFM
#
# The firmware runs on the reset clock (option-setting memory left erased:
# IWDT/WDT stopped). Cycle counts do not depend on the clock frequency.

BOARD_CPU_FLAGS := -mcpu=cortex-m33 -mthumb -mfloat-abi=hard -mfpu=fpv5-sp-d16
BOARD_LDSCRIPT  := $(EUNIT_ROOT)/boards/ra4e1/ra4e1.ld
BOARD_SRCS      :=
BOARD_DEFS      := -DEUNIT_BUF_WORDS=8192u -DEUNIT_CPU_HZ=0u
JLINK_DEVICE    := R7FA4E10D
BOARD_EMU_CPU   := cortex-m33
