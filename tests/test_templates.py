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
VARS = 'gcode_macro _COOLDOWN_VARS'
CHAMBER = 'heater_generic chamber'


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
            trace.append((cv.phase, cv.phase_loops, p.state[CHAMBER].target if CHAMBER in p.state else 0))
            if cv.phase in (0, phase):
                break
        return trace

    def custom_profile(self, p, **changes):
        table = p.state['gcode_macro _COOLDOWN_PROFILES'].profiles
        profile = dict(table['HOLD_60M_COOL_EX'], **changes)
        for key in [key for key, value in changes.items() if value is Ellipsis]:
            del profile[key]  # Ellipsis removes the key
        table['CUSTOM'] = wrap(profile)

    def messages(self, p):
        return [c for c in p.commands if c.startswith('RESPOND')]

    def banner_numbers(self, p):
        return [c.split('MSG="Cooldown phase ')[1][:3] for c in p.commands if 'Cooldown phase' in c]

    def sensor_printer(self, **reading):
        """A printer whose chamber has only a temperature sensor."""
        p = Printer()
        p.state.pop(CHAMBER)
        p.state['temperature_sensor enclosure'] = wrap(reading)
        p.state['gcode_macro _HARDWARE_VARS'].chamber_heater = ''
        p.state['gcode_macro _HARDWARE_VARS'].chamber_sensor = 'temperature_sensor enclosure'
        return p

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

    def test_completion_turns_every_heater_and_fan_off(self):
        for bed_heater in ['heater_bed', 'heater_generic buildplate']:
            with self.subTest(bed_heater=bed_heater):
                p = Printer()
                if bed_heater != 'heater_bed':
                    p.state[bed_heater] = p.state.pop('heater_bed')
                    p.state['gcode_macro _HARDWARE_VARS'].bed_heater = bed_heater
                p.state[CHAMBER].update(target=30., temperature=30.)
                p.state[bed_heater].update(target=30., temperature=30.)
                p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
                p.state['fan'].speed = 0.7  # part fan and external_pc are not tracked, so they are not a hand change
                p.state['fan_generic external_pc'].speed = 0.6
                p.run('_COOLDOWN_LOOP')
                self.assertEqual(p.state[VARS].phase, 0)
                self.assertEqual(p.state[CHAMBER].target, 0)
                self.assertEqual(p.state[bed_heater].target, 0)
                self.assertEqual(p.state['fan'].speed, 0)
                self.assertEqual(p.state['fan_generic external_pc'].speed, 0)
                self.assertEqual(p.state['fan_generic exhaust_fan'].speed, 0)

    def test_completion_leaves_a_bed_that_is_already_off_alone(self):
        p = Printer()
        p.state[CHAMBER].update(target=30., temperature=30.)
        p.state['heater_bed'].update(target=0., temperature=30.)
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state[VARS].phase, 0)
        self.assertFalse(any(c.startswith('SET_HEATER_TEMPERATURE HEATER=heater_bed') for c in p.commands))

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

    def test_rest_turns_external_pc_and_bed_fans_off_too(self):
        p = Printer()
        p.state['fan_generic bed_fans'] = wrap({'speed': 0.6})
        p.state['fan_generic external_pc'].speed = 0.6
        p.state['fan_generic exhaust_fan'].speed = 0.6
        p.run('START_COOLDOWN', PROFILE='REST_5M_THEN_EX')
        self.run_until(p, 3)
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state[VARS].phase, 3)
        for fan in ['exhaust_fan', 'external_pc', 'bed_fans']:
            self.assertEqual(p.state['fan_generic ' + fan].speed, 0, fan)
        for _ in range(10):  # the rest keeps running: its own fan changes are not a hand change
            p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state[VARS].phase, 3)
        self.run_until(p, 5)
        for fan in ['exhaust_fan', 'external_pc', 'bed_fans']:
            self.assertEqual(p.state['fan_generic ' + fan].speed, 1, fan)

    def test_fans_are_left_alone_when_there_is_no_rest(self):
        p = Printer()
        p.state['fan_generic external_pc'].speed = 0.6
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        self.run_until(p, 3)
        self.assertEqual(p.state[VARS].phase, 3)
        self.assertEqual(p.state['fan_generic external_pc'].speed, 0.6)

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
        self.assertIn('Invalid cooldown profile CUSTOM: ', message)
        self.assertIn('0 or more, exhaust_fan_speed must be', message)
        self.assertTrue(message.endswith('Cooldown not started."'))

    def test_negative_ramp_target_is_refused(self):
        p = Printer()
        self.custom_profile(p, chamber_target_temp=-5)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        self.assertEqual(p.state[VARS].phase, 0)
        self.assertNotIn('_COOLDOWN_LOOP', p.delays)
        self.assertFalse(any(c.startswith('SET_IDLE_TIMEOUT') for c in p.commands))
        message = [c for c in self.messages(p) if 'Invalid cooldown profile CUSTOM: ' in c]
        self.assertEqual(len(message), 1)
        self.assertIn('chamber_target_temp must be 0 or more', message[0])

    def test_zero_ramp_target_still_means_no_ramp(self):
        p = Printer()
        self.custom_profile(p, chamber_target_temp=0)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        self.assertEqual(p.state[VARS].phase, 1)

    def test_tiny_ramp_step_is_refused_only_when_ramping(self):
        for step, ramp_target, started in [(0.01, 42, False), (0.09, 42, False), (0.1, 42, True), (0.5, 42, True),
                                           (0.01, 0, True)]:
            with self.subTest(step=step, ramp_target=ramp_target):
                p = Printer()
                self.custom_profile(p, cooldown_ramp_step_c=step, chamber_target_temp=ramp_target)
                p.run('START_COOLDOWN', PROFILE='CUSTOM')
                self.assertEqual(p.state[VARS].phase, 1 if started else 0)
                refused = [c for c in self.messages(p) if 'cooldown_ramp_step_c must be 0.1 or more' in c]
                self.assertEqual(len(refused), 0 if started else 1)
                if not started:
                    self.assertFalse(any(c.startswith('SET_IDLE_TIMEOUT') for c in p.commands))

    def fan_minimum_printer(self, speed, **minimums):
        """Immediate-exhaust profile at `speed`; minimums maps a fan name to its fan_generic settings."""
        p = Printer()
        p.state['fan_generic bed_fans'] = wrap({'speed': 0.})
        for name, fan_settings in minimums.items():
            p.state['configfile'].settings['fan_generic ' + name] = wrap(fan_settings)
        self.custom_profile(p, chamber_hold_minutes=0, chamber_target_temp=0, cooldown_ramp_step_c=0,
                            cooldown_ramp_step_seconds=0, exhaust_fan_speed=speed)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        self.run_until(p, 5)
        return p

    def test_speed_below_a_fan_minimum_is_raised_and_reported(self):
        p = self.fan_minimum_printer(0.05, exhaust_fan={'min_power': 0.2}, external_pc={'min_power': None, 'off_below': 0.1})
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed, 0.2)
        self.assertEqual(p.state['fan_generic external_pc'].speed, 0.1)
        self.assertEqual(p.state['fan_generic bed_fans'].speed, 0.05)  # no minimum configured
        warnings = [c for c in self.messages(p) if 'below the fan minimum' in c]
        self.assertEqual(len(warnings), 1)
        self.assertIn('exhaust_fan (0.2), external_pc (0.1)', warnings[0])
        self.assertNotIn('bed_fans', warnings[0])
        self.assertEqual(p.state[VARS].phase, 5)  # the raised speeds are not seen as a hand change

    def test_speed_at_or_above_the_minimum_or_zero_is_left_alone(self):
        for speed, enable in [(0.2, True), (0.5, True), (1.0, True), (0.0, True), (0.05, False)]:
            with self.subTest(speed=speed, enable=enable):
                p = Printer()
                p.state['configfile'].settings['fan_generic exhaust_fan'] = wrap({'min_power': 0.2})
                self.custom_profile(p, chamber_hold_minutes=0, chamber_target_temp=0, cooldown_ramp_step_c=0,
                                    cooldown_ramp_step_seconds=0, exhaust_fan_speed=speed, exhaust_enable=enable)
                p.run('START_COOLDOWN', PROFILE='CUSTOM')
                self.run_until(p, 5)
                self.assertEqual(p.state['fan_generic exhaust_fan'].speed, speed if enable else 0)
                self.assertFalse(any('below the fan minimum' in c for c in self.messages(p)))

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

    def test_unknown_material_is_reported_but_known_and_blank_are_not(self):
        p = Printer()
        p.run('COOLDOWN_SELECT', MATERIAL='ASAA')
        notes = [c for c in self.messages(p) if 'Unknown material' in c]
        self.assertEqual(len(notes), 1)
        self.assertIn('Unknown material ASAA, using the DEFAULT profile PASSIVE_ONLY', notes[0])
        self.assertEqual(p.state[VARS].cooldown_profile, 'PASSIVE_ONLY')
        for material in ['ASA', 'asa', ' ASA ', 'DEFAULT', '', '  ', None]:
            with self.subTest(material=material):
                p = Printer()
                p.run('COOLDOWN_SELECT', **({} if material is None else {'MATERIAL': material}))
                self.assertFalse(any('Unknown material' in c for c in self.messages(p)))

    def test_unknown_material_with_a_quote_does_not_break_the_message(self):
        p = Printer()
        p.run('COOLDOWN_SELECT', MATERIAL='A"B')  # must not raise
        notes = [c for c in self.messages(p) if 'Unknown material' in c]
        self.assertEqual(len(notes), 1)
        self.assertIn("Unknown material A'B,", notes[0])

    def test_cooldown_select_refuses_a_profile_that_does_not_exist(self):
        for material, mapped in [('XX', 'NOPE'), ('DEFAULT', 'NOPE'), ('YY', None)]:
            with self.subTest(material=material, mapped=mapped):
                p = Printer()
                p.run('COOLDOWN_SELECT', MATERIAL='ASA')
                p.state['gcode_macro _COOLDOWN_MATERIALS'].filament_table[material] = mapped
                p.run('COOLDOWN_SELECT', MATERIAL=material)  # must not raise
                self.assertEqual(p.state[VARS].cooldown_profile, 'HOLD_60M_COOL_EX')  # unchanged
                refused = [c for c in self.messages(p) if 'which is not in the profile table' in c]
                self.assertEqual(len(refused), 1)
                self.assertIn('Profile not changed', refused[0])

    def test_cooldown_select_refuses_a_material_table_that_is_not_a_table(self):
        for broken in [['ASA', 'HOLD_60M_COOL_EX'], 'ASA', None, 5]:
            with self.subTest(table=broken):
                p = Printer()
                p.run('COOLDOWN_SELECT', MATERIAL='PLA')
                p.state['gcode_macro _COOLDOWN_MATERIALS'].filament_table = broken
                p.run('COOLDOWN_SELECT', MATERIAL='ASA')  # must not raise
                self.assertEqual(p.state[VARS].cooldown_profile, 'IMMEDIATE_EX')  # unchanged
                refused = [c for c in self.messages(p) if 'filament_table in _COOLDOWN_MATERIALS must be a table' in c]
                self.assertEqual(len(refused), 1)

    def test_cooldown_select_during_a_run_leaves_the_running_profile_alone(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('COOLDOWN_SELECT', MATERIAL='PLA')
        self.assertEqual(p.state[VARS].cooldown_profile, 'HOLD_60M_COOL_EX')
        self.assertEqual(sum('A cooldown is running' in c for c in self.messages(p)), 1)
        p.run('COOLDOWN_STATUS')
        self.assertIn('Profile: HOLD_60M_COOL_EX', p.commands[-1])
        p.run('COOLDOWN_RESET')
        p.run('COOLDOWN_SELECT', MATERIAL='PLA')
        self.assertEqual(p.state[VARS].cooldown_profile, 'IMMEDIATE_EX')
        self.assertEqual(sum('A cooldown is running' in c for c in self.messages(p)), 1)

    def test_cooldown_select_accepts_a_profile_in_any_case(self):
        p = Printer()
        p.state['gcode_macro _COOLDOWN_MATERIALS'].filament_table['XX'] = 'hold_60m_cool_ex'
        p.run('COOLDOWN_SELECT', MATERIAL='XX')
        self.assertEqual(p.state[VARS].cooldown_profile, 'hold_60m_cool_ex')
        p.run('START_COOLDOWN')
        self.assertEqual(p.state[VARS].phase, 1)

    def test_non_numeric_chamber_cooled_temp_is_refused_at_start(self):
        for value in ['35', None, [35]]:
            with self.subTest(value=value):
                p = Printer()
                p.state[VARS].chamber_cooled_temp = value
                p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
                self.assertEqual(p.state[VARS].phase, 0)
                self.assertFalse(any(c.startswith('SET_IDLE_TIMEOUT') for c in p.commands))
                self.assertTrue(any('chamber_cooled_temp' in c and 'must be a number' in c
                                    for c in self.messages(p)))

    def test_loop_stops_cleanly_on_invalid_state(self):
        cases = [('chamber_cooled_temp', None), ('chamber_cooled_temp', '35'), ('hold_loops', 'abc'),
                 ('ramp_step_loops', 'abc'), ('cooldown_ramp_step_c', 'abc'), ('ramp_chamber_target_temp', '42'),
                 ('phase', 7), ('phase', -1), ('phase', 'abc')]
        for var, value in cases:
            with self.subTest(var=var, value=value):
                p = Printer()
                p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
                p.state[VARS][var] = value
                p.run('_COOLDOWN_LOOP')  # must not raise
                self.assertEqual(p.state[VARS].phase, 0)
                self.assertEqual(p.delays['_COOLDOWN_LOOP'], 0)
                self.assertEqual(p.idle_timeout, 4800)
                self.assertTrue(any('not valid' in c for c in self.messages(p)))

    def test_skipped_hold_and_ramp_still_count_to_five(self):
        p = Printer()
        p.state[CHAMBER].target = 30.
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        self.run_until(p, 5)
        self.assertEqual(self.banner_numbers(p), ['1/5', '2/5', '3/5', '4/5', '5/5'])
        self.assertTrue(any('RAMP: skipped' in c for c in p.commands))

    def test_no_heater_still_counts_to_five(self):
        p = self.sensor_printer(temperature=50.)
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        self.run_until(p, 5)
        self.assertEqual(self.banner_numbers(p), ['1/5', '2/5', '3/5', '4/5', '5/5'])

    def test_bed_fans_only_printer_gets_its_fans(self):
        p = Printer()
        p.state.pop('fan_generic exhaust_fan')
        p.state.pop('fan_generic external_pc')
        p.state['fan_generic bed_fans'] = wrap({'speed': 0.})
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.run_until(p, 5)
        self.assertEqual(p.state['fan_generic bed_fans'].speed, 1)
        self.assertFalse(any('skipping exhaust' in c for c in p.commands))

    def test_no_fans_at_all_still_skips_with_a_message(self):
        p = Printer()
        p.state.pop('fan_generic exhaust_fan')
        p.state.pop('fan_generic external_pc')
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.run_until(p, 5)
        self.assertTrue(any('skipping exhaust' in c for c in p.commands))

    def test_exhaust_enable_text_is_refused(self):
        for value in ['False', 'no', '0', 'false', None]:
            with self.subTest(value=value):
                p = Printer()
                self.custom_profile(p, chamber_hold_minutes=0, chamber_target_temp=0, exhaust_enable=value)
                p.run('START_COOLDOWN', PROFILE='CUSTOM')
                self.assertEqual(p.state[VARS].phase, 0)
                self.assertTrue(any('exhaust_enable must be True or False' in c for c in self.messages(p)))

    def test_exhaust_enable_booleans_and_zero_one_still_work(self):
        for value, speed in [(True, 1.0), (False, 0.0), (1, 1.0), (0, 0.0), (Ellipsis, 1.0)]:
            with self.subTest(value=value):
                p = Printer()
                self.custom_profile(p, chamber_hold_minutes=0, chamber_target_temp=0, exhaust_enable=value)
                p.run('START_COOLDOWN', PROFILE='CUSTOM')
                self.assertEqual(p.state[VARS].phase, 1)
                self.assertEqual(p.state[VARS].exhaust_fan_speed, speed)

    def test_missing_or_non_numeric_profile_values_are_refused(self):
        cases = [('chamber_hold_minutes', 'abc'), ('passive_rest_minutes', None), ('chamber_target_temp', 'abc'),
                 ('cooldown_ramp_step_c', 'abc'), ('cooldown_ramp_step_seconds', None), ('exhaust_fan_speed', 'abc'),
                 ('chamber_hold_minutes', Ellipsis), ('exhaust_fan_speed', Ellipsis), ('chamber_hold_minutes', '60')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                p = Printer()
                self.custom_profile(p, **{key: value})
                p.run('START_COOLDOWN', PROFILE='CUSTOM')  # must not raise
                self.assertEqual(p.state[VARS].phase, 0)
                self.assertNotIn('_COOLDOWN_LOOP', p.delays)
                message = [c for c in self.messages(p) if 'Invalid cooldown profile CUSTOM' in c]
                self.assertEqual(len(message), 1)
                self.assertIn(key, message[0])
                self.assertNotIn(';', message[0])

    def test_profile_that_is_not_a_table_is_refused(self):
        for value in ['oops', None, [1, 2]]:
            with self.subTest(value=value):
                p = Printer()
                p.state['gcode_macro _COOLDOWN_PROFILES'].profiles['CUSTOM'] = value
                p.run('START_COOLDOWN', PROFILE='CUSTOM')
                self.assertEqual(p.state[VARS].phase, 0)

    def test_fractional_minutes_are_honoured(self):
        p = Printer()
        self.custom_profile(p, chamber_hold_minutes=60.9, passive_rest_minutes=0.5)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        self.assertEqual(p.state[VARS].hold_loops, 730)
        self.assertEqual(p.state[VARS].passive_loops, 6)

    def test_sensor_only_chamber_threshold_change_is_not_an_override(self):
        p = self.sensor_printer(temperature=50.)
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.run_until(p, 5)
        p.state[VARS].chamber_cooled_temp = 30
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state[VARS].phase, 5)
        self.assertFalse(any('changed by hand' in c for c in p.commands))

    def test_status_warns_when_the_loop_has_not_run_for_a_minute(self):
        p = Printer()
        p.state['toolhead'] = wrap({'estimated_print_time': 100.})
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        self.assertEqual(p.state[VARS].last_tick, 100.)
        p.state['toolhead'].estimated_print_time = 130.
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state[VARS].last_tick, 130.)
        p.state['toolhead'].estimated_print_time = 190.
        p.run('COOLDOWN_STATUS')
        self.assertFalse(any('cooldown loop last ran' in c for c in p.commands))
        p.state['toolhead'].estimated_print_time = 400.  # the loop was stopped by hand
        p.run('COOLDOWN_STATUS')
        warnings = [c for c in self.messages(p) if 'cooldown loop last ran 270 s ago' in c]
        self.assertEqual(len(warnings), 1)
        self.assertIn('Run COOLDOWN_RESET', warnings[0])
        p.run('_COOLDOWN_LOOP')
        p.run('COOLDOWN_STATUS')
        self.assertEqual(sum('cooldown loop last ran' in c for c in p.commands), 1)
        p.run('COOLDOWN_RESET')
        self.assertEqual(p.state[VARS].last_tick, 0)
        p.state['toolhead'].estimated_print_time = 900.
        p.run('COOLDOWN_STATUS')
        self.assertEqual(sum('cooldown loop last ran' in c for c in p.commands), 1)

    def test_status_without_a_toolhead_object_does_not_warn(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        p.run('COOLDOWN_STATUS')  # no 'toolhead' in printer: must not raise
        self.assertEqual(p.state[VARS].last_tick, 0)
        self.assertFalse(any('cooldown loop last ran' in c for c in p.commands))

    def test_a_toolhead_without_a_clock_does_not_raise(self):
        p = Printer()
        p.state['toolhead'] = wrap({'homed_axes': 'xyz'})  # Klipper-Configs' simulated toolhead has no clock
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        p.run('COOLDOWN_STATUS')
        self.assertEqual(p.state[VARS].phase, 1)
        self.assertEqual(p.state[VARS].last_tick, 0)

    def test_status_shows_a_question_mark_outside_the_phase_range(self):
        for phase in [-1, -6, 6, 9]:
            with self.subTest(phase=phase):
                p = Printer()
                p.state[VARS].phase = phase
                p.run('COOLDOWN_STATUS')
                self.assertIn('Phase: %d ?' % phase, p.commands[-1])

    def test_ramp_progress_line_is_rounded(self):
        p = Printer()
        p.state[CHAMBER].target = 45.3
        self.custom_profile(p, chamber_hold_minutes=0, cooldown_ramp_step_c=0.1, cooldown_ramp_step_seconds=5)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        self.run_until(p, 3)
        progress = [c for c in p.commands if 'Cooldown RAMP: chamber target' in c]
        self.assertTrue(progress)
        for line in progress:
            self.assertRegex(line, r'chamber target \d+\.\d°C')

    def test_material_name_is_trimmed(self):
        for material in [' ASA', 'ASA ', '  asa\t']:
            with self.subTest(material=material):
                p = Printer()
                p.run('COOLDOWN_SELECT', MATERIAL=material)
                self.assertEqual(p.state[VARS].cooldown_profile, 'HOLD_60M_COOL_EX')

    def test_profile_name_in_any_case_and_known_profiles_listed(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='immediate_ex')
        self.assertEqual(p.state[VARS].cooldown_profile, 'IMMEDIATE_EX')
        self.assertEqual(p.state[VARS].phase, 1)
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='NOPE')
        message = [c for c in self.messages(p) if 'Unknown cooldown profile' in c]
        self.assertEqual(len(message), 1)
        self.assertIn('Known profiles: HOLD_120M_COOL_NO_EX, HOLD_30M_COOL_EX', message[0])
        self.assertNotIn(';', message[0])

    def test_double_quote_in_profile_name_does_not_break_the_message(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='a"b')  # raised a Malformed command before
        self.assertEqual(p.state[VARS].phase, 0)
        self.assertTrue(any("a'b" in c for c in self.messages(p)))

    def test_sensor_without_temperature_is_refused_at_start(self):
        p = self.sensor_printer()  # an object with no temperature key
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.assertEqual(p.state[VARS].phase, 0)
        self.assertNotIn('_COOLDOWN_LOOP', p.delays)
        self.assertTrue(any('chamber_sensor' in c and 'has no temperature' in c for c in self.messages(p)))

    def test_bed_heater_without_temperature_is_refused_at_start(self):
        p = Printer()
        p.state['heater_bed'].pop('temperature')
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.assertEqual(p.state[VARS].phase, 0)
        self.assertTrue(any('bed_heater' in c and 'has no temperature' in c for c in self.messages(p)))

    def test_loop_stops_cleanly_when_a_reading_disappears(self):
        p = self.sensor_printer(temperature=50.)
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        self.assertEqual(p.state[VARS].phase, 1)
        p.state['temperature_sensor enclosure'] = wrap({})
        p.run('_COOLDOWN_LOOP')  # must not raise
        self.assertEqual(p.state[VARS].phase, 0)
        self.assertEqual(p.delays['_COOLDOWN_LOOP'], 0)
        self.assertTrue(any('cannot be read' in c for c in self.messages(p)))

    def test_a_working_sensor_still_starts(self):
        p = self.sensor_printer(temperature=50.)
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.assertEqual(p.state[VARS].phase, 1)

    def test_profile_names_with_quotes_are_refused_at_start(self):
        for name in ["O'NEIL", 'A"B']:
            with self.subTest(name=name):
                p = Printer()
                table = p.state['gcode_macro _COOLDOWN_PROFILES'].profiles
                table[name] = wrap(dict(table['HOLD_60M_COOL_EX']))
                p.run('START_COOLDOWN', PROFILE=name)  # must not raise
                self.assertEqual(p.state[VARS].phase, 0)
                self.assertNotIn('_COOLDOWN_LOOP', p.delays)
                self.assertEqual(p.state[VARS].cooldown_profile, 'PASSIVE_ONLY')
                self.assertFalse(any(c.startswith('SET_IDLE_TIMEOUT') for c in p.commands))
                message = [c for c in self.messages(p) if 'cannot contain quote marks' in c]
                self.assertEqual(len(message), 1)
                self.assertNotIn('"A"B"', message[0])

    def test_cooldown_select_refuses_a_profile_with_a_quote(self):
        for name in ["O'NEIL", 'A"B']:
            with self.subTest(name=name):
                p = Printer()
                p.state['gcode_macro _COOLDOWN_MATERIALS'].filament_table['XX'] = name
                p.run('COOLDOWN_SELECT', MATERIAL='XX')  # must not raise
                self.assertEqual(p.state[VARS].cooldown_profile, 'PASSIVE_ONLY')
                self.assertTrue(any('quote mark' in c for c in self.messages(p)))

    def test_semicolon_hash_and_asterisk_in_profile_names_are_refused(self):
        for name in ['A;B', 'A#B', 'A*B']:
            with self.subTest(name=name):
                p = Printer()
                table = p.state['gcode_macro _COOLDOWN_PROFILES'].profiles
                table[name] = wrap(dict(table['HOLD_60M_COOL_EX']))
                p.run('START_COOLDOWN', PROFILE=name)  # must not raise
                self.assertEqual(p.state[VARS].phase, 0)
                self.assertNotIn('_COOLDOWN_LOOP', p.delays)
                self.assertFalse(any(c.startswith('SET_IDLE_TIMEOUT') for c in p.commands))
                refused = [c for c in self.messages(p) if 'cannot contain quote marks, semicolons, hash signs or asterisks' in c]
                self.assertEqual(len(refused), 1)
                self.assertNotIn(';', refused[0].split('MSG=')[1])
                p.state['gcode_macro _COOLDOWN_MATERIALS'].filament_table['XX'] = name
                p.run('COOLDOWN_SELECT', MATERIAL='XX')
                self.assertEqual(p.state[VARS].cooldown_profile, 'PASSIVE_ONLY')
                self.assertTrue(any('asterisk in its name' in c for c in self.messages(p)))
                p.run('START_COOLDOWN', PROFILE='NOPE')  # the unknown-profile list echoes the bad key
                listing = [c for c in self.messages(p) if 'Known profiles' in c][0].split('MSG=')[1]
                self.assertNotIn(';', listing)
                self.assertIn('A?B', listing)

    def test_plain_profile_names_still_work(self):
        p = Printer()
        p.state['gcode_macro _COOLDOWN_MATERIALS'].filament_table['XX'] = 'HOLD_60M_COOL_EX'
        p.run('COOLDOWN_SELECT', MATERIAL='XX')
        self.assertEqual(p.state[VARS].cooldown_profile, 'HOLD_60M_COOL_EX')

    def test_ramp_step_seconds_is_rounded_to_five_and_reported(self):
        for seconds, real in [(7, 5), (8, 10), (9, 10), (12, 10), (13, 15), (5, 5), (10, 10), (120, 120)]:
            with self.subTest(seconds=seconds):
                p = Printer()
                self.custom_profile(p, cooldown_ramp_step_seconds=seconds)
                p.run('START_COOLDOWN', PROFILE='CUSTOM')
                self.assertEqual(p.state[VARS].phase, 1)
                self.assertEqual(p.state[VARS].cooldown_ramp_step_seconds, real)
                self.assertEqual(p.state[VARS].ramp_step_loops, real // 5)
                notes = [c for c in self.messages(p) if 'runs as' in c]
                self.assertEqual(len(notes), 0 if seconds == real else 1)
                if notes:
                    self.assertIn('%d s runs as %d s' % (seconds, real), notes[0])

    def test_ramp_step_below_five_is_still_refused(self):
        for seconds in [0, 4, 4.9]:
            with self.subTest(seconds=seconds):
                p = Printer()
                self.custom_profile(p, cooldown_ramp_step_seconds=seconds)
                p.run('START_COOLDOWN', PROFILE='CUSTOM')
                self.assertEqual(p.state[VARS].phase, 0)

    def test_step_seconds_is_left_alone_when_there_is_no_ramp(self):
        p = Printer()
        self.custom_profile(p, chamber_target_temp=0, cooldown_ramp_step_seconds=3)
        p.run('START_COOLDOWN', PROFILE='CUSTOM')
        self.assertEqual(p.state[VARS].phase, 1)
        self.assertFalse(any('runs as' in c for c in self.messages(p)))

    def test_print_check_uses_print_stats_not_idle_timeout(self):
        p = Printer()
        p.state['print_stats'] = wrap({'state': 'standby'})
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.run_until(p, 5)
        for _ in range(8):
            p.state['idle_timeout'].state = 'Printing'  # G4, homing, QGL, LOAD_FILAMENT ...
            p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state[VARS].phase, 5)
        p.state['print_stats'].state = 'printing'
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state[VARS].phase, 0)
        self.assertTrue(any('started printing' in c for c in self.messages(p)))

    def test_print_check_without_print_stats_object(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='IMMEDIATE_EX')
        self.run_until(p, 5)
        p.run('_COOLDOWN_LOOP')  # no 'print_stats' in printer: must not raise
        self.assertEqual(p.state[VARS].phase, 5)

    def test_reset_reports_a_running_cooldown_only(self):
        p = Printer()
        p.run('COOLDOWN_RESET')
        self.assertFalse(any('Cooldown reset' in c for c in p.commands))
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('COOLDOWN_RESET')
        self.assertEqual(sum('Cooldown reset' in c for c in p.commands), 1)

    def test_engine_stops_do_not_add_a_reset_line(self):
        def changed_by_hand(p):
            p.state[CHAMBER].target = 50.

        def invalid_value(p):
            p.state[VARS].hold_loops = 'abc'

        def unreadable_sensor(p):
            p.state[CHAMBER].pop('temperature')

        def printing(p):
            p.state['print_stats'] = wrap({'state': 'printing'})

        for stop, change in [('changed by hand', changed_by_hand), ('not valid', invalid_value),
                             ('cannot be read', unreadable_sensor), ('started printing', printing)]:
            with self.subTest(stop=stop):
                p = Printer()
                p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
                change(p)
                p.run('_COOLDOWN_LOOP')
                self.assertEqual(p.state[VARS].phase, 0)
                self.assertTrue(any(stop in c for c in p.commands))
                self.assertFalse(any('Cooldown reset' in c for c in p.commands))

    def test_hand_change_stop_names_what_changed_and_leaves_it_alone(self):
        def chamber(p):
            p.state[CHAMBER].target = 0.

        def bed(p):
            p.state['heater_bed'].target = 60.

        def exhaust(p):
            p.state['fan_generic exhaust_fan'].speed = 0.5

        def bed_fans(p):
            p.state['fan_generic bed_fans'].speed = 0.5

        for name, change in [('chamber target', chamber), ('bed target', bed), ('exhaust fan speed', exhaust),
                             ('bed fans speed', bed_fans)]:
            for profile in ['HOLD_60M_COOL_EX', 'IMMEDIATE_EX']:
                with self.subTest(changed=name, profile=profile):
                    p = Printer()
                    p.state['fan_generic bed_fans'] = wrap({'speed': 0.})
                    p.run('START_COOLDOWN', PROFILE=profile)
                    if profile == 'HOLD_60M_COOL_EX':
                        self.run_until(p, 2, limit=1)  # still in HOLD, a RAMP would have followed
                    change(p)
                    before = len(p.commands)
                    p.run('_COOLDOWN_LOOP')
                    self.assertEqual(p.state[VARS].phase, 0)
                    self.assertEqual(p.delays['_COOLDOWN_LOOP'], 0)  # the loop is cancelled
                    stop = [c for c in p.commands[before:] if 'changed by hand' in c]
                    self.assertEqual(len(stop), 1)
                    self.assertIn('hand (%s).' % name, stop[0])
                    self.assertIn('cancelled', stop[0])
                    self.assertNotIn(';', stop[0].split('MSG=')[1])
                    self.assertFalse(any(c.startswith(('CHAMBER', 'EXHAUST_FAN', 'BED_FANS', 'RESET_FANS'))
                                         for c in p.commands[before:]))

    def test_hand_change_stop_lists_every_change(self):
        p = Printer()
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.state[CHAMBER].target = 0.
        p.state['heater_bed'].target = 60.
        p.run('_COOLDOWN_LOOP')
        stop = [c for c in p.commands if 'changed by hand' in c][0]
        self.assertIn('(chamber target, bed target)', stop)

    def test_completion_does_not_add_a_reset_line(self):
        p = Printer()
        p.state[CHAMBER].update(target=30., temperature=30.)
        p.state['heater_bed'].temperature = 30.
        p.run('START_COOLDOWN', PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        self.assertTrue(any('Cooldown complete' in c for c in p.commands))
        self.assertFalse(any('Cooldown reset' in c for c in p.commands))


if __name__ == '__main__':
    unittest.main()
