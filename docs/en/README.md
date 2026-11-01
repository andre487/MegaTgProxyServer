# MegaTgProxyServer guide

[Overview](../../README.md) · [Русский](../ru/README.md)

[Setup](#setup) · [Commands](#commands) · [Inventory](#inventory) ·
[Secrets](#secrets) · [SSH egress](#ssh-egress) · [System](#system) ·
[Hooks](#hooks) · [Operations](#operations) · [Troubleshooting](#troubleshooting)

## Setup

Install Git, Python 3.12+, uv, and OpenSSH on macOS/Linux. Targets must run Debian/Ubuntu
and already have a non-root account with public-key SSH and sudo. Set ansible_user and
tg_admin.user to that account; there is no root bootstrap wizard. Use --ask-become-pass
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
subsequent verification; other arguments and --limit are retained. Roles currently have
no deployment tags: --tags proxy does not automatically select the proxy role.

## Inventory

Use native Ansible YAML: hosts under all.children.tg_proxies.hosts, shared values in
that group's vars. Keep it outside the public repository. inventory-path, .hooks,
.generated, .secrets, and inventory.yml are ignored by Git.

| Variable | Meaning / default |
|---|---|
| `ansible_host`, `ansible_user`, `ansible_port` | Management address, existing administrator, SSH port (22) |
| `ansible_ssh_private_key_file` | Optional local administrative private-key path |
| `tg_admin.user`, `tg_admin.public_key` | Managed non-root administrator and public key |
| `tg_endpoint` | Address published in client links; defaults to ansible_host |
| `tg_port` | Public TCP port; set explicitly in group vars, usually 443 |
| `tg_engine` | `mtg` or `mtproxy` |
| `tg_mode` | `faketls` for MTG; `classic` for official MTProxy |
| `tg_secret` | Vault-encrypted 32-hex-character key; required |
| `tg_domain` | FakeTLS SNI hostname; keep the existing value when importing MTG |
| `tg_egress` | `direct` or, for MTG, `ssh` |
| `tg_image` | MTG defaults to nineseconds/mtg:2.2.8; official MTProxy to telegrammessenger/proxy:latest |
| `tg_container_name` | Set explicitly: mtg-proxy or mtproto-proxy; verify also uses it |
| `tg_publish_ipv6` | Publish the proxy on IPv6 as well as IPv4; false by default |
| `tg_mtg_config` | Optional complete MTG TOML with __MEGATG_SECRET__ placeholder |
| `tg_workers` | Official MTProxy workers; default 2 |
| `tg_mtproxy_volume` | Official MTProxy data volume; default megatg-mtproxy-data |
| `tg_unattended_upgrades` | Set explicitly; true enables periodic unattended updates |

Set tg_engine, tg_mode, tg_egress, tg_port, and tg_container_name explicitly: standalone
verify/configs do not load role defaults. FakeTLS requires an ASCII/IDNA hostname.
A custom tg_mtg_config replaces the full TOML: it must listen on 3128, expose metrics
on 3129, and match the chosen egress. Use __MEGATG_SECRET__ for the generated client value.

## Secrets

Generate a key locally after setting ANSIBLE_VAULT_PASSWORD_FILE:

```sh
./mega-tg-proxy secret --mode faketls --domain www.example.com
# Or, for official MTProxy:
./mega-tg-proxy secret --mode classic
```

Insert the encrypted YAML into the host. Set tg_mode/tg_domain separately: --domain
validates generation input but does not save it. FakeTLS client secrets are
`ee + 16-byte key + hex(domain)`; official MTProxy uses the classic key.
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

Apply is parallel by default; deploy one host at a time to keep alternatives available.
Container recreation interrupts sessions. verify is a readiness check, not an MTProto
session: test messages/media in Telegram from the affected network before proceeding.
A failed verification leaves changes applied. If recovery is needed, restore the prior
inventory values and pinned image, reapply to that host, and verify. This does not undo
all system changes or restore deleted data; retain console access and data backups.

For upgrades, change the image version/digest explicitly. pull: missing does not refresh
an already-present mutable tag; prefer digests. Official MTProxy downloads its backend
list at startup; the role downloads its server protocol key over verified HTTPS.
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
