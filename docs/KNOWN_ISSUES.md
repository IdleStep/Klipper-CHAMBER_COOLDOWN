# Known issues and design decisions

The migration preserved Turbo's five-phase implementation, defects included. The
refinement pass that followed fixed them and deliberately diverges from that
baseline:

| Former defect | Resolution |
|---|---|
| Skipping hold/ramp (and the PASSIVE_ONLY, REST_5M_THEN_EX and IMMEDIATE_EX profiles) left the chamber heater target active, so phase 5 could never complete | Every path into phase 3 sets `CHAMBER TEMP=0`; completion does too |
| Phase-skip transitions and loop increments overwrote one another | Each tick performs one transition or one increment, through `_COOLDOWN_ENTER_PHASE` |
| `idle_timeout` (4800 s on Turbo) ended 120-minute holds and long 60-minute ramps | START_COOLDOWN raises the idle timeout to cover hold, ramp and rest when needed and restores the configured value on phase 3, completion or reset |
| Passive rest did not force exhaust off | Phase 3 entry sets `EXHAUST_FAN SPEED=0` when the rest is longer than 0 |
| `exhaust_enable` was ignored | `exhaust_enable: False` runs phase 4 at speed 0 (a missing key counts as True) |
| Invalid ramp timing could hold the heater forever; out-of-range exhaust speed stopped the loop mid-run; ramp steps could overshoot | START_COOLDOWN refuses invalid profiles; steps never go below the ramp target |
| Reporting used an undefined `c` test | Both arrows compare readings with the displayed target |

## By design

- COOLDOWN_RESET stops automation, clears the selection and restores an extended
  idle timeout, but leaves heaters and fans alone. PRINT_START and UI preheats call
  it after setting their own targets. Completion turns the chamber heater and
  controlled fans off.
- Report arrows show above / near / below target, not a temperature trend.
- The exhaust and chill phases have no separate deadline: the normal idle timeout
  applies once the heater is released.
- HIPS and PCTG keep their PASSIVE_ONLY fallback from Turbo's old retraction table.
  Changing intended profiles is separate work.

Isolated template checks do not establish full thermal or firmware equivalence.
