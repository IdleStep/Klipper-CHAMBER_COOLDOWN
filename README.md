# Klipper Chamber Cooldown

Material-selected five-phase chamber cooldown for Klipper and Kalico:
**hold → ramp → rest → exhaust → chill**. This repository owns the engine, six
profiles and the material map. It has no dependency on Klipper-Configs.

Cooldown API: **version 1**. See the [changelog](CHANGELOG.md) and
[known issues and design decisions](docs/KNOWN_ISSUES.md).

## Install

Requires [Klipper-Hardware-Controls](https://github.com/IdleStep/Klipper-Hardware-Controls)
API 1 (its settings, fans and chamber modules) and `[respond]`. Device
definitions stay in your printer configuration. Clone both repositories under
`~/printer_data/config`, then include each module once:

```ini
[include Klipper-Hardware-Controls/settings.cfg]
[include Klipper-Hardware-Controls/fans.cfg]
[include Klipper-Hardware-Controls/chamber.cfg]
[include hardware-local.cfg]
[include Klipper-Chamber-Cooldown/cooldown.cfg]
[include cooldown-local.cfg]
```

Hardware Controls' `hardware.cfg` can replace its three individual modules.
Local override files live outside both checkouts and load after the defaults.

## Configuration

Cooldown finds devices through Hardware Controls' `_HARDWARE_VARS`
(`chamber_heater`, `chamber_sensor`, `bed_heater`, `exhaust_fan`, `bed_fans`,
`external_pc`). For a chamber with only a sensor, set `chamber_heater` to `""` and
`chamber_sensor` to the full object name, for example
`"temperature_sensor chamber"`; hold and ramp are then skipped.

The one user setting is the completion temperature, in
[`examples/cooldown-local.cfg`](examples/cooldown-local.cfg):

```ini
[gcode_macro _COOLDOWN_VARS]
variable_chamber_cooled_temp: 35
```

## Commands

| Command | Behavior |
|---|---|
| `COOLDOWN_SELECT MATERIAL=ASA` | Picks the profile mapped to the material; unknown materials get the table's `DEFAULT` (PASSIVE_ONLY). |
| `START_COOLDOWN` | Starts the selected profile (PASSIVE_ONLY when none was selected). `PROFILE=NAME` overrides the selection and may be typed in any case. An unknown profile reports the known profile names, and an invalid one reports what is wrong with it; neither starts. |
| `COOLDOWN_STATUS` | Shows profile, phase number and name, and time in the phase. |
| `COOLDOWN_RESET` | Stops the cooldown, clears the selection and restores an idle timeout the cooldown raised. Heaters and fans are left as they are. |

Select the material again after a reset. Runtime state is not kept across
restarts.

## How a cooldown runs

The loop runs every 5 seconds. Each tick either stops the cooldown, moves to
the next phase, or advances the current one.

| Phase | What happens | Ends when |
|---|---|---|
| 1 HOLD | Chamber heater keeps its print target. | Hold time passes. Skipped when the profile has no hold. Without a chamber heater, or when the target is already below the ramp target, the cooldown goes straight to phase 3. |
| 2 RAMP | Target drops `cooldown_ramp_step_c` every `cooldown_ramp_step_seconds`, never below the ramp target. | Target reaches the ramp target. Skipped when the profile has none. |
| 3 REST | Chamber heater off; exhaust off if the rest is longer than 0. | Rest time passes. Skipped when the profile has no rest. |
| 4 EXHAUST | Exhaust, external_pc and bed fans set to the profile speed (0 when `exhaust_enable` is False). | On the next tick. |
| 5 CHILL | Waits; fans keep running. | Chamber and bed at or below `chamber_cooled_temp`. |

Every phase prints a numbered banner, so a cooldown always counts from 1/5 to
5/5. A phase the profile does not use says `skipped`.

At any phase, the cooldown **completes** (chamber heater and controlled fans off)
once chamber and bed are at or below `chamber_cooled_temp`. It **stops** without
touching heaters or fans if you change the chamber target, bed target, exhaust
or bed fan speed by hand, or a print starts (Klipper's `print_stats.state` becomes
`printing`; homing, probing and other moves do not stop it).

When hold, ramp and rest would outlast `[idle_timeout]`, START_COOLDOWN raises
the timeout for those phases and restores the configured value when the heater
is released. The normal idle timeout still limits the exhaust and chill phases.

## Profiles

| Profile | Hold | Ramp target | Rest | Exhaust | Materials |
|---|---:|---:|---:|---:|---|
| HOLD_120M_COOL_NO_EX | 120 min | 42°C | 0 | 0% | PA, PA6, PA6CF, PACF |
| HOLD_60M_COOL_EX | 60 min | 42°C | 0 | 100% | ABS, ABSCF, ASA, ASACF, ASAGF, PA12 |
| HOLD_30M_COOL_EX | 30 min | 42°C | 0 | 100% | none (use `PROFILE=`) |
| PASSIVE_ONLY | 0 | none | 0 | 0% | DEFAULT, PC, PCABS, PCABSCF, PCCF, PCTG, PETG, PETGCF, HIPS |
| REST_5M_THEN_EX | 0 | none | 5 min | 100% | TPU72D, TPU90A, TPU95A |
| IMMEDIATE_EX | 0 | none | 0 | 100% | PLA, PLA+, PLACF |

Ramping profiles step 1°C every 120 seconds. Field meanings and limits are
documented at the top of [`profiles.cfg`](profiles.cfg); START_COOLDOWN refuses a
ramp step at or below 0°C, a step time under 5 seconds, negative times, or an
exhaust speed outside 0.0 to 1.0. It also refuses a profile whose values are
missing or are not numbers (a value in quotes is text), and honors fractional
minutes (a 0.5 minute hold is 30 seconds). Because the loop ticks every 5
seconds, a ramp step time is rounded to the nearest 5 seconds (5 is the
minimum) and START_COOLDOWN says so; the banner and the idle-timeout estimate
use the rounded time. The material map keeps Turbo's effective
behavior, including HIPS and PCTG falling back to PASSIVE_ONLY.

## Integrating with print macros

Add guarded calls to existing macros rather than replacing them, and never write
`_COOLDOWN_VARS` directly:

| Where | Call |
|---|---|
| Print start, before material selection | `COOLDOWN_RESET` |
| Material handling | `COOLDOWN_SELECT MATERIAL={material}` |
| After print end and cancel actions | `START_COOLDOWN` |
| Idle timeout and UI shutdown or preheat | `COOLDOWN_RESET` |

```jinja
{% if 'gcode_macro START_COOLDOWN' in printer %}
  START_COOLDOWN
{% endif %}
```

## Messages

| Message | Meaning |
|---|---|
| `Cooldown started with profile: NAME` | START_COOLDOWN accepted the profile. |
| `Ramp step of N s runs as M s because the loop ticks every 5 s` | The profile's `cooldown_ramp_step_seconds` is not a multiple of 5; it runs at the nearest multiple. |
| `Cooldown phase N/5 NAME: ...` | A phase started. `skipped` means the profile does not use it. |
| `Cooldown HOLD: 2.0 of 60.0 min`, `Cooldown RAMP: ...`, `Cooldown REST: ...`, `Cooldown CHILL: ...` | Phase progress, every 2 minutes. |
| `Hold complete`, `Ramp target reached`, `Rest complete` | A phase finished. |
| `No chamber heater, skipping hold and ramp`, `Chamber target ... is below the ramp target ..., skipping hold and ramp` | The cooldown goes from phase 1 straight to phase 3. Banner 2/5 still prints, as `RAMP: skipped, no hold or ramp to run`. |
| `No exhaust, external_pc or bed_fans fan configured, skipping exhaust` | Phase 4 found none of the three fans to set. |
| `Chamber → 041.0/042.0 • Bed → 034.0/035.0 • Cycle 005` | Temperatures at the start of each phase and every 25 s: reading / displayed target. The displayed target is the heater target or `chamber_cooled_temp`, whichever is higher. Arrows compare the reading with it: above (↑), within 2°C below (→), further below (↓). |
| `Cooldown stopped: chamber, bed or fan settings were changed by hand` | A tracked target or fan speed changed outside the cooldown. |
| `Cooldown stopped: the printer started printing` | A print started (`print_stats.state` is `printing`) while the cooldown was running. |
| `Unknown cooldown profile: NAME. Known profiles: HOLD_120M_COOL_NO_EX, ...` | Nothing was started; the message lists the valid names (a quote mark in the typed name is shown as `'`). |
| `Invalid cooldown profile` | Nothing was started; the profile's values are wrong, and the message says which. |
| `Invalid cooldown profile NAME: profile names cannot contain quote marks. Cooldown not started.` | A profile in the table has `'` or `"` in its name. Rename it (names are `A-Z`, `0-9` and `_`). |
| `The profile for this material has a quote mark in its name, which is not allowed. Profile not changed.` | COOLDOWN_SELECT found a quote mark in the profile name the material map points to, and left the selection as it was. |
| `Invalid cooldown profile NAME: chamber_hold_minutes, exhaust_fan_speed must be numbers. Cooldown not started.` | A profile value is missing or is text; the message lists the keys. |
| `chamber_cooled_temp in _COOLDOWN_VARS must be a number. Cooldown not started.` | The setting is text or empty; nothing was started. Fix it in `cooldown-local.cfg`. |
| `chamber_sensor in _HARDWARE_VARS has no temperature. Cooldown not started.` (and the same for `bed_heater`) | The named object exists but is not a temperature device, so the name in `_HARDWARE_VARS` is wrong. |
| `Cooldown stopped: the chamber or bed temperature cannot be read` | A tick found a reading that is not a number, and reset the cooldown. |
| `Cooldown stopped: a value in _COOLDOWN_VARS is not valid` | A tick found a state value that is not a number, or a phase outside 1-5, and reset the cooldown. Something wrote to `_COOLDOWN_VARS` directly. |
| `Cooldown complete` | Heater and controlled fans are off. |

## Updates and rollback

Add [`examples/moonraker.conf`](examples/moonraker.conf) to `moonraker.conf`. It
follows tagged releases (`channel: stable`); use `channel: dev` to follow `main`.
Update while the printer is idle, keep overrides outside the checkout and record
the tested revisions of both repositories per printer. Cooldown API 1 works with
Hardware Controls API 1 from 1.0.0 on. Migration from the Klipper-Configs
cooldown is in [docs/MIGRATION.md](docs/MIGRATION.md).

## Tests

Check out Hardware Controls as `hardware-controls` beside this README (it
provides the shared test harness), then:

```sh
pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

- `tests/test_templates.py` simulates every profile and phase path.
- `tests/test_config_lint.py` checks the config files.
- `tests/test_klippy.py` runs `tests/klippy/*.gcode` in real Klipper and Kalico
  without hardware; it is skipped unless `KLIPPER_DIR`, `KLIPPY_DICT` and
  `KLIPPY_PYTHON` are set (see the CI workflow).

CI also runs the suite against Hardware Controls 1.0.0. None of this replaces a
real thermal run on the printer.
