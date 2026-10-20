#################################
# emath examples: run a goal on every suite, e.g.
#   make test          host, every suite
#   make -k test-sim   keep going after a failure
#   make target        one firmware per suite (+ the global one)
#   make test/sin      a single suite

SUITES := sin mulq15 atan2 pow isqrt rms all
GOALS  := test test-sim test-emu target test-target clean

define goal_rule
$(1): $(addprefix $(1)/,$(SUITES))
$(1)/%:
	@$$(MAKE) --no-print-directory -C tests/$$* $(1)
.PHONY: $(1)
endef

$(foreach g,$(GOALS),$(eval $(call goal_rule,$(g))))
