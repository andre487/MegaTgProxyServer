import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class MTProxyStartTest(unittest.TestCase):
    def test_tls_start_and_missing_inputs(self):
        source = Path(__file__).resolve().parents[1]/'roles/proxy/templates/mtproxy-start.sh.j2'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root/'mtproto-proxy'
            binary.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            binary.chmod(0o700)
            ip = root/'ip'
            ip.write_text('#!/bin/sh\necho "1.1.1.1 via 172.17.0.1 dev eth0 src 172.17.0.2 uid 0"\n')
            ip.chmod(0o700)
            script = root/'start.sh'
            script.write_text(source.read_text().replace('/usr/local/bin/mtproto-proxy', str(binary)))
            env = os.environ | {'PATH': str(root)+os.pathsep+os.environ['PATH'], 'SECRET': '1'*32, 'MODE': 'faketls', 'DOMAIN': 'mtp.example.com', 'PUBLIC_IP': '192.0.2.1'}
            run = subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            args = json.loads(run.stdout)
            self.assertEqual(args[args.index('-D')+1], 'mtp.example.com')
            self.assertEqual(args[args.index('-S')+1], '1'*32)
            self.assertEqual(args[args.index('--nat-info')+1], '172.17.0.2:192.0.2.1')
            self.assertNotIn('-M', args)
            classic = subprocess.run(['/bin/sh', str(script)], env=env | {'MODE': 'classic', 'DOMAIN': '', 'WORKERS': '3'}, capture_output=True, text=True)
            self.assertEqual(classic.returncode, 0, classic.stderr)
            classic_args = json.loads(classic.stdout)
            self.assertEqual(classic_args[classic_args.index('-M')+1], '3')
            self.assertNotIn('-D', classic_args)
            for missing in ['SECRET', 'DOMAIN', 'PUBLIC_IP', 'MODE']:
                with self.subTest(missing=missing):
                    result = subprocess.run(['/bin/sh', str(script)], env=env | {missing: ''}, capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b'')

    def test_compatibility_probe_covers_extended_hello(self):
        import hmac
        from tools.probe_mtproxy_tls import client_hello
        key = bytes.fromhex('11'*16)
        for modern in [False, True]:
            with self.subTest(modern=modern):
                packet, random = client_hello('mtp.example.com', key, modern)
                self.assertEqual(int.from_bytes(packet[3:5], 'big'), len(packet)-5)
                self.assertEqual(int.from_bytes(packet[6:9], 'big'), len(packet)-9)
                self.assertEqual(len(packet), 517) if not modern else self.assertGreater(len(packet), 1024)
                packet[11:43] = bytes(32)
                self.assertEqual(hmac.digest(key, packet, 'sha256')[:28], random[:28])
                self.assertEqual(packet[78:80], b'\x0a\x0a' if modern else b'\x13\x01')
