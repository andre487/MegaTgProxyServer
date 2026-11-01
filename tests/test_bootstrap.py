import unittest
from unittest.mock import patch

import bootstrap


class BootstrapTest(unittest.TestCase):
    def test_requires_explicit_hosts(self):
        with self.assertRaisesRegex(ValueError, 'exact host names'):
            bootstrap.bootstrap(None, None)

    @patch('bootstrap.subprocess.run')
    def test_admin_probe_uses_fresh_key_connection_and_sudo(self, run):
        run.return_value.returncode = 0
        host = {'ansible_host': 'example.com', 'tg_admin': {'user': 'deploy', 'private_key_file': '/tmp/key'}}
        self.assertTrue(bootstrap.check_admin(host))
        command = run.call_args.args[0]
        self.assertIn('ControlPath=none', command)
        self.assertIn('BatchMode=yes', command)
        self.assertEqual(command[-1], 'sudo -n true')
        run.return_value.returncode = 255
        self.assertFalse(bootstrap.check_admin(host))

    @patch('bootstrap.check_admin', side_effect=[False, False])
    @patch('bootstrap.subprocess.check_output')
    @patch('bootstrap.subprocess.run')
    def test_failed_new_access_keeps_policy_unchanged(self, run, output, probe):
        import json
        import tempfile
        from pathlib import Path
        from ruamel.yaml import YAML
        host = {'ansible_host': 'example.com', 'tg_admin': {
            'user': 'deploy', 'public_key': 'ssh-ed25519 TEST',
            'private_key_file': '/tmp/key', 'bootstrap_user': 'root'}}
        output.side_effect = [json.dumps({'_meta': {'hostvars': {'node': host}}}).encode(),
                              'ssh-ed25519 TEST\n']
        phases = []
        def phase(command, **kwargs):
            data = YAML().load(Path(command[2]))
            self.assertEqual(data['all']['hosts']['node']['ansible_python_interpreter'], '/usr/bin/python3')
            phases.append(data['all']['hosts']['node']['tg_bootstrap_phase'])
            return type('Result', (), {'returncode': 0})()
        run.side_effect = phase
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inventory.yml'
            path.write_text('unchanged')
            with self.assertRaisesRegex(ValueError, 'bootstrap remains pending'):
                bootstrap.bootstrap(path, 'node')
            self.assertEqual(path.read_text(), 'unchanged')
        self.assertEqual(phases, ['account'])
