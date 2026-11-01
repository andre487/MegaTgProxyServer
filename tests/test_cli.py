import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cli import make_secret, main
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
                with self.subTest(codes=codes), patch("sys.argv", ["mega-tg-proxy", "apply", "--verify", "--inventory", str(inv), "--limit", "mtp_am", "--tags", "proxy"]), patch("cli.subprocess.call", side_effect=codes) as call, patch("cli.run_hooks", return_value=0) as hook:
                    self.assertEqual(main(), expected)
                    self.assertEqual(call.call_count, len(codes))
                    self.assertEqual(call.call_args_list[0].args[0][3], "playbooks/site.yml")
                    if len(codes) == 2:
                        cmd = call.call_args_list[1].args[0]
                        self.assertEqual(cmd[3], "playbooks/verify.yml")
                        self.assertIn("mtp_am", cmd)
                        self.assertNotIn("--tags", cmd)
                    self.assertEqual(hook.called, hooks)

    def test_apply_without_verify_and_no_hooks(self):
        with tempfile.TemporaryDirectory() as t:
            inv = Path(t) / "inventory.yml"; inv.write_text("all: {}\n")
            for flag, calls in [( [], 1), (["--verify"], 2)]:
                with patch("sys.argv", ["mega-tg-proxy", "apply", "--no-hooks", "--inventory", str(inv), *flag]), patch("cli.subprocess.call", return_value=0) as call, patch("cli.run_hooks") as hook:
                    self.assertEqual(main(), 0)
                    self.assertEqual(call.call_count, calls)
                    hook.assert_not_called()
