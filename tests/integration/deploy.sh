#!/usr/bin/env bash
# Runs only in disposable LXD guests; never point this at a production server.
set -euo pipefail
image=${1:?Debian/Ubuntu LXD image required}
method=${2:?checkout or bash required}
engine=${3:?mtg or mtproxy required}
case "$method:$engine" in checkout:mtg|checkout:mtproxy|bash:mtg|bash:mtproxy) ;; *) exit 2 ;; esac
instance="megatg-ci-$RANDOM"
work_dir=$(mktemp -d)
cleanup() {
    sudo lxc delete --force "$instance" >/dev/null 2>&1 || true
    rm -rf "$work_dir"
}
trap cleanup EXIT
sudo iptables -P FORWARD ACCEPT
sudo ip6tables -P FORWARD ACCEPT
sudo lxc launch "$image" "$instance" -c security.nesting=true -c security.privileged=true
# Copy the working tree, including uncommitted installer changes for local runs.
tar --exclude=.git --exclude=.venv --exclude=.generated --exclude=.hooks \
    --exclude=.secrets --exclude=inventory-path --exclude=inventory.yml \
    --exclude=__pycache__ -czf "$work_dir/source.tar.gz" .
sudo lxc file push "$work_dir/source.tar.gz" "$instance/root/source.tar.gz"
sudo lxc exec "$instance" -- bash -s -- "$method" "$engine" < tests/integration/guest.sh
