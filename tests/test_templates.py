"""Cooldown behavior tests in the shared Hardware Controls simulator.

Run with: python -m unittest discover -s tests -v
Needs Klipper-Hardware-Controls checked out as hardware-controls/ beside this
README (its tests/klipper_sim.py is the simulator) and Jinja2 3.1.6.
Klipper-Configs imports this module for Printer and wrap; keep those names.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Appended, not prepended: Hardware Controls has test modules with the same names.
sys.path.append(str(ROOT / 'hardware-controls' / 'tests'))

import klipper_sim  # noqa: E402
from klipper_sim import State, wrap  # noqa: E402,F401  (re-exported for Klipper-Configs)

COOLDOWN_MODULES = ['profiles', 'materials', 'engine']
# What README says cooldown needs from Hardware Controls.
REQUIRED_HARDWARE_MODULES = ['settings', 'fans', 'chamber']


class Printer(klipper_sim.Printer):
    """Simulated printer with Hardware Controls and, optionally, cooldown loaded."""

    def __init__(self, hardware=True, cooldown=True):
        super().__init__(hardware)
        if cooldown:
            for name in COOLDOWN_MODULES:
                self.load(ROOT / (name + '.cfg'))


class Templates(unittest.TestCase):
    def test_runs_with_only_required_hardware_modules(self):
        p = Printer(hardware=False, cooldown=False)
        for name in REQUIRED_HARDWARE_MODULES:
            p.load(klipper_sim.HW_ROOT / (name + '.cfg'))
        for name in COOLDOWN_MODULES:
            p.load(ROOT / (name + '.cfg'))
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        for _ in range(5):
            p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 5)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed, 1)

    def test_material_selection(self):
        p = Printer()
        cases = [('asa', 'HOLD_60M_COOL_EX'), ('PA6', 'HOLD_120M_COOL_NO_EX'), ('PLA', 'IMMEDIATE_EX'),
                 ('PCTG', 'PASSIVE_ONLY'), ('HIPS', 'PASSIVE_ONLY'), ('unknown', 'PASSIVE_ONLY')]
        for material, expected in cases:
            p.run('COOLDOWN_SELECT', MATERIAL=material)
            self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].cooldown_profile, expected)

    def test_explicit_profile_and_invalid(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='REST_5M_THEN_EX')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].cooldown_profile, 'REST_5M_THEN_EX')
        self.assertEqual(p.delays['_COOLDOWN_LOOP'], 5)
        p.run('COOLDOWN_RESET')
        p.run('START_COOLDOWN', PROFILE='INVALID')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 0)
        self.assertEqual(p.delays['_COOLDOWN_LOOP'], 0)

    def test_all_profiles_reach_final_phase(self):
        for profile in Printer().state['gcode_macro _COOLDOWN_PROFILES'].profiles:
            with self.subTest(profile=profile):
                p = Printer()
                p.run('START_COOLDOWN', PROFILE=profile)
                for _ in range(2400):
                    p.run('_COOLDOWN_LOOP')
                    if p.state['gcode_macro _COOLDOWN_VARS'].phase == 5:
                        break
                self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 5)
                p.state['heater_generic chamber'].temperature = 34.
                p.state['heater_bed'].temperature = 34.
                p.run('_COOLDOWN_LOOP')
                self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 0)
                self.assertEqual(p.delays['_COOLDOWN_LOOP'], 0)

    def test_override_missing_bed_fans(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.state['heater_generic chamber'].target = 50.
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 0)

    def test_sensor_only_chamber(self):
        p = Printer()
        p.state.pop('heater_generic chamber')
        p.state['temperature_sensor enclosure'] = wrap({'temperature': 50.})
        p.state['gcode_macro _HARDWARE_VARS'].chamber_heater = ''
        p.state['gcode_macro _HARDWARE_VARS'].chamber_sensor = 'temperature_sensor enclosure'
        p.run('START_COOLDOWN', PROFILE='PASSIVE_ONLY')
        for _ in range(8):
            p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 5)

    def test_alternate_hardware_names(self):
        p = Printer()
        hw = p.state['gcode_macro _HARDWARE_VARS']
        renames = [('chamber_heater', 'heater_generic chamber', 'heater_generic enclosure'),
                   ('bed_heater', 'heater_bed', 'heater_generic buildplate'),
                   ('exhaust_fan', 'fan_generic exhaust_fan', 'fan_generic vent')]
        for role, old, new in renames:
            p.state[new] = p.state.pop(old)
            hw[role] = new.split(' ', 1)[-1] if role != 'bed_heater' else new
        hw.chamber_sensor = 'heater_generic enclosure'
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        for _ in range(12):
            p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['fan_generic vent'].speed, 1)

    def run_until(self, p, phase, limit=2400):
        trace = []
        for _ in range(limit):
            p.run('_COOLDOWN_LOOP')
            cv = p.state['gcode_macro _COOLDOWN_VARS']
            trace.append((cv.phase, cv.phase_loops, p.state['heater_generic chamber'].target))
            if cv.phase in (0, phase):
                break
        return trace

    def custom_profile(self, p, **changes):
        table = p.state['gcode_macro _COOLDOWN_PROFILES'].profiles
        table['CUSTOM'] = wrap(dict(table['HOLD_60M_COOL_EX'], **changes))

    def test_heater_released_for_every_profile_and_start_target(self):
        for start in [55., 30., 0.]:
            for profile in Printer().state['gcode_macro _COOLDOWN_PROFILES'].profiles:
                with self.subTest(profile=profile, start=start):
                    p = Printer()
                    p.state['heater_generic chamber'].target = start
                    p.run('START_COOLDOWN', PROFILE=profile)
                    trace = self.run_until(p, 5)
                    self.assertEqual(trace[-1][0], 5)
                    self.assertTrue(all(target == 0 for phase, _, target in trace if phase >= 3))

    def test_one_transition_per_tick(self):
        profiles = Printer().state['gcode_macro _COOLDOWN_PROFILES'].profiles
        for profile, start in [(profile, start) for profile in profiles for start in [55., 30.]]:
            with self.subTest(profile=profile, start=start):
                p = Printer()
                p.state['heater_generic chamber'].target = start
                p.run('START_COOLDOWN', PROFILE=profile)
                previous = (1, 0)
                for phase, loops, _ in self.run_until(p, 5):
                    if phase == previous[0]:
                        self.assertEqual(loops, previous[1] + 1)
                    else:
                        self.assertGreater(phase, previous[0])
                        self.assertEqual(loops, 0)
                    previous = (phase, loops)

    def test_completion_turns_heater_and_fans_off(self):
        p = Printer()
        p.state['heater_generic chamber'].update(target=30., temperature=30.)
        p.state['heater_bed'].temperature = 30.
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 0)
        self.assertEqual(p.state['heater_generic chamber'].target, 0)
        self.assertIn('RESET_FANS', p.commands)

    def test_idle_timeout_extended_for_heated_phases_only(self):
        cases = [('HOLD_120M_COOL_NO_EX', 7200 + 13 * 120 + 600),
                 ('HOLD_60M_COOL_EX', 3600 + 13 * 120 + 600)]
        for profile, expected in cases:
            with self.subTest(profile=profile):
                p = Printer()
                p.run('START_COOLDOWN', PROFILE=profile)
                self.assertEqual(p.idle_timeout, expected)
                self.run_until(p, 3)
                self.assertEqual(p.idle_timeout, 4800)
                self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].idle_timeout_extended, 0)

    def test_idle_timeout_untouched_when_not_needed(self):
        cases = [(55., 'IMMEDIATE_EX'), (55., 'REST_5M_THEN_EX'), (30., 'HOLD_120M_COOL_NO_EX')]
        for start, profile in cases:
            with self.subTest(profile=profile, start=start):
                p = Printer()
                p.state['heater_generic chamber'].target = start
                p.run('START_COOLDOWN', PROFILE=profile)
                self.run_until(p, 5)
                p.run('COOLDOWN_RESET')
                self.assertFalse(any(c.startswith('SET_IDLE_TIMEOUT') for c in p.commands))

    def test_reset_restores_extended_idle_timeout_once(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='HOLD_120M_COOL_NO_EX')
        p.run('COOLDOWN_RESET')
        self.assertEqual(p.idle_timeout, 4800)
        p.idle_timeout = 43200.
        p.run('COOLDOWN_RESET')
        self.assertEqual(p.idle_timeout, 43200)

    def test_reset_leaves_heaters_and_fans(self):
        p = Printer()
        p.state['fan_generic exhaust_fan'].speed = .5
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('COOLDOWN_RESET')
        self.assertEqual(p.state['heater_generic chamber'].target, 55)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed, .5)
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].cooldown_ramp_step_seconds, 0)

    def test_passive_rest_turns_exhaust_off(self):
        p = Printer()
        p.state['fan_generic exhaust_fan'].speed = 1.
        p.run('START_COOLDOWN', PROFILE='REST_5M_THEN_EX')
        self.run_until(p, 3)
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 3)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed, 0)
        self.run_until(p, 5)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed, 1)

    def test_exhaust_enable_is_honored(self):
        p = Printer()
        self.custom_profile(p, chamber_hold_minutes=0, chamber_target_temp=0,
                            exhaust_enable=False, exhaust_fan_speed=1.0)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        self.assertEqual(self.run_until(p, 5)[-1][0], 5)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed, 0)

    def test_invalid_profiles_are_refused(self):
        cases = [dict(cooldown_ramp_step_seconds=2), dict(cooldown_ramp_step_c=0),
                 dict(exhaust_fan_speed=1.5), dict(chamber_hold_minutes=-1)]
        for changes in cases:
            with self.subTest(**changes):
                p = Printer()
                self.custom_profile(p, **changes)
                p.run('START_COOLDOWN', PROFILE='CUSTOM')
                self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase, 0)
                self.assertNotIn('_COOLDOWN_LOOP', p.delays)
                self.assertTrue(any('Invalid cooldown profile CUSTOM' in c for c in p.commands))

    def test_invalid_profile_lists_every_problem_in_one_line(self):
        # Klipper cuts a gcode line at ';', so the message must not contain one.
        p = Printer()
        self.custom_profile(p, chamber_hold_minutes=-1, exhaust_fan_speed=1.5)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        message = [c for c in p.commands if 'Invalid cooldown profile CUSTOM' in c][0]
        self.assertNotIn(';', message)
        self.assertIn('0 or more, exhaust_fan_speed must be', message)
        self.assertTrue(message.endswith('Cooldown not started."'))

    def test_ramp_step_does_not_overshoot(self):
        p = Printer()
        p.state['heater_generic chamber'].target = 44.
        self.custom_profile(p, chamber_hold_minutes=0, cooldown_ramp_step_c=5)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        targets = [t for phase, _, t in self.run_until(p, 3) if phase == 2]
        self.assertEqual(sorted(set(targets)), [42., 44.])

    def test_unused_phases_are_shown_as_skipped(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.run_until(p, 5)
        banners = [c for c in p.commands if 'Cooldown phase' in c]
        self.assertEqual([b.split('MSG="Cooldown phase ')[1][:3] for b in banners],
                         ['1/5', '2/5', '3/5', '4/5', '5/5'])
        self.assertIn('HOLD: skipped, profile has no hold', banners[0])
        self.assertIn('RAMP: skipped, profile has no ramp', banners[1])
        self.assertIn('rest skipped, profile has no rest', banners[2])
        for line in ['Hold complete', 'Rest complete', 'skipping ramp', '0.0°C every 0 s']:
            self.assertFalse(any(line in c for c in p.commands), line)

    def test_chamber_arrow_reported(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        report = [c for c in p.commands if c.startswith('RESPOND PREFIX="📃"')]
        self.assertTrue(report)
        self.assertIn('Chamber →', report[0])

    def test_bed_arrow_compares_with_displayed_target(self):
        p = Printer()
        p.state['heater_bed'].temperature = 34.
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        report = [c for c in p.commands if c.startswith('RESPOND PREFIX="📃"')]
        self.assertIn('Bed → 034.0/035.0', report[0])

    def test_status_names_phase(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('COOLDOWN_STATUS')
        self.assertIn('Phase: 1 HOLD', p.commands[-1])
        p.run('COOLDOWN_RESET')
        p.run('COOLDOWN_STATUS')
        self.assertIn('Phase: 0 IDLE', p.commands[-1])

    def test_unknown_material_uses_table_default(self):
        p = Printer()
        p.state['gcode_macro _COOLDOWN_MATERIALS'].filament_table['DEFAULT'] = 'IMMEDIATE_EX'
        p.run('COOLDOWN_SELECT', MATERIAL='UNOBTAINIUM')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].cooldown_profile, 'IMMEDIATE_EX')


if __name__ == '__main__':
    unittest.main()
