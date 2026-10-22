"""Cooldown under real Klipper and Kalico (batch mode, no hardware).

Uses Hardware Controls' runner and test printer (tests/klippy_batch.py,
tests/klippy/printer.cfg). Timers never fire in batch mode, so the
_COOLDOWN_LOOP body is also defined as TEST_COOLDOWN_TICK for scripts to call.
Scripts set chamber_cooled_temp below zero because heaters read 0°C here.
"""
import pathlib
import unittest

import test_templates
from klippy_batch import SUPPORT_DIR, delayed_gcode_as_macro, run_script_files
from klipper_sim import HW_ROOT

SCRIPTS = pathlib.Path(__file__).resolve().parent / 'klippy'


def printer_cfg():
    return '\n'.join([
        (SUPPORT_DIR / 'printer.cfg').read_text(encoding='utf-8'),
        '[include Klipper-Chamber-Cooldown/cooldown.cfg]',
        '',
        delayed_gcode_as_macro(test_templates.ROOT / 'engine.cfg', '_COOLDOWN_LOOP', 'TEST_COOLDOWN_TICK'),
    ])


class RealKlipper(unittest.TestCase):
    def test_scripts(self):
        run_script_files(self, SCRIPTS, printer_cfg(), {
            'Klipper-Hardware-Controls': HW_ROOT,
            'Klipper-Chamber-Cooldown': test_templates.ROOT,
        })


if __name__ == '__main__':
    unittest.main()
