import unittest

import test_templates  # noqa: F401  (puts hardware-controls/tests on sys.path)
from config_lint import lint
from test_templates import ROOT


class ConfigLint(unittest.TestCase):
    def test_config_files_are_clean(self):
        self.assertEqual(lint(ROOT, skip=('hardware-controls',)), {})


if __name__ == '__main__':
    unittest.main()
