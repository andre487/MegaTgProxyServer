"""Ansible launcher; inventory is native Ansible YAML with inline Vault values."""
import argparse
import json
import tempfile
import os
from pathlib import Path
import secrets
import subprocess
import sys
from hooks import find_hooks, run_hooks
from ruamel.yaml import YAML
from urllib.parse import parse_qs, urlsplit
ROOT = Path(__file__).resolve().parent

def make_secret(mode, domain):
    if mode == "faketls":
        domain = domain.encode("idna").decode("ascii")
        if not domain or len(domain) > 253 or any(not part or len(part) > 63 for part in domain.split(".")):
            raise ValueError("Invalid FakeTLS hostname")
    key = secrets.token_hex(16)
    return key, "ee" + key + domain.encode().hex() if mode == "faketls" else key

def ordered_links(links, order):
    ranks = {server.rstrip('.').lower(): index for index, server in enumerate(order)}
    def key(link):
        server = parse_qs(urlsplit(link).query).get('server', [''])[0].rstrip('.').lower()
        return ranks.get(server, len(ranks))
    return sorted(links, key=key)


def link_order(inventory):
    document = YAML().load(inventory) or {}
    group = document.get('all', {}).get('children', {}).get('tg_proxies', {})
    order = (group.get('vars') or {}).get('tg_links_order', [])
    if not isinstance(order, list) or any(not isinstance(server, str) or not server.strip() for server in order):
        raise ValueError('tg_links_order must be a list of public server names or IPs')
    if len({server.rstrip('.').lower() for server in order}) != len(order):
        raise ValueError('tg_links_order contains duplicate server names or IPs')
    return order


def export_links(cmd, output, order=()):
    to_stdout = str(output) in ('-', '/dev/stdout')
    if not to_stdout:
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
    generated = ROOT / '.generated'
    generated.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='links-', dir=generated) as directory:
        command = cmd.copy()
        command[3] = 'playbooks/configs.yml'
        code = subprocess.call(command + ['--extra-vars', json.dumps({'tg_links_directory': directory})], cwd=ROOT, stdout=sys.stderr if to_stdout else None)
        if code:
            return code
        fragments = sorted(Path(directory).glob('*.txt'))
        if not fragments:
            print('No hosts selected; links file was not changed', file=sys.stderr)
            return 1
        links = ordered_links([line for fragment in fragments for line in fragment.read_text().splitlines() if line], order)
        content = '\n'.join(links) + '\n'
        if to_stdout:
            sys.stdout.write(content)
            return 0
        descriptor, staging = tempfile.mkstemp(prefix='.links-', dir=output.parent)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                stream.write(content)
            os.replace(staging, output)
        finally:
            if os.path.exists(staging):
                os.unlink(staging)
    print(f'Client links saved to {output}')
    return 0


def warn_duplicate_domains(inventory):
    document = YAML().load(inventory)
    group = (document or {}).get('all', {}).get('children', {}).get('tg_proxies', {})
    seen = {}
    for name, values in (group.get('hosts') or {}).items():
        host = dict(group.get('vars') or {}) | (values or {})
        default_endpoints = host.get('tg_endpoints', [host.get('tg_endpoint', host.get('ansible_host', name))])
        routes = host.get('tg_jump_tunnels', []) if host.get('tg_node_role') == 'jump' else [None]
        for route in routes:
            label = name + ('/' + route['name'] if route else '')
            endpoints = [route['endpoint']] if route and 'endpoint' in route else default_endpoints
            for value in endpoints:
                endpoint = str(value).rstrip('.').lower()
                if endpoint in seen:
                    print(f'WARNING: public domain/IP {endpoint} is shared by {seen[endpoint]} and {label}; Telegram identifies these links as the same proxy', file=sys.stderr)
                else:
                    seen[endpoint] = label



def main():
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", type=Path)
    p.add_argument("--limit", "-l")
    p.add_argument("--output", type=Path, help="Save client links as TXT; - or /dev/stdout writes to stdout (configs)")
    p.add_argument("--no-hooks", action="store_true")
    p.add_argument("--verify", action="store_true", help="Verify after apply, before running hooks")
    p.add_argument("--tags")
    p.add_argument("--skip-tags")
    p.add_argument("--start-at-task")
    p.add_argument("command", choices=["bootstrap", "deps", "plan", "apply", "verify", "configs", "secret", "check"])
    p.add_argument("--mode", choices=["classic", "faketls"], default="faketls")
    p.add_argument("--bootstrap-password-file", type=Path)
    p.add_argument("--domain", default="www.example.com")
    a, extra = p.parse_known_args()
    if a.output and a.command != 'configs':
        p.error('--output is only supported with configs')
    if a.verify and a.command != "apply":
        p.error("--verify is only supported with apply")
    if a.command == "check":
        code = subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT)
        if code:
            return code
        return subprocess.call(["ansible-playbook", "-i", "localhost,", "-c", "local", "tests/render.yml"], cwd=ROOT)
    if a.command == "deps":
        return subprocess.call(["ansible-galaxy", "collection", "list"], cwd=ROOT)
    if a.command == "secret":
        key, _ = make_secret(a.mode, a.domain)
        cmd = ["ansible-vault", "encrypt_string", "--stdin-name", "tg_secret"]
        if not os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE"):
            sys.exit("Set ANSIBLE_VAULT_PASSWORD_FILE to encrypt the generated secret")
        # Never print the plaintext key; keep it in memory and pass over stdin.
        return subprocess.run(cmd, input=key, text=True, cwd=ROOT).returncode
    pointer = ROOT / "inventory-path"
    inventory = (a.inventory or Path(pointer.read_text().strip() if pointer.exists() else "inventory.yml")).expanduser().resolve()
    if not inventory.is_file():
        sys.exit(f"Inventory missing: {inventory}")
    warn_duplicate_domains(inventory)
    if a.command == "bootstrap":
        from bootstrap import bootstrap
        return bootstrap(inventory, a.limit, a.bootstrap_password_file)
    play = "site" if a.command in ("plan", "apply") else a.command
    cmd = ["ansible-playbook", "-i", str(inventory), f"playbooks/{play}.yml"]
    if "!vault" in inventory.read_text() and not os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE"):
        cmd += ["--ask-vault-pass"]
    if a.limit:
        cmd += ["--limit", a.limit]
    if a.command == "plan":
        cmd += ["--check"]  # Do not emit a diff containing credentials.
    selection = []
    for option in ("tags", "skip_tags", "start_at_task"):
        if getattr(a, option) is not None:
            selection += ["--" + option.replace("_", "-"), getattr(a, option)]
    inspection = any(flag in extra for flag in ['--syntax-check', '--list-hosts', '--list-tasks', '--list-tags', '--check', '-C'])
    if a.command == 'configs' and not inspection:
        return export_links(cmd + extra, a.output or Path('-'), link_order(inventory))
    code = subprocess.call(cmd + extra + selection, cwd=ROOT)
    if code == 0 and a.command == "apply" and a.verify:
        verify_cmd = cmd.copy()
        verify_cmd[3] = "playbooks/verify.yml"
        # Verify the selected hosts in full, regardless of apply's task filters.
        code = subprocess.call(verify_cmd + extra, cwd=ROOT)
    if code == 0 and a.command == 'apply' and not inspection:
        hooks_enabled = not a.no_hooks and bool(find_hooks(ROOT, 'post-config-change'))
        links_file = ROOT / '.generated' / 'links.txt'
        if hooks_enabled:
            code = export_links(cmd + extra, links_file, link_order(inventory))
        if code == 0 and hooks_enabled:
            code = run_hooks(ROOT, 'post-config-change', inventory, inventory,
                             links_file=links_file, limit=a.limit)
    return code

if __name__ == "__main__":
    raise SystemExit(main())
