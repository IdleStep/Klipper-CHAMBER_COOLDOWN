# Deferred behavior repairs

The migration preserves Turbo's five-phase implementation. Existing defects remain:

- Skipping the ramp can leave the chamber heater target active.
- Phase-skip transitions and loop increments can overwrite one another.
- The 120-minute hold can be interrupted by Turbo's 4800-second idle timeout.
- Passive rest does not force exhaust off on entry.
- `exhaust_enable` is not enforced; speed determines exhaust activation.
- Invalid custom ramp timing, target overshoot and an overall deadline need policy.
- Reporting uses an undefined `c` test; arrows do not measure temperature trends.
- Reset stops automation but does not turn off the chamber heater or fans.

The override diagnostic's direct accesses to absent optional hardware were removed;
the existing guarded readings still detect overrides and reset automation.

HIPS and PCTG preserve their effective PASSIVE_ONLY fallback because Turbo's old
retraction table lacked these materials. Changing intended profiles is separate work.

Isolated template checks do not establish full thermal or firmware equivalence.
