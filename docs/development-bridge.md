# Development LLM bridge

Run a fresh test VM with a current ISO and the host's saved Codex ChatGPT login:

```bash
./scripts/run-vm.sh --name bridge-minimal --dev-bridge
```

The installer automatically opens its conversation with the model configured in
`$CODEX_HOME/config.toml` (default `~/.codex/config.toml`). To pin a different model:

```bash
./scripts/run-vm.sh --name bridge-minimal --dev-bridge --bridge-model gpt-6-astra
```

For the Live website test machine use `scripts/run-live-web-vm.sh`; it starts the
bridge automatically. `AGIOS_TEST_SCRIPTED=<configuration.json>` replaces the
model with a fixed configuration (`dev-bridge.py --scripted`), which exercises
storage, preview and finalization without spending model quota; the dialogue
itself is then not a test of the model. `AGIOS_TEST_BRIDGE=claude-code` routes
the dialogue through the host's headless Claude Code; `AGIOS_TEST_BRIDGE=none`
starts no bridge at all, so the Live behaves as on a real computer (for example to
check the ChatGPT sign-in link, for which the bridge otherwise stands in).

Requires an ISO containing `bridge.py` and `71-agi-dev-bridge.rules`. Older images
cannot discover this channel. Normal runs without `--dev-bridge` retain the
provider selection and browser/API login flow. The bridge is only available in
install mode; boot the installed system normally with `--mode disk`.

## Transport and authorization

`run-vm.sh` starts a bridge for that QEMU process, creates a Unix socket in a unique
0700 runtime directory, and attaches it as `org.agi-os.llm` via virtio serial.
There is no TCP listener, API key to type, shared host filesystem or credential in
the guest/ISO. Only the VM launched with that channel can use it (other processes
running as the same host user are within the same trust boundary). QEMU exit
terminates the bridge and its model backend and removes the socket.

The guest protocol allows only `models` and bounded `reply` requests. It does not
forward app-server RPC, tools, shell commands, account data, or arbitrary model
selection. The existing installer schema, validation, review, password entry and
explicit disk consent remain in force. The model is conversation-only, isolated
by bubblewrap with an empty home and no host disks, configuration, MCP servers or
skills. The host bridge sends only the current access token and account ID to
that backend's memory using official external-token authentication.

Codex on the host owns the saved OAuth session and refresh-token lifecycle. The
bridge reads the current access token before each turn and on backend refresh
requests. It neither copies nor rotates the refresh token. An expired token that
has not been renewed by host Codex, revoked login, provider outage or account
limit can still stop inference. Reconnect/renew Codex on the host and retry; no
login inside each new VM is required. This mode currently requires file-backed
ChatGPT login in `auth.json`; keyring-only and API-key authentication are not
supported. No existing credentials are migrated into Bitwarden and no new
technical secret is created by this transport.

The external-token app-server API is experimental:
https://learn.chatgpt.com/docs/app-server#authentication-modes

## Testing

- Unit/transport checks: `python -B -m unittest discover -s tests -v`.
- Run graphical tests under a separate Xvfb display to avoid changing desktop
  focus or the user's clipboard; use `--no-clipboard` for bridge-only tests.
- Exercise real inference, restart the installer, reboot the live VM and repeat.
- Use `docs/test-cases/minimal-console.md` for installation and independent disk
  boot acceptance. Connecting the bridge alone is not installation acceptance.
- Browser login remains a separate integration scenario; bridge inference does
  not test OAuth browser redirects or the guest browser.

Errors deliberately omit raw backend/provider output. A bridge startup failure
is reported in `vm/<scenario>/bridge.log`; it contains no dialogue or credentials.
