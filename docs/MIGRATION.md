# Migration and rollback

Source: Turbo's live cooldown, based on Klipper-Configs blob
d666ca19f587960d4cb7ba801d8207da2812d998 (only trailing whitespace differs).
The old public implementation remains in Git history at
d8864740a9201492b0fb6dbfc61bc080c5fb13af.

Install Hardware Controls first. Replace old helper includes before loading new
ones. Then replace the cooldown include. Keep overrides outside both checkouts.
Do not include duplicate definitions. Back up root files, changed integrations,
loaded state and installed revisions before restarting while inactive.

Core material selection uses guarded COOLDOWN_SELECT after existing fallback.
Print startup resets, end/cancel starts, and idle timeout/KlipperScreen reset.
Startup disable_sensors stays in the core common macro file. The scheduled
ENABLE_MOTION_SENSOR callback lives in Hardware Controls and calls MOTION_SENSOR
ENABLE=1; existing 60-second scheduling is unchanged.

The engine no longer matches that baseline tick for tick: the defects listed in
[known issues](KNOWN_ISSUES.md) were fixed after the migration. Public commands,
profile names and the material map are unchanged.

Verify loading and smoke checks, then observe a full ASA cooldown at production
timings before publishing the core cleanup. Other printers must install Hardware
Controls before adopting that cleanup; cooldown is optional and calls are guarded.

Rollback restores root includes and all changed integration files together, then
restarts while inactive and verifies the original configuration. Keep backups
outside active include patterns. Do not update unrelated printer components.
