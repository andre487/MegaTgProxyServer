# MegaTgProxyServer guide

<p align="center">
  <img src="../assets/icon-radius.svg" width="160" alt="MPX — MegaTgProxyServer">
</p>

[Overview](../../README.md) · [Русский](../ru/README.md)

[Setup](#setup) · [Commands](#commands) · [Inventory](#inventory) ·
[Secrets](#secrets) · [SSH egress](#ssh-egress) · [System](#system) ·
[Hooks](#hooks) · [Operations](#operations) · [Troubleshooting](#troubleshooting) · [Bootstrap and jump](#bootstrap-and-ingress-jump)

## Setup

Install Git, Python 3.12+, uv, and OpenSSH on macOS/Linux. Targets must run Debian/Ubuntu
and already have a non-root account with public-key SSH and sudo. Set ansible_user and
tg_admin.user to that account; use `bootstrap` below for initial root access. Use --ask-become-pass
if sudo requires a password. Work from the local checkout:

```sh
./mega-tg-proxy deps
umask 077
mkdir -p ~/.config/mega-tg-proxy
cp inventory.example.yml ~/.config/mega-tg-proxy/inventory.yml
printf '%s\n' ~/.config/mega-tg-proxy/inventory.yml > inventory-path
```

Use the appropriate example for your engine/egress. Replace all placeholders. `deps`
initializes the uv.lock environment and lists bundled Ansible collections; it does
not modify servers. Other launcher commands initialize that environment too.

For a **new** inventory, create a password file once using a private editor; enter a
strong Vault password on one line. Never overwrite the password for an existing inventory.

```sh
$EDITOR ~/.config/mega-tg-proxy/vault-password
chmod 600 ~/.config/mega-tg-proxy/vault-password
export ANSIBLE_VAULT_PASSWORD_FILE="$HOME/.config/mega-tg-proxy/vault-password"
```

Back up that password separately: encrypted values cannot be recovered without it.
With an existing inventory, use its existing Vault password. Ansible requests it
interactively when inline !vault is present and the environment variable is unset.

## Commands

| Command | Purpose |
|---|---|
| `bootstrap` | Create an administrator, verify SSH/sudo, then apply SSH policy; requires exact host names in --limit |
| `deps` | Initialize the locked local environment and list collections |
| `plan` | Check mode; service starts and protocol-key download are skipped |
| `apply --verify` | Apply, verify, then run hooks; stop on error |
| `apply` | Apply and run hooks, without verification |
| `verify` | Check containers, public TCP ports, MTG metrics, and SSH/SOCKS5 egress |
| `configs` | Print client links containing secrets |
| `secret` | Print a new Vault-encrypted tg_secret; inventory is not edited |
| `check` | Run local tests and Ansible rendering checks |

`--inventory PATH`, `--limit HOST`, and `--no-hooks` work before or after the command.
Without --inventory the launcher reads inventory-path, then falls back to inventory.yml.
Relative paths resolve from the repository root. --verify is valid only for apply.
Extra arguments go to Ansible. Apply's --tags/--skip-tags/--start-at-task do not restrict
subsequent verification; other arguments and --limit are retained.
Available tags are `jump`, `tunnel_users`, and `cleanup`; cleanup also has the
`always` tag. There is no `proxy` tag. Task selection does not disable automatic cleanup.

## Inventory

Use native Ansible YAML: hosts under all.children.tg_proxies.hosts, shared values in
that group's vars. Keep it outside the public repository. inventory-path, .hooks,
.generated, .secrets, and inventory.yml are ignored by Git.

| Variable | Meaning / default |
|---|---|
| `ansible_host`, `ansible_user`, `ansible_port` | Management address, existing administrator, SSH port (22) |
| `ansible_python_interpreter` | Remote Python path; examples pin `/usr/bin/python3` |
| `ansible_ssh_private_key_file` | Optional local administrative private-key path |
| `tg_admin.user`, `tg_admin.public_key` | Managed non-root administrator and public key |
| `tg_endpoint` | Address published in client links; defaults to ansible_host |
| `tg_port` | Public TCP port; set explicitly in group vars, usually 443 |
| `tg_engine` | `mtg` or `mtproxy` |
| `tg_mode` | `faketls` for MTG; `classic` or `faketls` for official MTProxy |
| `tg_secret` | Vault-encrypted 32-hex-character key; required |
| `tg_domain` | FakeTLS SNI hostname; keep the existing value when importing MTG |
| `tg_egress` | `direct` or `ssh` (both engines) |
| `tg_image` | MTG defaults to nineseconds/mtg:2.2.8; official MTProxy is built locally as `megatg/mtproxy:<commit>-minimal` |
| `tg_container_name` | Set explicitly: mtg-proxy or mtproto-proxy; verify also uses it |
| `tg_publish_ipv6` | Publish the proxy on IPv6 as well as IPv4; false by default |
| `tg_mtg_template` | MTG template name: mtg.toml.j2 by default, or mtg-tuned.toml.j2 for the tuning profile |
| `tg_workers` | Official MTProxy workers; default 2 |
| `tg_mtproxy_volume` | Official MTProxy data volume; default megatg-mtproxy-data |
| `tg_unattended_upgrades` | Set explicitly; true enables periodic unattended updates |

Set tg_engine, tg_mode, tg_egress, tg_port, and tg_container_name explicitly: standalone
verify/configs do not load role defaults. FakeTLS requires an ASCII/IDNA hostname.
Configuration files live only in `templates/`, not inventory, defaults or tasks.
MTG templates receive `tg_secret_full` and derive egress from SSH parameters.
The tuning profile accepts `tg_mtg_debug`, `tg_mtg_prefer_ip`,
`tg_mtg_auto_update`, `tg_mtg_http_timeout` and `tg_mtg_idle_timeout`.
Common image versions and source commit live in defaults; inventory contains
per-server overrides and infrastructure details.

## Secrets

Generate a key locally after setting ANSIBLE_VAULT_PASSWORD_FILE:

```sh
./mega-tg-proxy secret --mode faketls --domain www.example.com
# Or, for official MTProxy:
./mega-tg-proxy secret --mode classic
```

Insert the encrypted YAML into the host. Set tg_mode/tg_domain separately: --domain
validates generation input but does not save it. FakeTLS client secrets are
`ee + 16-byte key + hex(domain)` for both engines. `tg_secret` always stores only
the 16-byte base key, without a prefix or domain.
Apply never generates or rotates client keys. Changing the key or FakeTLS hostname
changes the client link. configs prints links only on explicit request.

To encrypt an **existing** key without putting it in shell history:

```sh
./.venv/bin/ansible-vault encrypt_string --prompt --name tg_secret
# Encrypt an SSH private-key file:
./.venv/bin/ansible-vault encrypt_string --stdin-name tg_ssh_private_key < /private/path/id_ed25519
```

Paste the encrypted result into inventory; never publish plaintext keys or configs
output. The downloaded Telegram protocol key is unrelated to client secrets.

## SSH egress

Follow [inventory.ssh.example.yml](../../inventory.ssh.example.yml). MegaProxyServer
can manage the exit's forwarding account; this project manages the client tunnel.
Set tg_ssh_host/port/user, a Vault-encrypted tg_ssh_private_key, and tg_ssh_known_hosts.
Verify the exit host key through a trusted channel; nonstandard ports need a
`[hostname]:port` record. StrictHostKeyChecking is enabled.

Set tg_network/bridge/subnet/gateway and tg_ssh_socks_port explicitly. SSH creates a
SOCKS listener on the dedicated Docker gateway; UFW permits its subnet through its
bridge. Key, host-key file, or unit changes restart mtg-ssh-egress. Switching to direct
egress does not automatically remove the old tunnel or network.

## System

Runtime/security packages, Docker, time sync, SSH fail2ban, UFW, unattended-upgrades,
and log limits are managed. Existing Docker CE is preserved; fresh hosts use docker.io.
Docker logs rotate at 10 MB × 3 and journald at 500 MB. Automatic reboot is disabled;
periodic updates use distribution origins. No login notifier is installed.

The administrator receives passwordless sudo; authorized_keys is replaced with its
configured key, and root/password SSH login is disabled. SSH policy validation restores
the previous policy on failure, but is not a general deployment rollback.
UFW permits SSH, proxy, and internal SOCKS where needed; unrelated old allow rules
remain. Docker publications bypass UFW INPUT, so other containers need separate review.

## Hooks

After success: .hooks/post-config-change, then executable files in
.hooks/post-config-change.d in filename order. With --verify they run after verification.
Failure stops later steps and returns nonzero; applied changes are not rolled back.
Working directory: repository root. Environment:

| Variable | Value |
|---|---|
| `MEGATG_ROOT` | Absolute repository path |
| `MEGATG_LINKS_FILE` | Absolute path to `.generated/links.txt`, links for selected hosts only |
| `MEGATG_LIMIT` | The `--limit` expression, or an empty string |
| `MEGATG_EVENT` | post-config-change |
| `MEGATG_INVENTORY`, `MEGATG_ANSIBLE_INVENTORY` | Absolute selected native inventory path |

Hooks receive the **whole inventory**, even with --limit; they must implement their own
selection if needed. --no-hooks skips them without disabling verify.

```sh
mkdir -p .hooks
cp examples/post-config-change .hooks/post-config-change
chmod 700 .hooks/post-config-change
```

The example calls px-manager/tools/deploy.sh (override checkout with PX_MANAGER_REPO),
passing TG inventory through MEGAPROXY_INVENTORY. It requires px-manager support for
this format; until that support is installed, use --no-hooks. Local hooks stay out of Git.

## Operations

Before deployment, back up private inventory/Vault password and record current image
digests and volume names. Preserve existing keys and FakeTLS domains when importing;
for a container without persistent storage, capture its key before replacing it.
One-off migration scripts/playbooks belong outside the production repository.

```sh
./mega-tg-proxy plan --limit example
./mega-tg-proxy apply --limit example --verify --no-hooks
./mega-tg-proxy configs --limit example
```

Apply runs across hosts in parallel using the default Ansible strategy (up to 5 forks by default).
Set `--forks N` (`-f N`) to control concurrency.
Container recreation interrupts sessions. verify is a readiness check, not an MTProto
session: test messages/media in Telegram from the affected network after deployment.
To update one host at a time, run separate applies with `--limit HOST`.
A failed verification leaves changes applied. If recovery is needed, restore the prior
inventory values and previous image/source revision, reapply, and verify. Images
removed by cleanup must be pulled or built again. This does not undo
all system changes or restore deleted data; retain console access and data backups.

For MTG upgrades, change `tg_image` (version/digest); `pull: missing` does not refresh
an already-present mutable tag. For official MTProxy, change `tg_mtproxy_source_ref`
to build a new version on the target. Ansible downloads the backend list and protocol
key over verified HTTPS during deployment.
Only one project should manage each container.

## Troubleshooting

On the server, use docker ps, ss -lntp, and these service-specific checks:

```sh
sudo systemctl status mtg-ssh-egress
sudo journalctl -u mtg-ssh-egress --since '10 minutes ago'
curl --fail http://127.0.0.1:3129/metrics
```

For an unreachable port, check DNS, provider firewall, UFW, and Docker mappings. For
stalled media, compare client/server captures and TCP retransmissions. If MTG stops
accepting clients, inspect the listen queue and process limits. Startup logs of official
MTProxy may contain secrets; redact logs and keep packet captures private.

Local checks (not a full server/Telegram integration test):

```sh
./mega-tg-proxy check
./mega-tg-proxy --inventory inventory.example.yml plan --syntax-check
./mega-tg-proxy --inventory inventory.ssh.example.yml plan --syntax-check
./mega-tg-proxy --inventory inventory.mtproxy.example.yml plan --syntax-check
```

MTProxy + SSH: set `tg_engine: mtproxy`, `tg_mode: classic`, `tg_egress: ssh`
and the SSH settings from `inventory.ssh.example.yml`. TCP is redirected through
redsocks into the SSH SOCKS5 listener; container IPv6 is disabled. The bridge
and subnet must be dedicated to this proxy. Runtime validation on Linux is required
before deployment.

## Bootstrap and ingress jump

`./mega-tg-proxy --limit HOST bootstrap` follows MegaProxyServer's account →
fresh administrative SSH/sudo check → policy → check flow. Configure host-specific
`tg_admin` with `user`, `public_key`, `private_key_file`, `bootstrap_user`,
`bootstrap_auth` (`key` or `password`), optionally `bootstrap_private_key_file`.
Passwords are prompted or read from `--bootstrap-password-file`; pending bootstrap
fields are cleared on success.

`tg_tunnel_users: [{name, port, public_keys}]` manages key-only local forwarding
accounts restricted to `127.0.0.1:port`, without shell, PTY, remote forwarding or
sudo. Use `--tags tunnel_users` to configure accounts without restarting proxies.

Set `tg_node_role: jump`, `tg_jump_domain`, encrypted `tg_jump_private_key`, pinned
`tg_jump_known_hosts`, and `tg_jump_tunnels` including `faketls` and `classic`, each
with `host`, `user`, `local_port`, `remote_port`, optionally `ssh_port`. HAProxy
routes matching SNI to faketls, rejects unknown TLS, and sends non-TLS to classic
(after up to 3 seconds). Backend SSH listeners bind only localhost. The old proxy
container is stopped after checking the FakeTLS tunnel path, then removed by cleanup
after a successful cutover. Existing client links require preserving the backend secret.

`configs --limit JUMP` prints ready FakeTLS and classic links using each backend's
secret. Set `inventory_host` on each `tg_jump_tunnels` entry to the backend's
inventory name. Set a unique `endpoint` on each route for its public link address.

Before configured hooks run after successful apply (and optional verify),
`.generated/links.txt` is generated with mode 0600, one URL per line, respecting
`--limit`. Export failure prevents hooks from running; `--no-hooks` disables the
automatic export. Export separately with
`./mega-tg-proxy --limit jump configs --output .generated/links.txt`.

Use `configs --output -` or `configs --output /dev/stdout` for stdout.
Only links are written to stdout; Ansible progress is sent to stderr.

Set `endpoint` on each `tg_jump_tunnels` entry to give each route a distinct
public address, e.g. `faketls → jump-tls.example.com`, `classic → jump-classic.example.com`.
These are client link addresses for one jump, not separate server configurations.
Backend secrets and FakeTLS domains are preserved. The CLI warns on stderr when
links share a public domain or IP, including routes within one jump, ignoring
case and trailing dots. FakeTLS domains are not used for this check.

Official MTProxy supports `tg_mode: faketls`: the role downloads the backend list
and mounts an explicit startup invoking the binary with `-D tg_domain`, without
`-M`. Set `tg_public_ip` for NAT (defaults to the primary interface IPv4).
When the FakeTLS domain points at the proxy itself, set `tg_mtproxy_fronting_ip`
to an external TLS address for fallback. Docker overrides name resolution only
inside the container, preserving SNI and preventing self-proxy loops.

Add further TLS routes to `tg_jump_tunnels` with unique `name`, `local_port`, `sni`
and public `endpoint`. `classic` remains the default for non-TLS traffic.
HAProxy configuration updates use reload.

Official MTProxy builds from a pinned commit by default. To upgrade, change
`tg_mtproxy_source_ref` (a full 40-character commit); the local image name is
generated automatically.
Docker Hub's `telegrammessenger/proxy:latest` has an old binary unsuitable for
modern extended FakeTLS ClientHello packets. Check both formats and real MTProto
exchange without printing secrets:
`uv run python tools/probe_mtproxy_tls.py tls_backend edge-tls.example.com`.

All official MTProxy nodes build locally from the pinned `tg_mtproxy_source_ref`.
The build stage contains the compiler and headers; runtime uses `scratch` with
the binary, required shared libraries, static BusyBox, and minimal passwd/group/NSS
files. No curl, apt, compiler or headers are shipped in runtime. Ansible fetches
backend lists and protocol keys on the host; classic/FakeTLS share a startup
script and preserve client secrets and ports.

After every deployment, including tagged runs, `docker_cleanup` checks the active
container/listener, then removes unused project images, stopped containers and
empty networks labelled `io.megatg.managed=true` or `io.megatg.build=true`.
Pre-label build stages are identified by the official source URL in Docker history.
Images referenced by any container, even a stopped one, are never forcibly deleted.
Persistent volumes and unrelated application images are preserved. On jump, the
obsolete stopped MTG, SOCKS unit and empty network are also retired.
Use `--tags cleanup` for cleanup only; check mode never removes resources.

Set `tg_links_order` in `tg_proxies.vars` to a list of exact public domains/IPs
in the desired order. It applies to `configs`, TXT, stdout and hook exports;
`--limit` preserves relative ordering. Unlisted addresses follow in unspecified order.
