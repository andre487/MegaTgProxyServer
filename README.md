# MegaTgProxyServer

<p align="center">
  <img src="docs/assets/icon-radius.svg" width="160" alt="MPX — MegaTgProxyServer">
</p>

Manage Telegram proxies on Debian and Ubuntu with Ansible: MTG FakeTLS or official
MTProxy (classic/FakeTLS), with optional SSH tunnels and SNI routing through a jump
server. [MIT licensed](LICENSE).

**[English guide](docs/en/README.md)** · **[Руководство на русском](docs/ru/README.md)**

## Start here

Requirements: macOS/Linux, Git, Python 3.12+, [uv](https://docs.astral.sh/uv/), OpenSSH,
and SSH access to each server. Use an existing non-root administrator with sudo,
or create one with the two-phase `bootstrap` command described in the guides.

Official MTProxy is built on each target from pinned official source, using a minimal
`scratch` runtime. Both engines can connect to Telegram directly or through an
SSH tunnel with a SOCKS5 listener. Separately, a jump server can route incoming
connections to backends by FakeTLS SNI, with a default route for non-TLS traffic.

Start with an inventory example:

- [MTG](inventory.example.yml)
- [MTG with SSH egress](inventory.ssh.example.yml)
- [Official MTProxy](inventory.mtproxy.example.yml)

Follow the guide to create a private inventory and Vault password file, then run:

```sh
./mega-tg-proxy plan --limit example
./mega-tg-proxy apply --limit example --verify --no-hooks
./mega-tg-proxy configs --limit example
```

`apply --verify` runs **apply/cleanup → verify → link export → hooks**, stopping on error.
Link export runs automatically when hooks are enabled; `--no-hooks` skips both. Container recreation briefly interrupts connections; verification
checks readiness, so also test messages and media in Telegram.

The playbook replaces the administrator's authorized keys with the configured key
and disables root/password SSH login. Confirm key access before applying.
Keep inventories and Vault passwords private; `configs` output contains client secrets.
Set `tg_links_order` in inventory to order links; unlisted addresses follow.

See the guides for configuration, updates, px-manager hooks, diagnostics, and development.
