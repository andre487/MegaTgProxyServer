#!/usr/bin/env bash
set -euo pipefail
method=${1:?}
engine=${2:?}
export DEBIAN_FRONTEND=noninteractive
# Some CI runners disallow plain HTTP in nested guests.
sed -i 's|http://|https://|g' /etc/apt/sources.list 2>/dev/null || true
sed -i 's|http://|https://|g' /etc/apt/sources.list.d/*.sources 2>/dev/null || true
apt-get update
apt-get install -y ca-certificates git python3 python3-venv openssh-server sudo
mkdir /root/source
tar --no-same-owner -xzf /root/source.tar.gz -C /root/source
cd /root/source
git init -b main
git add .
git -c user.name=CI -c user.email=ci@example.com commit -qm 'Test working tree'
if [[ $method == bash ]]; then
    # Exercise a fresh clone without fetching an unrelated main revision.
    git config --global url.file:///root/source.insteadOf https://github.com/andre487/MegaTgProxyServer.git
    printf 'y\n' | script -qefc 'bash /root/source/install.sh' /dev/null
    cd /opt/mega-tg-proxy-server
    test -x .bootstrap/bin/uv
else
    python3 -m venv .bootstrap
    .bootstrap/bin/pip install 'uv==0.12.5'
    export PATH="$PWD/.bootstrap/bin:$PATH"
    uv sync --frozen --python 3.12
    ./mega-tg-proxy deps
fi
ssh-keygen -q -t ed25519 -N '' -f /root/ci-key
install -d -m 0700 /root/.ssh
cat /root/ci-key.pub >> /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
systemctl enable --now ssh
ssh-keyscan -H 127.0.0.1 > /root/.ssh/known_hosts
export CI_ENGINE="$engine"
.bootstrap/bin/uv run --frozen python - <<'PY'
import os
from pathlib import Path
from ruamel.yaml import YAML
engine = os.environ['CI_ENGINE']
host = {
    'ansible_host': '127.0.0.1', 'ansible_user': 'ci-admin',
    'ansible_ssh_private_key_file': '/root/ci-key',
    'ansible_python_interpreter': '/usr/bin/python3',
    'tg_endpoint': 'ci.example.com', 'tg_port': 443,
    'tg_engine': engine, 'tg_mode': 'faketls' if engine == 'mtg' else 'classic',
    'tg_domain': 'www.google.com', 'tg_egress': 'direct',
    'tg_container_name': 'mtg-proxy' if engine == 'mtg' else 'mtproto-proxy',
    'tg_secret': '0123456789abcdef0123456789abcdef',
    'tg_unattended_upgrades': False,
    'tg_admin': {'user': 'ci-admin', 'public_key': Path('/root/ci-key.pub').read_text().strip(),
                 'private_key_file': '/root/ci-key', 'bootstrap_user': 'root',
                 'bootstrap_auth': 'key'},
}
YAML().dump({'all': {'children': {'tg_proxies': {'hosts': {'ci': host}}}}}, Path('/root/ci-inventory.yml'))
Path('/root/ci-inventory.yml').chmod(0o600)
PY
cli=(./mega-tg-proxy --inventory /root/ci-inventory.yml --limit ci --no-hooks)
"${cli[@]}" bootstrap
"${cli[@]}" apply --verify
"${cli[@]}" plan
"${cli[@]}" configs --output /root/links.txt
grep -q 'server=ci.example.com' /root/links.txt
test "$(stat -c %a /root/links.txt)" = 600
# A second deployment also exercises cleanup with an existing container.
"${cli[@]}" apply --verify
docker inspect --format '{{.State.Running}}' "$( [[ $engine == mtg ]] && echo mtg-proxy || echo mtproto-proxy )" | grep -qx true
