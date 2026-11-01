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

    def test_image_candidates_handle_skipped_register_results(self):
        from jinja2 import StrictUndefined
        from jinja2.nativetypes import NativeEnvironment
        tasks = YAML(typ='safe').load(Path(__file__).resolve().parents[1]/'roles/docker_cleanup/tasks/main.yml')
        expression = next(task['loop'] for task in tasks if task.get('loop_control', {}).get('loop_var') == 'tg_retired_image')
        env = NativeEnvironment(undefined=StrictUndefined)
        env.filters['unique'] = lambda values: list(dict.fromkeys(values))
        context = {'tg_local_mtproxy_images': {'stdout_lines': ['local']},
                   'tg_legacy_build_images': {'stdout_lines': []},
                   'tg_legacy_mtproxy_image': {'images': [{'Id': 'legacy'}]}}
        for result in [None, {'skipped': True, 'changed': False}, {'exists': False}]:
            with self.subTest(result=result):
                variables = dict(context)
                if result is not None:
                    variables.update(tg_previous_proxy=result, tg_cleanup_retired=result)
                self.assertEqual(env.from_string(expression).render(**variables), ['local', 'legacy'])
        context.update(tg_previous_proxy={'exists': True, 'container': {'Image': 'previous'}},
                       tg_cleanup_retired={'exists': True, 'container': {'Image': 'previous'}})
        self.assertEqual(env.from_string(expression).render(**context), ['previous', 'local', 'legacy'])
