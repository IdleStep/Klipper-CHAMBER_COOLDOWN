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
- Chamber progress arrow works, and the bed arrow compares with the displayed
  bed value (target or `chamber_cooled_temp`), as the chamber arrow does.

### Changed
- Clearer messages; COOLDOWN_STATUS shows the phase name and time in phase.
- Internal names: `_CHAMBER_SET_TARGET` is now `_COOLDOWN_SNAPSHOT`, and its
  recorded values are `seen_*` variables in `_COOLDOWN_VARS`.
- The profile table is `_COOLDOWN_PROFILES.profiles` (was `filament_table`). A
  local file that overrides the profile table must use the new name.
- COOLDOWN_SELECT falls back to the material table's `DEFAULT`.
- Moonraker example follows tagged releases.
- Tests use Hardware Controls' shared harness, lint the configs, run in real
  Klipper and Kalico, and run against Hardware Controls 1.0.0.

## 1.0.0

Turbo's five-phase cooldown migrated from Klipper-Configs, behavior preserved.
