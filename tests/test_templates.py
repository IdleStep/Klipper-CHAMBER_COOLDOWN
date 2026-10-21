"""Render real Klipper templates and execute emitted macro commands in isolation.

Run with: python -m unittest discover -s tests -v
Requires Jinja2 3.1.6. No printer access and no hardware commands are transmitted.
"""
import ast
import configparser
import copy
import pathlib
import shlex
import unittest

import jinja2

ROOT = pathlib.Path(__file__).resolve().parents[1]
HW = ROOT / 'hardware-controls'

class State(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(key) from e

def wrap(value):
    if isinstance(value, dict):
        return State({k: wrap(v) for k,v in value.items()})
    if isinstance(value,list):
        return [wrap(v) for v in value]
    return value

class Printer:
    def __init__(self, hardware=True, cooldown=True):
        self.state = wrap({'idle_timeout': {'state': 'Idle'}, 'heater_generic chamber': {'target':55., 'temperature':55.},
            'heater_bed': {'target':0., 'temperature':80.}, 'fan': {'speed':0.},
            'fan_generic exhaust_fan': {'speed':0.}, 'fan_generic external_pc': {'speed':0.},
            'filament_motion_sensor motion_sensor': {'enabled':False},
            'filament_switch_sensor switch_sensor': {'enabled':False},
            'configfile': {'settings': {'fan': {'off_below':0.01}, 'stepper_x':{}, 'stepper_y':{}, 'idle_timeout': {'timeout':4800.}}}})
        self.idle_timeout=4800.
        self.templates={}
        self.commands=[]
        self.delays={}
        self.messages=[]
        self.env=jinja2.Environment(block_start_string='{%',block_end_string='%}',variable_start_string='{',variable_end_string='}')
        if hardware:
            for name in ['settings','fans','chamber','leds','dump_fan','sensors','release_steppers']:
                self.load(HW / (name+'.cfg'))
        if cooldown:
            for name in ['profiles','materials','engine']:
                self.load(ROOT / (name+'.cfg'))

    def load(self,path):
        cfg=configparser.RawConfigParser(delimiters=(':',),strict=True)
        cfg.read_string(path.read_text(encoding='utf-8'))
        for section in cfg.sections():
            if section.startswith(('gcode_macro ', 'delayed_gcode ')):
                kind,name=section.split(' ',1)
                self.templates[name.upper()]=self.env.from_string(cfg[section].get('gcode',''))
                if kind=='gcode_macro':
                    self.state[section]=wrap({k[9:]:ast.literal_eval(v) for k,v in cfg[section].items() if k.startswith('variable_')})

    def run(self,command,**params):
        def fail(message):
            raise ValueError(message)
        rendered=self.templates[command.upper()].render(printer=copy.deepcopy(self.state),params=State({k:str(v) for k,v in params.items()}),
            action_raise_error=fail,action_respond_info=lambda s:self.messages.append(s) or '')
        for line in rendered.splitlines():
            line=line.strip()
            if not line or line.startswith('#'):
                continue
            tokens=shlex.split(line)
            name=tokens[0].upper()
            args=dict(t.split('=',1) for t in tokens[1:] if '=' in t)
            self.commands.append(line)
            if name in self.templates:
                self.run(name,**args)
            elif name=='SET_GCODE_VARIABLE':
                self.state['gcode_macro '+args['MACRO']][args['VARIABLE']]=wrap(ast.literal_eval(args['VALUE']))
            elif name=='SET_IDLE_TIMEOUT':
                self.idle_timeout=float(args['TIMEOUT'])
            elif name=='UPDATE_DELAYED_GCODE':
                self.delays[args['ID']]=float(args['DURATION'])
            elif name=='SET_HEATER_TEMPERATURE':
                key='heater_generic '+args['HEATER'] if 'heater_generic '+args['HEATER'] in self.state else args['HEATER']
                self.state[key].target=float(args['TARGET'])
            elif name=='SET_FAN_SPEED':
                self.state['fan_generic '+args['FAN']].speed=float(args['SPEED'])
            elif name=='M106':
                self.state['fan'].speed=float(tokens[1][1:])/255
            elif name=='SET_FILAMENT_SENSOR':
                for kind in ['filament_motion_sensor ','filament_switch_sensor ']:
                    if kind+args['SENSOR'] in self.state:
                        self.state[kind+args['SENSOR']].enabled=bool(int(args['ENABLE']))
        return rendered

class Templates(unittest.TestCase):
    def test_all_templates_compile(self):
        p=Printer()
        p.load(HW/'optional/fan_tach_monitor.cfg')
        self.assertIn('CHECK_ALL_FANS',p.templates)

    def test_hardware_independent_and_inert(self):
        p=Printer(cooldown=False)
        self.assertEqual(p.commands,[])
        self.assertNotIn('gcode_macro _COOLDOWN_VARS',p.state)
        cfg=configparser.RawConfigParser(delimiters=(':',))
        cfg.read(HW/'sensors.cfg')
        self.assertNotIn('initial_duration',cfg['delayed_gcode ENABLE_MOTION_SENSOR'])
        self.assertNotIn('delayed_gcode disable_sensors',cfg)

    def test_delayed_sensor_calls_control(self):
        p=Printer(cooldown=False)
        p.run('ENABLE_MOTION_SENSOR')
        self.assertIn('MOTION_SENSOR ENABLE=1',p.commands)
        self.assertTrue(p.state['filament_motion_sensor motion_sensor'].enabled)

    def test_sensor_mapping_and_missing(self):
        p=Printer(cooldown=False)
        p.state['gcode_macro _HARDWARE_VARS'].motion_sensor='encoder'
        p.state['filament_motion_sensor encoder']=wrap({'enabled':False})
        p.run('MOTION_SENSOR',ENABLE=1)
        self.assertTrue(p.state['filament_motion_sensor encoder'].enabled)
        p.state.pop('filament_motion_sensor encoder')
        p.run('MOTION_SENSOR',ENABLE=0)

    def test_pause_resume_saved_sensor_variables(self):
        p=Printer(cooldown=False)
        self.assertEqual(p.state['gcode_macro MOTION_SENSOR'].fmotion_enabled,0)
        self.assertEqual(p.state['gcode_macro SWITCH_SENSOR'].fswitch_enabled,0)
        p.state['gcode_macro MOTION_SENSOR'].fmotion_enabled=1
        p.run('MOTION_SENSOR',ENABLE=p.state['gcode_macro MOTION_SENSOR'].fmotion_enabled)
        self.assertTrue(p.state['filament_motion_sensor motion_sensor'].enabled)

    def test_fans_do_not_require_exhaust(self):
        p=Printer(cooldown=False)
        p.state.pop('fan_generic exhaust_fan')
        p.state['fan_generic bed_fans']=wrap({'speed':0.})
        p.run('BED_FANS',SPEED=.4)
        p.run('EXTERNAL_PC',SPEED=.3)
        p.run('PART_COOLING',SPEED=50)
        self.assertEqual(p.state['fan_generic bed_fans'].speed,.4)
        self.assertEqual(p.state['fan_generic external_pc'].speed,.3)

    def test_reset_fans_and_optional_leds(self):
        p=Printer(cooldown=False)
        p.run('EXHAUST_FAN',SPEED=1)
        p.run('EXTERNAL_PC',SPEED=.5)
        p.run('RESET_FANS')
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed,0)
        self.assertEqual(p.state['fan_generic external_pc'].speed,0)
        for macro in ['LED_ON','LED_DIM','LED_OFF','DUMP_FAN']:
            p.run(macro)

    def test_configured_leds(self):
        p=Printer(cooldown=False)
        p.state['neopixel discostick']=State()
        p.state['output_pin daystick']=State()
        p.run('LED_DIM')
        self.assertIn('SET_PIN PIN=daystick VALUE=0.33',p.commands)
        self.assertTrue(any('RED=0.3098' in c for c in p.commands))

    def test_stepper_semantics_no_hardware(self):
        p=Printer(cooldown=False)
        p.run('RELEASE_Z')
        p.run('RELEASE_XY')
        self.assertIn('M84 Z',p.commands)
        self.assertIn('SET_STEPPER_ENABLE STEPPER=stepper_x ENABLE=0',p.commands)
        self.assertIn('SET_STEPPER_ENABLE STEPPER=stepper_y ENABLE=0',p.commands)

    def test_material_selection(self):
        p=Printer()
        for material,expected in [('asa','HOLD_60M_COOL_EX'),('PA6','HOLD_120M_COOL_NO_EX'),('PLA','IMMEDIATE_EX'),('PCTG','PASSIVE_ONLY'),('HIPS','PASSIVE_ONLY'),('unknown','PASSIVE_ONLY')]:
            p.run('COOLDOWN_SELECT',MATERIAL=material)
            self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].cooldown_profile,expected)

    def test_explicit_profile_and_invalid(self):
        p=Printer()
        p.run('START_COOLDOWN',PROFILE='REST_5M_THEN_EX')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].cooldown_profile,'REST_5M_THEN_EX')
        self.assertEqual(p.delays['_COOLDOWN_LOOP'],5)
        p.run('COOLDOWN_RESET')
        p.run('START_COOLDOWN',PROFILE='INVALID')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase,0)
        self.assertEqual(p.delays['_COOLDOWN_LOOP'],0)

    def test_all_profiles_reach_final_phase(self):
        for profile in Printer().state['gcode_macro _COOLDOWN_PROFILES'].filament_table:
            with self.subTest(profile=profile):
                p=Printer()
                p.run('START_COOLDOWN',PROFILE=profile)
                for i in range(2400):
                    p.run('_COOLDOWN_LOOP')
                    if p.state['gcode_macro _COOLDOWN_VARS'].phase==5:
                        break
                self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase,5)
                p.state['heater_generic chamber'].temperature=34.
                p.state['heater_bed'].temperature=34.
                p.run('_COOLDOWN_LOOP')
                self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase,0)
                self.assertEqual(p.delays['_COOLDOWN_LOOP'],0)

    def test_override_missing_bed_fans(self):
        p=Printer()
        p.run('START_COOLDOWN',PROFILE='HOLD_60M_COOL_EX')
        p.state['heater_generic chamber'].target=50.
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase,0)

    def test_sensor_only_chamber(self):
        p=Printer()
        p.state.pop('heater_generic chamber')
        p.state['temperature_sensor enclosure']=wrap({'temperature':50.})
        p.state['gcode_macro _HARDWARE_VARS'].chamber_heater=''
        p.state['gcode_macro _HARDWARE_VARS'].chamber_sensor='temperature_sensor enclosure'
        p.run('START_COOLDOWN',PROFILE='PASSIVE_ONLY')
        for i in range(8): p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase,5)

    def test_alternate_hardware_names(self):
        p=Printer()
        hw=p.state['gcode_macro _HARDWARE_VARS']
        for role,old,new in [('chamber_heater','heater_generic chamber','heater_generic enclosure'),('bed_heater','heater_bed','heater_generic buildplate'),('exhaust_fan','fan_generic exhaust_fan','fan_generic vent')]:
            p.state[new]=p.state.pop(old)
            hw[role]=new.split(' ',1)[-1] if role!='bed_heater' else new
        hw.chamber_sensor='heater_generic enclosure'
        p.run('START_COOLDOWN',PROFILE='IMMEDIATE_EX')
        for i in range(12): p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['fan_generic vent'].speed,1)

    def run_until(self,p,phase,limit=2400):
        trace=[]
        for i in range(limit):
            p.run('_COOLDOWN_LOOP')
            cv=p.state['gcode_macro _COOLDOWN_VARS']
            trace.append((cv.phase,cv.phase_loops,p.state['heater_generic chamber'].target))
            if cv.phase in (0,phase): break
        return trace

    def custom_profile(self,p,**changes):
        table=p.state['gcode_macro _COOLDOWN_PROFILES'].filament_table
        table['CUSTOM']=wrap(dict(table['HOLD_60M_COOL_EX'],**changes))

    def test_heater_released_for_every_profile_and_start_target(self):
        for start in [55.,30.,0.]:
            for profile in Printer().state['gcode_macro _COOLDOWN_PROFILES'].filament_table:
                with self.subTest(profile=profile,start=start):
                    p=Printer()
                    p.state['heater_generic chamber'].target=start
                    p.run('START_COOLDOWN',PROFILE=profile)
                    trace=self.run_until(p,5)
                    self.assertEqual(trace[-1][0],5)
                    self.assertTrue(all(target==0 for phase,_,target in trace if phase>=3))

    def test_one_transition_per_tick(self):
        profiles=Printer().state['gcode_macro _COOLDOWN_PROFILES'].filament_table
        for profile,start in [(profile,start) for profile in profiles for start in [55.,30.]]:
            with self.subTest(profile=profile,start=start):
                p=Printer()
                p.state['heater_generic chamber'].target=start
                p.run('START_COOLDOWN',PROFILE=profile)
                previous=(1,0)
                for phase,loops,_ in self.run_until(p,5):
                    if phase==previous[0]:
                        self.assertEqual(loops,previous[1]+1)
                    else:
                        self.assertGreater(phase,previous[0])
                        self.assertEqual(loops,0)
                    previous=(phase,loops)

    def test_completion_turns_heater_and_fans_off(self):
        p=Printer()
        p.state['heater_generic chamber'].update(target=30.,temperature=30.)
        p.state['heater_bed'].temperature=30.
        p.run('START_COOLDOWN',PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase,0)
        self.assertEqual(p.state['heater_generic chamber'].target,0)
        self.assertIn('RESET_FANS',p.commands)

    def test_idle_timeout_extended_for_heated_phases_only(self):
        for profile,expected in [('HOLD_120M_COOL_NO_EX',7200+13*120+600),('HOLD_60M_COOL_EX',3600+13*120+600)]:
            with self.subTest(profile=profile):
                p=Printer()
                p.run('START_COOLDOWN',PROFILE=profile)
                self.assertEqual(p.idle_timeout,expected)
                self.run_until(p,3)
                self.assertEqual(p.idle_timeout,4800)
                self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].idle_timeout_extended,0)

    def test_idle_timeout_untouched_when_not_needed(self):
        for start,profile in [(55.,'IMMEDIATE_EX'),(55.,'REST_5M_THEN_EX'),(30.,'HOLD_120M_COOL_NO_EX')]:
            with self.subTest(profile=profile,start=start):
                p=Printer()
                p.state['heater_generic chamber'].target=start
                p.run('START_COOLDOWN',PROFILE=profile)
                self.run_until(p,5)
                p.run('COOLDOWN_RESET')
                self.assertFalse(any(c.startswith('SET_IDLE_TIMEOUT') for c in p.commands))

    def test_reset_restores_extended_idle_timeout_once(self):
        p=Printer()
        p.run('START_COOLDOWN',PROFILE='HOLD_120M_COOL_NO_EX')
        p.run('COOLDOWN_RESET')
        self.assertEqual(p.idle_timeout,4800)
        p.idle_timeout=43200.
        p.run('COOLDOWN_RESET')
        self.assertEqual(p.idle_timeout,43200)

    def test_reset_leaves_heaters_and_fans(self):
        p=Printer()
        p.state['fan_generic exhaust_fan'].speed=.5
        p.run('START_COOLDOWN',PROFILE='HOLD_60M_COOL_EX')
        p.run('COOLDOWN_RESET')
        self.assertEqual(p.state['heater_generic chamber'].target,55)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed,.5)
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].cooldown_ramp_step_seconds,0)

    def test_passive_rest_turns_exhaust_off(self):
        p=Printer()
        p.state['fan_generic exhaust_fan'].speed=1.
        p.run('START_COOLDOWN',PROFILE='REST_5M_THEN_EX')
        self.run_until(p,3)
        p.run('_COOLDOWN_LOOP')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase,3)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed,0)
        self.run_until(p,5)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed,1)

    def test_exhaust_enable_is_honored(self):
        p=Printer()
        self.custom_profile(p,chamber_hold_minutes=0,chamber_target_temp=0,exhaust_enable=False,exhaust_fan_speed=1.0)
        p.run('START_COOLDOWN',PROFILE='CUSTOM')
        self.assertEqual(self.run_until(p,5)[-1][0],5)
        self.assertEqual(p.state['fan_generic exhaust_fan'].speed,0)

    def test_invalid_profiles_are_refused(self):
        for changes in [dict(cooldown_ramp_step_seconds=2),dict(cooldown_ramp_step_c=0),dict(exhaust_fan_speed=1.5),dict(chamber_hold_minutes=-1)]:
            with self.subTest(**changes):
                p=Printer()
                self.custom_profile(p,**changes)
                p.run('START_COOLDOWN',PROFILE='CUSTOM')
                self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].phase,0)
                self.assertNotIn('_COOLDOWN_LOOP',p.delays)
                self.assertTrue(any('Invalid cooldown profile CUSTOM' in c for c in p.commands))

    def test_ramp_step_does_not_overshoot(self):
        p=Printer()
        p.state['heater_generic chamber'].target=44.
        self.custom_profile(p,chamber_hold_minutes=0,cooldown_ramp_step_c=5)
        p.run('START_COOLDOWN',PROFILE='CUSTOM')
        targets=[t for phase,_,t in self.run_until(p,3) if phase==2]
        self.assertEqual(sorted(set(targets)),[42.,44.])

    def test_chamber_arrow_reported(self):
        p=Printer()
        p.run('START_COOLDOWN',PROFILE='HOLD_60M_COOL_EX')
        p.run('_COOLDOWN_LOOP')
        report=[c for c in p.commands if c.startswith('RESPOND PREFIX="📃"')]
        self.assertTrue(report)
        self.assertIn('Chamber →',report[0])

    def test_unknown_material_uses_table_default(self):
        p=Printer()
        p.state['gcode_macro _COOLDOWN_MATERIALS'].filament_table['DEFAULT']='IMMEDIATE_EX'
        p.run('COOLDOWN_SELECT',MATERIAL='UNOBTAINIUM')
        self.assertEqual(p.state['gcode_macro _COOLDOWN_VARS'].cooldown_profile,'IMMEDIATE_EX')

    def test_public_macros_have_descriptions(self):
        for name in ['materials','engine']:
            cfg=configparser.RawConfigParser(delimiters=(':',),strict=True)
            cfg.read(ROOT/(name+'.cfg'),encoding='utf-8')
            for section in cfg.sections():
                if section.startswith('gcode_macro ') and not section[12:].startswith('_'):
                    with self.subTest(macro=section):
                        self.assertTrue(cfg[section].get('description','').strip())

if __name__=='__main__':
    unittest.main()
