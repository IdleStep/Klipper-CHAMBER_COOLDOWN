# Known issues and design decisions

The migration preserved Turbo's five-phase implementation, defects included. The
refinement pass that followed fixed them and deliberately diverges from that
baseline:

| Former defect | Resolution |
|---|---|
| Skipping hold/ramp (and the PASSIVE_ONLY, REST_5M_THEN_EX and IMMEDIATE_EX profiles) left the chamber heater target active, so phase 5 could never complete | Every path into phase 3 sets `CHAMBER TEMP=0`; completion does too |
| Phase-skip transitions and loop increments overwrote one another | Each tick performs one transition or one increment; every transition goes through `_COOLDOWN_ENTER_PHASE` |
| `idle_timeout` (4800 s on Turbo) ended 120-minute holds and long 60-minute ramps | START_COOLDOWN raises the idle timeout to cover hold, ramp and rest when needed and restores the configured value on phase 3, completion or reset |
| Passive rest did not force exhaust off | Phase 3 entry sets `EXHAUST_FAN SPEED=0` when the rest is longer than 0 |
| `exhaust_enable` was ignored | `exhaust_enable: False` runs phase 4 at speed 0 (a missing key counts as True) |
| Invalid ramp timing could hold the heater forever; out-of-range exhaust speed stopped the loop mid-run; ramp steps could overshoot | START_COOLDOWN refuses invalid profiles; steps never go below the ramp target |
| Reporting used an undefined `c` test | Both arrows compare readings with the displayed target |
| A text or empty `chamber_cooled_temp` was accepted; the first tick then raised, and Klipper does not reschedule a delayed gcode that raises, so the cooldown sat in its phase with the heater on until the idle timeout ended it | START_COOLDOWN refuses a `chamber_cooled_temp` that is not a number; a tick that finds a non-numeric state value or a phase outside 1-5 stops the cooldown with a message |

## By design

- COOLDOWN_RESET stops automation, clears the selection and restores an extended
  idle timeout, but leaves heaters and fans alone. PRINT_START and UI preheats call
  it after setting their own targets. Completion turns the chamber heater and
  controlled fans off.
- Report arrows show above / near / below the displayed target, not a
  temperature trend.
- A phase the profile does not use still prints its numbered banner, marked
  `skipped`, so the user sees every phase from 1/5 to 5/5.
- The exhaust and chill phases have no separate deadline: the normal idle timeout
  applies once the heater is released.
- HIPS and PCTG keep their PASSIVE_ONLY fallback from Turbo's old retraction table.
  Changing intended profiles is separate work.

- The print check reads `print_stats.state`, which only a file print sets (a
  printer without a `print_stats` object has no check). It replaced a test of
  `idle_timeout.state`, which can read `Printing` after a move, dwell or homing,
  not only during a print. Klipper-Configs' PRINT_START calls `COOLDOWN_RESET`
  first, so the check matters only for a print started some other way.
- The cooldown cannot read the idle timeout in force (a macro only sees the
  configured `[idle_timeout]` value). When a profile needs a longer timeout it
  sets one computed from the configured value, and at phase 3, on completion or
  on reset it writes the configured value back. A timeout you set yourself
  (`SET_IDLE_TIMEOUT`, `DISABLE_TIMEOUT`, a pause) is therefore replaced, and a
  longer one can be shortened during the hold and ramp.
- Completion needs the bed reading at or below `chamber_cooled_temp`. A bed
  target above it, left on after the print, stops the cooldown from completing;
  the exhaust fans then run until the idle timeout ends the session.
- `UPDATE_DELAYED_GCODE ID=_COOLDOWN_LOOP DURATION=0` typed by hand stops the
  loop without resetting the cooldown, so it still shows a running phase and the
  heater keeps its target. Use `COOLDOWN_RESET` to stop it.
- Profile and material names should be `A-Z`, `0-9` and `_`. A quote mark in a
  profile name is refused, because the name is stored with
  `SET_GCODE_VARIABLE` and a quote breaks that command. Mainline Klipper also
  cuts a `;`, `#` or `*` out of a command line before any macro sees it, even
  inside quotes (Kalico keeps them), so such a name could not be typed there.
  START_COOLDOWN and COOLDOWN_SELECT therefore refuse a name with a quote mark,
  semicolon, hash sign or asterisk, and show those characters as `?` in their
  messages.

Isolated template checks do not establish full thermal or firmware equivalence.
