"""Two-phase administrative bootstrap, matching MegaProxyServer's flow."""
import getpass
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent


def check_admin(host):
    admin = host['tg_admin']
    key = str(Path(admin['private_key_file']).expanduser())
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
               '-o', 'ControlMaster=no', '-o', 'ControlPath=none', '-o', 'ConnectTimeout=10',
               '-p', str(host.get('ansible_port', 22)), '-i', key]
    for option in ['ansible_ssh_common_args', 'ansible_ssh_extra_args']:
        command += shlex.split(host.get(option, ''))
    command += ['-l', admin['user'], '--', host['ansible_host'], 'sudo -n true']
    try:
        return subprocess.run(command, timeout=30, capture_output=True).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def bootstrap(path, limit, password_file=None):
    if not limit:
        raise ValueError('Bootstrap requires exact host names in --limit')
    data = json.loads(subprocess.check_output(['ansible-inventory', '-i', str(path), '--list'], cwd=ROOT))
    names = list(dict.fromkeys(limit.split(',')))
    hosts = data['_meta']['hostvars']
    if any(name not in hosts for name in names):
        raise ValueError('Unknown bootstrap host')
    for name in names:
        host = hosts[name]
        admin = host['tg_admin']
        if not admin.get('bootstrap_user'):
            continue
        key = Path(admin['private_key_file']).expanduser()
        public = subprocess.check_output(['ssh-keygen', '-y', '-f', str(key)], text=True)
        if public.split()[:2] != admin['public_key'].split()[:2]:
            raise ValueError('Administrative public and private keys do not match')
        phases = ['policy'] if check_admin(host) else ['account', 'policy']
        for phase in phases:
            variables = dict(host, tg_bootstrap_phase=phase,
                             ansible_user=admin['user'] if phase == 'policy' else admin['bootstrap_user'],
                             ansible_ssh_private_key_file=str(key) if phase == 'policy' else admin.get('bootstrap_private_key_file', str(key)))
            variables.setdefault('ansible_python_interpreter', '/usr/bin/python3')
            if phase == 'account' and admin.get('bootstrap_auth') == 'password':
                password = Path(password_file).read_text().strip() if password_file else getpass.getpass(f'Initial SSH password for {name}: ')
                if not password:
                    raise ValueError('Initial password must not be empty')
                variables.update(ansible_password=password, ansible_become_password=password,
                                 ansible_ssh_common_args='-o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive')
            with tempfile.TemporaryDirectory(prefix='megatg-bootstrap-') as directory:
                temporary = Path(directory) / 'inventory.yml'
                temporary.touch(mode=0o600)
                with temporary.open('w') as stream:
                    YAML().dump({'all': {'hosts': {name: variables}}}, stream)
                result = subprocess.run(['ansible-playbook', '-i', str(temporary), 'playbooks/bootstrap.yml'], cwd=ROOT)
            if result.returncode:
                return result.returncode
            if not check_admin(host):
                raise ValueError(f'Administrative key login or sudo failed after {phase}; bootstrap remains pending')
        yaml = YAML()
        document = yaml.load(path)
        # Native inventory layout is intentionally kept consistent with this project.
        values = document['all']['children']['tg_proxies']['hosts'][name]['tg_admin']
        for field in ['bootstrap_user', 'bootstrap_private_key_file']:
            values.pop(field, None)
        values['bootstrap_auth'] = 'key'
        descriptor, staging = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                yaml.dump(document, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staging, path)
        finally:
            if os.path.exists(staging):
                os.unlink(staging)
        print(f'Administrative connection activated for: {name}', flush=True)
    return 0
