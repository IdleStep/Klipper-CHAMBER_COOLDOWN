# Klipper CHAMBER_COOLDOWN

Material-selected five-phase cooldown: **hold → ramp → passive rest → exhaust →
final cooling**. This repository owns the engine, six profiles and material map.
It has no dependency on Klipper-Configs.

## Installation

Requires [Klipper-Hardware-Controls](https://github.com/IdleStep/Klipper-Hardware-Controls)
API 1 (settings, fan and chamber modules), standard Klipper macros and `[respond]`.
Printer hardware definitions stay in your own configuration. Turbo's Kalico is
the initial deployment target. Read the [known issues](docs/KNOWN_ISSUES.md).

Clone both repositories under `~/printer_data/config`, then include:

```ini
[include Klipper-Hardware-Controls/settings.cfg]
[include Klipper-Hardware-Controls/fans.cfg]
[include Klipper-Hardware-Controls/chamber.cfg]
[include hardware-local.cfg]
[include Klipper-CHAMBER_COOLDOWN/cooldown.cfg]
[include cooldown-local.cfg]
```

For the full control bundle, use Hardware Controls' `hardware.cfg` instead of the
three individual files. Include each module once. Copy local examples outside
checkouts; load overrides after defaults. Cooldown uses mapped device names in
`_HARDWARE_VARS`. For sensor-only chambers, set `chamber_heater` to `""` and
`chamber_sensor` to the full temperature-sensor object name.

## Public commands

```gcode
COOLDOWN_SELECT MATERIAL=ASA
START_COOLDOWN
COOLDOWN_STATUS
COOLDOWN_RESET
# Explicit override:
START_COOLDOWN PROFILE=HOLD_60M_COOL_EX
```

Unknown material selects PASSIVE_ONLY. An unknown explicit profile reports an
error without scheduling a new run. Reset clears selection and stops the timer;
it does not shut down heaters or fans. Select material after resetting for a new
job. Runtime state is not persisted across restarts.

## Profiles

| Profile | Hold | Ramp target | Rest | Exhaust |
|---|---:|---:|---:|---:|
| HOLD_120M_COOL_NO_EX | 120 min | 42°C | 0 | 0% |
| HOLD_60M_COOL_EX | 60 min | 42°C | 0 | 100% |
| HOLD_30M_COOL_EX | 30 min | 42°C | 0 | 100% |
| PASSIVE_ONLY | 0 | skipped | 0 | 0% |
| REST_5M_THEN_EX | 0 | skipped | 5 min | 100% |
| IMMEDIATE_EX | 0 | skipped | 0 | 100% |

Hold/ramp profiles reduce target 1°C every 120 seconds. The loop runs every five
seconds. Completion requires chamber and bed readings at or below 35°C by default
and resets all fans configured through Hardware Controls. The material map keeps
Turbo's effective behavior, including HIPS/PCTG falling back to PASSIVE_ONLY.

## Integration and updates

Merge guarded calls into existing macros: COOLDOWN_RESET during startup before
material selection; COOLDOWN_SELECT MATERIAL={material} during material handling;
START_COOLDOWN after normal print end/cancel actions; COOLDOWN_RESET in idle/UI
shutdown. Do not replace whole print macros or write runtime variables directly.

```jinja
{% if 'gcode_macro START_COOLDOWN' in printer %}
  START_COOLDOWN
{% endif %}
```

See [migration and rollback](docs/MIGRATION.md) and
[Moonraker updater example](examples/moonraker.conf). Keep overrides outside
checkouts and update while inactive. Initial compatibility: cooldown API 1 with
Hardware Controls API 1; record exact tested revisions per printer.

## Tests

Clone Hardware Controls into `hardware-controls` beside this README for testing,
install `requirements-test.txt`, then run `python -m unittest discover -s tests -v`.
Tests render templates and simulate commands without contacting hardware. They
cover all profiles, mapped devices, optional fans, fallback, reset and completion;
they do not replace full firmware or thermal validation.
