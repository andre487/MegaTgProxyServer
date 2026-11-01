import json
from pathlib import Path
import tomllib
import unittest
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]


class ConfigTemplatesTest(unittest.TestCase):
    def test_mtg_templates_preserve_transport_and_tuning(self):
        env = Environment(loader=FileSystemLoader(ROOT/'roles/proxy/templates'), undefined=StrictUndefined)
        env.filters['to_json'] = json.dumps
        for template in ['mtg.toml.j2', 'mtg-tuned.toml.j2']:
            for egress in ['direct', 'ssh']:
                with self.subTest(template=template, egress=egress):
                    config = tomllib.loads(env.get_template(template).render(
                        tg_secret_full='ee'+'1'*32+'example.com'.encode().hex(),
                        tg_egress=egress, tg_gateway='172.30.44.1', tg_ssh_socks_port=1080,
                        tg_mtg_debug=True, tg_mtg_prefer_ip='prefer-ipv4', tg_mtg_auto_update=True,
                        tg_mtg_http_timeout='20s', tg_mtg_idle_timeout='1m'))
                    self.assertTrue(config['secret'].startswith('ee'))
                    self.assertEqual(config['bind-to'], '0.0.0.0:3128')
                    self.assertEqual(config['network']['proxies'], ['socks5://172.30.44.1:1080'] if egress=='ssh' else [])
                    self.assertEqual(config['stats']['prometheus']['bind-to'], '0.0.0.0:3129')
                    if template=='mtg-tuned.toml.j2':
                        self.assertEqual(config['network']['timeout']['http'], '20s')
                        self.assertEqual(config['network']['timeout']['idle'], '1m')
                        self.assertTrue(config['defense']['anti-replay']['enabled'])
                        self.assertTrue(config['defense']['blocklist']['enabled'])

    def test_file_configuration_is_not_declared_in_tasks_or_defaults(self):
        yaml = YAML(typ='safe')
        def check(node, path):
            if isinstance(node, dict):
                if 'ansible.builtin.copy' in node:
                    content = node['ansible.builtin.copy'].get('content', '')
                    # Copies are for opaque secrets or restoration, not file definitions.
                    self.assertTrue(not content or (content.startswith('{{') and content.endswith('}}')), str(path))
                if 'content' in node:
                    self.assertFalse(isinstance(node['content'], str) and '\n' in node['content'], str(path))
                for value in node.values():
                    check(value, path)
            elif isinstance(node, list):
                for value in node:
                    check(value, path)
        for path in (ROOT/'roles').rglob('*.yml'):
            check(yaml.load(path), path)
        defaults = yaml.load(ROOT/'roles/proxy/defaults/main.yml')
        self.assertNotIn('tg_mtg_config', defaults)
