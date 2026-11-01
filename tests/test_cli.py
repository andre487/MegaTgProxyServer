import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cli import make_secret, main, export_links
from hooks import run_hooks

class Checks(unittest.TestCase):
    def test_secret(self):
        a, full = make_secret("faketls", "example.com")
        self.assertEqual(bytes.fromhex(full), b"\xee" + bytes.fromhex(a) + b"example.com")
        self.assertNotEqual(a, make_secret("classic", "")[0])
        with self.assertRaises(ValueError):
            make_secret("faketls", "")

    def test_hooks_order_environment_and_failure(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t); d = r / ".hooks/post-config-change.d"; d.mkdir(parents=True)
            for name, body in [("10-first", 'echo "$MEGATG_INVENTORY" > result'), ("20-fail", "exit 7"), ("30-skip", "touch unexpected")]:
                p = d / name; p.write_text("#!/bin/sh\n" + body + "\n"); p.chmod(0o700)
            self.assertEqual(run_hooks(r, "post-config-change", r / "inv.yml", r / "inv.yml"), 7)
            self.assertEqual((r / "result").read_text().strip(), str((r / "inv.yml").resolve()))
            self.assertFalse((r / "unexpected").exists())

    def test_apply_verify_before_hooks(self):
        with tempfile.TemporaryDirectory() as t:
            inv = Path(t) / "inventory.yml"
            inv.write_text("all: {}\n")
            for codes, expected, hooks in [([0, 0], 0, True), ([0, 7], 7, False), ([4], 4, False)]:
                with self.subTest(codes=codes), patch("sys.argv", ["mega-tg-proxy", "apply", "--verify", "--inventory", str(inv), "--limit", "mtp_am", "--tags", "proxy"]), patch("cli.subprocess.call", side_effect=codes) as call, patch("cli.run_hooks", return_value=0) as hook, patch("cli.find_hooks", return_value=[Path("/hook")]), patch("cli.export_links", return_value=0) as export:
                    self.assertEqual(main(), expected)
                    self.assertEqual(call.call_count, len(codes))
                    self.assertEqual(call.call_args_list[0].args[0][3], "playbooks/site.yml")
                    if len(codes) == 2:
                        cmd = call.call_args_list[1].args[0]
                        self.assertEqual(cmd[3], "playbooks/verify.yml")
                        self.assertIn("mtp_am", cmd)
                        self.assertNotIn("--tags", cmd)
                    self.assertEqual(hook.called, hooks)
                    self.assertEqual(export.called, hooks)
                    if hooks:
                        self.assertEqual(hook.call_args.kwargs['limit'], 'mtp_am')
                        self.assertEqual(hook.call_args.kwargs['links_file'].name, 'links.txt')

    def test_apply_without_verify_and_no_hooks(self):
        with tempfile.TemporaryDirectory() as t:
            inv = Path(t) / "inventory.yml"; inv.write_text("all: {}\n")
            for flag, calls in [( [], 1), (["--verify"], 2)]:
                with patch("sys.argv", ["mega-tg-proxy", "apply", "--no-hooks", "--inventory", str(inv), *flag]), patch("cli.subprocess.call", return_value=0) as call, patch("cli.run_hooks") as hook:
                    self.assertEqual(main(), 0)
                    self.assertEqual(call.call_count, calls)
                    hook.assert_not_called()

    def test_hook_receives_links_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.hooks').mkdir()
            hook = root / '.hooks/post-config-change'
            hook.write_text('#!/bin/sh\nprintf "%s\\n" "$MEGATG_LINKS_FILE" "$MEGATG_LIMIT" > received\n')
            hook.chmod(0o700)
            output = root / '.generated/links.txt'
            self.assertEqual(run_hooks(root, 'post-config-change', root/'inv', root/'inv', output, 'trpx1,mtp_am'), 0)
            self.assertEqual((root/'received').read_text().splitlines(), [str(output.resolve()), 'trpx1,mtp_am'])
            with patch.dict(os.environ, {'MEGATG_LIMIT': 'stale', 'MEGATG_LINKS_FILE': 'stale'}):
                self.assertEqual(run_hooks(root, 'post-config-change', root/'inv', root/'inv'), 0)
            self.assertEqual((root/'received').read_text(), '\n\n')

    def test_export_is_private_atomic_and_keeps_limit(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / '.generated/links.txt'
            command = ['ansible-playbook', '-i', 'inv', 'playbooks/site.yml', '--limit', 'trpx1']
            def write_fragments(args, **kwargs):
                self.assertIn('trpx1', args)
                self.assertEqual(args[3], 'playbooks/configs.yml')
                fragments = Path(json.loads(args[-1])['tg_links_directory'])
                (fragments/'a.txt').write_text('tg://proxy?first\n')
                (fragments/'b.txt').write_text('tg://proxy?second\n')
                return 0
            with patch('cli.ROOT', root), patch('cli.subprocess.call', side_effect=write_fragments):
                self.assertEqual(export_links(command, output), 0)
            self.assertEqual(output.read_text(), 'tg://proxy?first\ntg://proxy?second\n')
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with patch('cli.ROOT', root), patch('cli.subprocess.call', return_value=7):
                self.assertEqual(export_links(command, output), 7)
            self.assertEqual(output.read_text(), 'tg://proxy?first\ntg://proxy?second\n')

    def test_failed_export_does_not_run_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            inv = Path(directory)/'inv.yml'
            inv.write_text('all: {}\n')
            with patch('sys.argv', ['mega-tg-proxy', 'apply', '--inventory', str(inv)]), patch('cli.subprocess.call', return_value=0), patch('cli.find_hooks', return_value=[Path('/hook')]), patch('cli.export_links', return_value=9), patch('cli.run_hooks') as hook:
                self.assertEqual(main(), 9)
                hook.assert_not_called()

    def test_apply_generates_selected_links_before_real_hook(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inv = root/'inventory.yml'
            inv.write_text('all: {}\n')
            (root/'.hooks').mkdir()
            hook = root/'.hooks/post-config-change'
            hook.write_text('#!/bin/sh\nset -eu\ntest "$MEGATG_LIMIT" = trpx1\ncat "$MEGATG_LINKS_FILE" > received\n')
            hook.chmod(0o700)
            commands = []
            def ansible(command, **kwargs):
                commands.append(command)
                if command[3] == 'playbooks/configs.yml':
                    self.assertEqual(command[command.index('--limit')+1], 'trpx1')
                    fragments = Path(json.loads(command[-1])['tg_links_directory'])
                    (fragments/'a.txt').write_text('tg://proxy?selected\n')
                return 0
            with patch('cli.ROOT', root), patch('sys.argv', ['mega-tg-proxy', 'apply', '--inventory', str(inv), '--limit', 'trpx1']), patch('cli.subprocess.call', side_effect=ansible):
                self.assertEqual(main(), 0)
            self.assertEqual([c[3] for c in commands], ['playbooks/site.yml', 'playbooks/configs.yml'])
            self.assertEqual((root/'received').read_text(), 'tg://proxy?selected\n')

    def test_export_stdout_aliases_contain_only_links(self):
        import io
        import json
        import sys
        for target in ['-', '/dev/stdout']:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = io.StringIO()
                def write_fragments(command, **kwargs):
                    self.assertIs(kwargs['stdout'], sys.stderr)
                    fragments = Path(json.loads(command[-1])['tg_links_directory'])
                    (fragments/'a.txt').write_text('tg://proxy?first\n')
                    (fragments/'b.txt').write_text('tg://proxy?second\n')
                    return 0
                command = ['ansible-playbook', '-i', 'inv', 'playbooks/configs.yml']
                with patch('cli.ROOT', root), patch('cli.sys.stdout', output), patch('cli.subprocess.call', side_effect=write_fragments), patch('cli.tempfile.mkstemp', side_effect=AssertionError('stdout must not be replaced as a file')):
                    self.assertEqual(export_links(command, Path(target)), 0)
                self.assertEqual(output.getvalue(), 'tg://proxy?first\ntg://proxy?second\n')
                output = io.StringIO()
                with patch('cli.ROOT', root), patch('cli.sys.stdout', output), patch('cli.subprocess.call', return_value=7):
                    self.assertEqual(export_links(command, Path(target)), 7)
                self.assertEqual(output.getvalue(), '')

    def test_duplicate_public_domains_warn_on_stderr_only(self):
        import io
        from cli import warn_duplicate_domains
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory)/'inventory.yml'
            inventory.write_text('''all:
  children:
    tg_proxies:
      hosts:
        old:
          ansible_host: 192.0.2.1
          tg_endpoint: Proxy.Example.com.
          tg_domain: fake-old.example
        jump:
          ansible_host: 192.0.2.1
          tg_node_role: jump
          tg_endpoints: [proxy.example.com]
          tg_jump_tunnels: [{name: classic}]
          tg_domain: fake-new.example
''')
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch('cli.sys.stdout', stdout), patch('cli.sys.stderr', stderr):
                warn_duplicate_domains(inventory)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue().count('WARNING:'), 1)
            self.assertIn('old and jump', stderr.getvalue())
            self.assertIn('proxy.example.com', stderr.getvalue())
            inventory.write_text(inventory.read_text().replace('Proxy.Example.com.', 'other.example.com').replace('fake-new.example', 'fake-old.example'))
            stderr = io.StringIO()
            with patch('cli.sys.stderr', stderr):
                warn_duplicate_domains(inventory)
            self.assertEqual(stderr.getvalue(), '')

            inventory.write_text('all: {children: {tg_proxies: {hosts: {a: {ansible_host: 192.0.2.1}, b: {ansible_host: 192.0.2.1}}}}}')
            stderr = io.StringIO()
            with patch('cli.sys.stderr', stderr):
                warn_duplicate_domains(inventory)
            self.assertEqual(stderr.getvalue().count('WARNING:'), 1)

            inventory.write_text('all: {children: {tg_proxies: {hosts: {jump: {tg_node_role: jump, tg_endpoint: same.example, tg_jump_tunnels: [{name: faketls}, {name: classic}]}}}}}')
            stderr = io.StringIO()
            with patch('cli.sys.stderr', stderr):
                warn_duplicate_domains(inventory)
            self.assertIn('jump/faketls and jump/classic', stderr.getvalue())
            inventory.write_text(inventory.read_text().replace('{name: classic}', '{name: classic, endpoint: other.example}'))
            stderr = io.StringIO()
            with patch('cli.sys.stderr', stderr):
                warn_duplicate_domains(inventory)
            self.assertEqual(stderr.getvalue(), '')

    def test_explicit_link_order_and_unlisted_tail(self):
        from cli import ordered_links, link_order
        links = ['tg://proxy?server=unlisted-b&port=443&secret=1',
                 'tg://proxy?server=trpx1.example.com&port=443&secret=2',
                 'tg://proxy?server=192.0.2.10&port=443&secret=3',
                 'tg://proxy?server=unlisted-a&port=443&secret=4',
                 'tg://proxy?server=trpx2.example.com&port=443&secret=5']
        order = ['192.0.2.10', 'trpx2.example.com', 'trpx1.example.com']
        self.assertEqual(ordered_links(links, order)[:3], [links[2], links[4], links[1]])
        self.assertEqual(set(ordered_links(links, order)[3:]), {links[0], links[3]})
        self.assertEqual(ordered_links([links[1], links[4]], order), [links[4], links[1]])
        self.assertEqual(ordered_links([links[1]], ['TRPX1.EXAMPLE.COM.']), [links[1]])
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory)/'inventory.yml'
            inventory.write_text('all: {children: {tg_proxies: {vars: {tg_links_order: [a, b]}}}}')
            self.assertEqual(link_order(inventory), ['a', 'b'])
            inventory.write_text(inventory.read_text().replace('[a, b]', '[a, A.]'))
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                link_order(inventory)
