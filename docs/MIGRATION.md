# Migration and rollback

Source: Turbo's live cooldown, based on Klipper-Configs blob
d666ca19f587960d4cb7ba801d8207da2812d998 (only trailing whitespace differs).
The old public implementation remains in Git history at
d8864740a9201492b0fb6dbfc61bc080c5fb13af.

## Install

1. Install Hardware Controls first.
2. Remove the old helper includes before adding the Hardware Controls ones.
   Never load both: the macros would be defined twice.
3. Replace the old cooldown include with `Klipper-CHAMBER_COOLDOWN/cooldown.cfg`.
4. Keep local overrides outside both checkouts.
5. Back up the root config files, the integration files you change, the saved
   state and the installed revisions, then restart while the printer is idle.

## How Klipper-Configs calls cooldown

- Material handling calls COOLDOWN_SELECT, guarded so it runs only when cooldown
  is installed, after its existing material fallback.
- Print start calls COOLDOWN_RESET, print end and cancel call START_COOLDOWN,
  and the idle timeout and KlipperScreen call COOLDOWN_RESET.
- The startup `disable_sensors` delayed gcode stays in Klipper-Configs' common
  macro file. The ENABLE_MOTION_SENSOR callback it schedules now lives in
  Hardware Controls and calls `MOTION_SENSOR ENABLE=1`; the 60-second schedule
  is unchanged.

The engine no longer matches the baseline tick for tick: the defects listed in
[known issues](KNOWN_ISSUES.md) were fixed after the migration. Public commands,
profile names and the material map are unchanged.

## Before publishing the Klipper-Configs cleanup

Check that the configuration loads and passes the smoke checks, then watch a
full ASA cooldown at production timings. Other printers must install Hardware
Controls before they take that cleanup; cooldown itself is optional, and every
call to it is guarded.

## Rollback

Restore the old root includes and every changed integration file together,
restart while the printer is idle and check that the original configuration
loads. Keep backups outside paths that active `[include]` patterns match. Do not
update unrelated printer components.
