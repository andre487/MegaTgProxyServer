from pathlib import Path
import unittest
from ruamel.yaml import YAML


class CleanupSafetyTest(unittest.TestCase):
    def test_cleanup_is_scoped_and_preserves_data(self):
        directory = Path(__file__).resolve().parents[1]/'roles/docker_cleanup/tasks'
        allowed = {'io.megatg.managed=true', 'io.megatg.build=true'}
        prune_count = 0
        for path in directory.glob('*.yml'):
            for task in YAML(typ='safe').load(path):
                prune = task.get('community.docker.docker_prune')
                if prune:
                    prune_count += 1
                    self.assertFalse(prune.get('volumes', False))
                    self.assertFalse(prune.get('builder_cache', False))
                    for resource in ['containers', 'images', 'networks']:
                        if prune.get(resource):
                            label = prune[resource+'_filters']['label']
                            if label == '{{ item }}':
                                self.assertTrue(set(task['loop']) <= allowed)
                            else:
                                self.assertIn(label, allowed)
                for module, force in [('docker_image', 'force_absent'), ('docker_container', 'force_kill'), ('docker_network', 'force')]:
                    operation = task.get('community.docker.'+module, {})
                    if operation.get('state') == 'absent':
                        self.assertIs(operation[force], False)
                command = task.get('ansible.builtin.command', {}).get('argv', [])
                if command[:2] == ['docker', 'rm']:
                    self.assertNotIn('--force', command)
                    self.assertNotIn('-f', command)
                self.assertNotIn('community.docker.docker_volume', task)
        self.assertGreater(prune_count, 0)
