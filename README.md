# MegaTgProxyServer

Manage Telegram proxies on Debian and Ubuntu with Ansible: MTG FakeTLS or official
MTProxy, with direct egress or SSH/SOCKS5 egress for MTG. [MIT licensed](LICENSE).

**[English guide](docs/en/README.md)** · **[Руководство на русском](docs/ru/README.md)**

## Start here

Requirements: macOS/Linux, Git, Python 3.12+, [uv](https://docs.astral.sh/uv/), OpenSSH,
and an existing non-root SSH administrator with sudo on each server.

Choose an inventory example:

- [MTG, direct](inventory.example.yml)
- [MTG, SSH/SOCKS5 exit](inventory.ssh.example.yml)
- [Official MTProxy, direct](inventory.mtproxy.example.yml)

Follow the guide to create a private inventory and Vault password file, then run:

```sh
./mega-tg-proxy plan --limit example
./mega-tg-proxy apply --limit example --verify --no-hooks
./mega-tg-proxy configs --limit example
```

`apply --verify` runs **apply → verify → hooks**, stopping on error. `--no-hooks`
skips hooks only. Container recreation briefly interrupts connections; verification
checks readiness, so also test messages and media in Telegram.

The playbook replaces the administrator's authorized keys with the configured key
and disables root/password SSH login. Confirm key access before applying.
Keep inventories and Vault passwords private; `configs` output contains client secrets.

See the guides for configuration, updates, px-manager hooks, diagnostics, and development.
