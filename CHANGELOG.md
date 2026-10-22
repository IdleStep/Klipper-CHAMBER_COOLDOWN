# Changelog

Versions follow the cooldown API: the major version changes only when a public
command, its parameters, a profile name or `chamber_cooled_temp` changes
incompatibly.

## 1.1.0

Requires Hardware Controls 1.0.0 or later.

### Fixed
- The chamber heater is turned off on every path into the rest phase and on
  completion; PASSIVE_ONLY, REST_5M_THEN_EX, IMMEDIATE_EX and skipped holds used
  to leave it heating so the cooldown never finished.
- One phase transition or increment per loop tick; skips no longer overwrite
  each other.
- Idle timeout is raised for long hold/ramp phases and restored afterwards.
- Passive rest turns the exhaust off; `exhaust_enable` is honored.
- Invalid profiles are refused at start; ramp steps never overshoot.
- A profile with several problems lists them all in one `Invalid cooldown
  profile` line. They were joined with `;`, which Klipper and Kalico treat as
  the start of a comment, so the message was cut off.
- Chamber progress arrow works, and the bed arrow compares with the displayed
  bed value (target or `chamber_cooled_temp`), as the chamber arrow does.

- START_COOLDOWN refuses a `chamber_cooled_temp` that is not a number (text,
  empty or a list). It used to start, raise the idle timeout and then raise on
  the first tick, which left the heater at its hold target with the loop dead
  until the idle timeout. A tick that finds a non-numeric state value or a phase
  outside 1-5 now stops the cooldown with `Cooldown stopped: a value in
  _COOLDOWN_VARS is not valid`.
- Banner 2/5 is printed when hold and ramp are skipped (no chamber heater, or a
  start target below the ramp target). The cooldown used to print 1/5, 3/5, 4/5
  and 5/5 on those paths; it now says `Cooldown phase 2/5 RAMP: skipped, no hold
  or ramp to run`.
- Phase 4 counts `bed_fans`. A printer with only bed fans was told `No exhaust
  or external_pc fan configured, skipping exhaust` and its bed fans were never
  set; the message now reads `No exhaust, external_pc or bed_fans fan
  configured, skipping exhaust` and appears only when none of the three exists.
- `exhaust_enable` in a profile must be `True` or `False` (`1` and `0` and a
  missing key work as before). Text such as `"False"` counted as true, so the
  fans ran at full speed; text and `None` are now refused with `exhaust_enable
  must be True or False`.
- Profile values must be present and numeric. `chamber_hold_minutes`,
  `passive_rest_minutes`, `chamber_target_temp`, `cooldown_ramp_step_c`,
  `cooldown_ramp_step_seconds` and `exhaust_fan_speed` used to be coerced
  silently: text or `None` read as 0 (a skipped phase, or fans set to 0), and a
  missing key raised a template error. START_COOLDOWN now refuses them in one
  `Invalid cooldown profile NAME: ... must be numbers` line. Text values such as
  `"60"`, which were accepted before, are refused too. The shipped profiles use
  numbers and are unaffected.
- Fractional hold and rest minutes are honored. They were truncated, so a hold
  of 0.5 minutes was no hold at all.
- A chamber with only a sensor has no tracked target. Changing
  `chamber_cooled_temp` during the cooldown no longer stops it with `changed by
  hand`.
- START_COOLDOWN refuses a `chamber_sensor` (when there is no chamber heater) or
  a `bed_heater` that has no `temperature`, which only happens when
  `_HARDWARE_VARS` names the wrong object. A tick that finds a reading that is
  not a number stops the cooldown with `Cooldown stopped: the chamber or bed
  temperature cannot be read`; the tick used to raise and strand the loop.
- A profile name with a quote mark (`O'NEIL`) is refused by START_COOLDOWN with
  `profile names cannot contain quote marks`, and COOLDOWN_SELECT refuses to
  store one. START used to fail half way through, after it had raised the idle
  timeout.
- COOLDOWN_SELECT trims whitespace around the material. `MATERIAL=" ASA"`
  silently selected the DEFAULT profile.

### Changed
- `START_COOLDOWN PROFILE=` accepts a profile name in any case (materials
  already did), and `Unknown cooldown profile` now lists the known profiles. A
  `"` in the typed name is shown as `'`; it used to make the message itself fail
  with `Malformed command`.
- Clearer messages; COOLDOWN_STATUS shows the phase name and time in phase.
- A phase the profile does not use still prints its numbered banner, marked
  skipped (`Cooldown phase 2/5 RAMP: skipped, profile has no ramp`), instead of
  zero durations followed by `Hold complete` or `skipping ramp`.
- Internal names: `_CHAMBER_SET_TARGET` is now `_COOLDOWN_SNAPSHOT`, and its
  recorded values are `seen_*` variables in `_COOLDOWN_VARS`.
- The profile table is `_COOLDOWN_PROFILES.profiles` (was `filament_table`). A
  local file that overrides the profile table must use the new name.
- COOLDOWN_SELECT falls back to the material table's `DEFAULT`.
- Moonraker example follows tagged releases.
- The repository is renamed Klipper-Chamber-Cooldown (was
  Klipper-CHAMBER_COOLDOWN). Clone it into
  `~/printer_data/config/Klipper-Chamber-Cooldown` and include
  `Klipper-Chamber-Cooldown/cooldown.cfg`. GitHub redirects the old URL.
- The Moonraker example names its section after the repository:
  `[update_manager Klipper-Chamber-Cooldown]`.
- Code, comments, tests, README and docs tidied, with no behavior change.
- Tests use Hardware Controls' shared harness, lint the configs, run in real
  Klipper and Kalico, and run against Hardware Controls 1.0.0.

## 1.0.0

Turbo's five-phase cooldown migrated from Klipper-Configs, behavior preserved.
