"""Installer entry points must work when stdin is the downloaded script."""
from pathlib import Path
import subprocess
import unittest


class InstallerTests(unittest.TestCase):
    def run_installer(self, *args):
        script = Path(__file__).resolve().parents[1] / 'install.sh'
        return subprocess.run(['bash', '-s', '--', *args], input=script.read_text(),
                              text=True, capture_output=True, timeout=10)

    def test_piped_help_needs_neither_root_nor_terminal(self):
        result = self.run_installer('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('MegaTgProxyServer/main/install.sh', result.stdout)
        self.assertIn('MEGATG_REF', result.stdout)

    def test_unknown_argument_fails_before_installation(self):
        result = self.run_installer('--unknown')
        self.assertEqual(result.returncode, 2)
        self.assertIn('Unexpected arguments', result.stderr)
