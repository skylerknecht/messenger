# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.2] - 2026-07-31

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Fixed

- Forwarder client writers are now properly cleaned up on all close paths — `send_data(b'')`, failed SOCKS negotiation, denied connection replies, and `LocalForwarderClient.initiate_forwarder_client` exceptions all route through `_cleanup()`
- `RemotePortForwarder` now has a `stop()` method — previously stopping a remote forwarder only removed it from the list, leaking open connections and stream tasks
- Manager `stop` dispatcher now calls `stop()` on all forwarder types, not just `LocalPortForwarder`
- Connection-denied handling moved into forwarder clients — `SocksForwarderClient` now sends the proper SOCKS5 error reply before closing instead of aborting the transport with no reply
- `alphanumeric_identifier` now correctly indexes the full alphanumeric list — digits 0-9 were never selected due to using `len(alphabet)` instead of `len(alphanumeric)`
- `_parse_port_ranges` validates input instead of crashing on malformed entries like `80-http` or `1-2-3`
- `_parse_ip_ranges` rewritten to handle hyphenated hostnames using `rpartition`
- `interact` no longer prints a false "Could not find Messenger" error on a successful match
- Scanner `handle_initiate_forwarder_client_rep` only releases the semaphore and updates results for its own scan identifiers, not every reply
- Scanner now sends a close signal for successful scan connections so remote forwarder clients get cleaned up
- Scanner `stop()` now sets `end_time` so runtime doesn't count indefinitely
- Reconnect detection in `messengers.py` now fires correctly — `last_check_in` is checked before being updated
- SOCKS negotiation uses `readexactly` instead of `read` to prevent partial reads on slow or fragmented connections
- `writer.write()` calls are now followed by `await writer.drain()` for proper backpressure
- WebSocket handler validates the first received message is `BINARY` before accessing `msg.data`, preventing crashes on CLOSE/ERROR frames
- WebSocket reconnection rejects messengers that aren't `WebSocketMessenger` instead of crashing with `AttributeError`
- `SocksProxy.handle_client` appends the client before calling `initiate_forwarder_client` so failed negotiations still get cleaned up
- SOCKS reply write is wrapped in try/except to handle clients that disconnect during the handshake
- Encryption key generation now uses the `secrets` module instead of `random`
- `LocalPortForwarder.stop()` no longer crashes when `start()` failed and `self.server` is `None`
- `WebSocketMessenger.send_message_upstream` catches `send_bytes` failures and falls back to queuing the message
- Bind error handling now uses `errno.EADDRINUSE` and `errno.EADDRNOTAVAIL` instead of hardcoded Linux values 98/99
- Redundant `request.read()` in `redirect_handler` removed — body was read for debug logging then re-read in `http_post_handler`
- Engine, forwarder clients, and WebSocket server wrap critical paths in try/except so a single malformed message doesn't kill the session
- Malformed or undecryptable message frames now stop parsing instead of propagating an exception
- `get_messenger_id` returns `None` instead of asserting on non-CheckIn messages
- HTTP and WebSocket handlers guard against empty or unidentifiable check-ins instead of crashing
- Fixed `MANIFEST.in` typo

### Changed

- `_cleanup()` accepts an `abort` parameter for forced teardown vs graceful close
- `scanner.handle_initiate_forwarder_client_rep` is now async
- Cleaned up redundant `__init__` assignments in `Scanner`
- Python client submodule bumped

## [0.4.1] - 2026-07-26

### Fixed

- HTTP and WebSocket-based clients no longer require using `/socketio/?EIO=4&transport=websocket`

## [0.4.0] - 2026-07-26

### Added

- New standalone `messenger-builder` executable with per-language subcommands (auto-discovered from `builder/clients/*/builder.py`) and an `update-clients` subcommand that runs `git submodule sync/update/foreach`.
- `builder/` package for build tooling; `builder.clients.*` submodules for Python, C#, and Node.js clients.
- New Node.js client submodule (`builder/clients/nodejs`).
- `pycryptodome` and `jinja2` added to `requirements.txt` / `setup.py` `install_requires`.
- `MAINFEST.in` (sic) to package `builder/clients` resources.
- New docs: `docs/communication.md` (rewritten protocol spec), `docs/chaining-messengers.md`, `docs/local-port-forwards-and-socks.md`, `docs/remote-port-forwards.md`, `docs/testing.md`.
- `messenger/text.py` module exposing shared `color_text` / `bold_text` helpers.
- Status message when `interact` cannot find a matching messenger ID.
- Handler-level debug messages moved to the generic `redirect_handler` so both HTTP and WS transports emit them.

### Changed

- `messenger/aes.py` replaced its ~260-line pure-Python AES implementation with a thin wrapper around `pycryptodome`'s `Crypto.Cipher.AES`.
- Client submodules moved from `messenger/clients/` to `builder/clients/` (paths updated in `.gitmodules`).
- `build` command removed from the interactive CLI; client building is now handled exclusively by the `messenger-builder` binary.
- `setup.py` now installs both `messenger-cli` and `messenger-builder` scripts and packages `builder/**` client resources.
- HTTP `web.Application` no longer sets `client_max_size=2GB`; aiohttp's default cap now applies.
- `LocalPortForwarder.handle_client` now closes the writer up in the forwarder when the remote replies with a non-zero reason (previously silently dropped in the client).
- `LocalForwarderClient` and `SocksForwarderClient` no longer check `rep != 0` themselves — the parent forwarder handles denial and always starts the stream on success.
- `SocksForwarderClient` renamed its constructor arg `cleanup` to `on_close` to match siblings.
- `LocalForwarderClient.send_data` now calls `writer.close()` on EOF instead of `writer.write_eof()`.
- `receive_data()` on forwarder clients renamed to `stream()`.
- Node.js client's supported protocol set changed (bundled-client bump).
- Multiple submodule bumps for Python, C#, and Node.js clients.
- `messengers.py`: various status-message tweaks and copy edits.
- README rewritten with new hyperlinks and doc layout.
- `docs/getting-started.md` and `docs/communications.md` removed; content moved to the new docs.
- `docs/operational-usage.md` renamed to `docs/ntlmrelay2self-with-messenger.md`.

### Fixed

- Remote port forward start message printed the forwarder identifier instead of the owning messenger identifier.
- Remote-forwarder denials now send an `InitiateForwarderClientRep` back to the client instead of silently dropping.
- Local port forwarder bug where denied client connections leaked; writer is now closed and awaited.
- `set_websocket` was returning/using an empty list of queued messages on reconnect.
- Duplicate ports in the port list (bundled-client top-ports resource dedup).
- Typo fix: `Captured unexpect error` → `Captured unexpected error`.
- Assorted README typos and hyperlinks.

### Removed

- Interactive `build` command from `messenger-cli` (superseded by `messenger-builder`).
- `messenger/clients/` package (moved to `builder/clients/`).
- `UpdateCLI.color_text` and `UpdateCLI.bold_text` static methods (relocated to `messenger/text.py`).
- Pure-Python AES fallback in `messenger/aes.py`.

## [0.3.6] - 2025-10-21

### Fixed

- WebSocket reconnection used a nonexistent `update_cli.messages` attribute and never actually flushed queued messages; `set_websocket` now drains via `get_upstream_messages()` and sends the properly serialized batch.

### Changed

- HTTP messenger status is now rendered as `Xms delay` / `Xs delay` / `Xm delay` / `Xh delay` instead of `Last Seen X seconds/minutes/hours ago`.
- WebSocket messenger status lowercased to `connected` / `disconnected`.
- Removed the HTTP messenger's `expiration()` background task (disconnection/reconnection is now inferred purely from `last_check_in` in the status property).

## [0.3.5] - 2025-10-21

### Added

- Unhandled exceptions in the CLI loop are now appended to `~/.messenger/exceptions.log` with a timestamp and traceback.
- When `debug_level != 0`, the full traceback is also printed to the console.
- CLI directs the user to file a GitHub issue on unexpected errors.
- New `messenger/forwarder_clients.py` module — forwarder-client classes (`ForwarderClient`, `LocalForwarderClient`, `RemoteForwarderClient`, `SocksForwarderClient`) split out of `forwarders.py`.
- Server queues upstream messages for a messenger even when it is not marked alive (removed the `if not messenger.alive` guard in `local` and other command paths).

### Changed

- Large refactor of `messenger/forwarders.py` (~300 lines removed) around the new `forwarder_clients` split.
- Messenger table column renamed from `Alive` (Yes/No) to `Status` (uses each messenger's `status` property).
- Various messenger status-message copy tweaks.

## [0.3.4] - 2025-08-08

### Fixed

- `execute_command` counted required parameters wrong when a flag was passed before positional arguments — positional args were being counted as keyword args. Now consumed flags are excluded from the required-param count.

## [0.3.3] - 2025-08-08

### Fixed

- `RemoteForwarderClient.initiate_forwarder_client` never scheduled `receive_data()`, so remote port forwards accepted connections but never streamed data.

## [0.3.2] - 2025-08-08

### Added

- `--update-submodules` flag on `messenger-cli` that runs `git submodule sync/update/foreach` before starting the CLI (this is a CLI flag, not a REPL command).
- `include_package_data=True` and `package_data={'messenger': ['resources/*']}` in `setup.py` so `top_ports.txt` ships with `pip`/`pipx` installs.
- `build python` now degrades gracefully when the Python client submodule is not present, pointing the user at `--update-submodules`.

### Changed

- Scanner listing/detail branches in `print_scanners` swapped — `scans` (no identifier) now shows the summary table, `scans <identifier>` shows per-port results. Closed and pending results hidden unless `--verbose`.
- Help/example text for `local`, `remote`, and `socks` clarified (`listening_port`, `destination_port` wording; `socks 9050` default).
- Node.js client hyperlink added to the README.
- Client submodule pointer bumps (`messenger/clients/csharp`, `messenger/clients/python`).

### Fixed

- `top-ports` resource was not accessible after install because `package_data` was not configured.

## [0.3.1] - 2025-08-01

### Fixed

- Race condition where a `LocalForwarderClient` could try to write data upstream before the remote peer had confirmed the connection.

## [0.3.0] - 2025-08-01

### Added

- `portscan` command (in-CLI TCP port scanner) with a new `messenger/scanner.py` module, `--concurrency` control on both scans and per-worker concurrency, and configurable worker count.
- `scans` command listing active/completed scanners and their progress (`Runtime`, `Attempts`, `Progress`, `Open`, `Closed`).
- `stop` command extended to also stop in-progress scanners in addition to forwarders.
- `debug` command with numeric debug levels (0–6): handler messages, messenger messages, forwarder-client messages, and raw data at each layer. Debug icon renders as `[DBG N]`.
- `build` command in the CLI (`build python` initially wired up via `messenger.clients.python.builder`). C# and node_js accepted as arguments but marked "not implemented".
- Flag/keyword-argument support in `execute_command` — commands can now be invoked with `--name value` / `--flag` in addition to positional args.
- `messenger/scanner.py`, `messenger/resources/top_ports.txt` (8344 ports), `docs/getting-started.md`, `docs/operational-usage.md`.
- New git submodules for bundled clients: `messenger/clients/python` and `messenger/clients/csharp`.

### Changed

- Renamed the `messenger-server` entry-point script to `messenger-cli`; `messenger-client` script removed.
- `setup.py` now ships only `messenger-cli` (client is a submodule now).
- Reworked reconnection procedure for messengers.
- Various status-message / help-menu / error-message rewording across the manager.
- WebSocket handler in `http_ws_server.py` updated for how it processes new messengers.
- Detailed scan results table with runtime/attempts/progress columns.

### Fixed

- SOCKS5 compatibility issues (bundled Python-client bumps and manager-side handling).
- Scanner was iterating dict keys instead of values (`bug where scanner didnt access the values and only the keys`).
- Scanner workers were pegging the CPU.
- SOCKS5 `atype == 0` handling in the Python client (submodule pull).
- Invalid concurrency numbers now produce a clear error instead of crashing.

## [0.2.5] - 2025-04-10

### Fixed

- Messengers could not reconnect — when `get_upstream_messages()` was called on a messenger with `alive == False`, `alive` is now flipped to True and a "reconnected" status is emitted (previously the reconnection status update never fired).

### Changed

- Default server bind address changed from `127.0.0.1` to `0.0.0.0`, default port from `1337` to `8080` in `messenger-server`.
- Added short-form flags (`-a`, `-p`, `-s`, `-e`) to `messenger-server` arguments.
- Status message rewording: identifiers now wrapped in backticks; "is now available" → "is now connected."

## [0.2.4] - 2025-03-23

### Added

- New `messenger/engine.py` "engine" module abstracting shared client/server message handling; both client and server rewritten around it.
- New `messenger/http_ws_server.py` splitting the HTTP+WebSocket transport out of the old `server.py`.
- `interact` command (select a target messenger once, then run per-messenger commands without re-specifying the ID); `back` command to return to the main menu.
- Verbose flag (`--verbose`) on listing commands with proxy support in the client.
- `--encryption-key` CLI flag on the server.
- Sent/received byte counters on messengers, formatted in the messengers table.
- Bold-text helper (`UpdateCLI.bold_text`) — encryption key is bolded in banner output.
- "No messengers/forwarders to display" status messages for empty tables.

### Changed

- `messenger/server.py` deleted; transport code now lives in `http_ws_server.py`.
- `messenger-client` and `messenger-server` scripts substantially rewritten to use the new engine.
- Increased max request size for HTTP and WebSocket messengers (`client_max_size` bumped to 2GB in `http_ws_server.py`).
- Graceful shutdown handling added to the messenger client.
- Reordered `External IP` and `User-Agent` columns in verbose messenger output.
- Help menu descriptions rewritten across commands.
- Additional error handling in the messenger client.

### Fixed

- Messenger client no longer errors when passed a non-URL server URL.
- WebSocket messengers were never being marked dead — now correctly transition when the socket closes.
- Sent/received byte counts were off; expanded floating-point precision and corrected byte formatting.
- Format-string compatibility for older Python versions.
- "No messengers connected" message printed even when messengers were present.
- Attempts logic in the messenger client.

## [0.2.3] - 2024-11-11

### Added

- Outbound proxy support in the messenger client.
- AES-CBC encryption for HTTP and WebSocket transports — new `messenger/aes.py` (pure-Python AES fallback with optional `pycryptodome` fast path) and `messenger/generator.py` (encryption key generation and key hashing).
- Reconnection ability for HTTP messengers (server-side identifier reuse).

### Changed

- Messenger identifier scheme reworked (uses short hashed IDs instead of full UUIDs).
- README substantially expanded.

## [0.2.2] - 2024-11-10

### Added

- ANSI terminal colors in CLI output (`UpdateCLI.color_text`, colored status icons).

### Changed

- Renamed "Local Forwarders" to "Local Port Forwarders" (nomenclature update in commands and messages).
- Command docstrings expanded/clarified across the manager.
- Formatting and unused-import cleanup across `manager.py`, `forwarders.py`, `messengers.py`.

### Fixed

- Sending to a messenger that was no longer alive now short-circuits.
- Sending data from forwarder clients that no longer exist now short-circuits.

## [0.2.1] - 2024-11-06

### Changed

- Dependencies updated in both `requirements.txt` and `setup.py`.

### Fixed

- `WebSocketClient` was not starting (minor bug in the client script).

## [0.2.0] - 2024-11-06

### Added

- Remote port forwards — new `RemoteForwarder` class in `forwarders.py`, plus client-side `RemoteForwarder` streaming.
- Local port forwards (`LocalForwarderClient`, `ForwarderClient` base class) reworked from the earlier SOCKS-only model.
- `Manager` class (`messenger/manager.py`) replacing the old `MessengerCLI`, with a real command dispatch table (`exit`, `forwarders`, `messengers`, `local`, `remote`, `stop`, `help`) and prompt-toolkit-based interactive prompt with tab completion.
- Structured message protocol: new `messenger/message.py` (`MessageBuilder` / `MessageParser`) with typed message frames (Initiate Forwarder Client Req/Rep, Send Data, Check In).
- `messenger/messengers.py` with `HTTPMessenger` / `WebSocketMessenger` abstractions.
- Custom User-Agent (Firefox 128 on macOS) in the client.
- `docs/communications.md` documenting the wire protocol.
- Server strips the `Server` HTTP response header (started in 0.1.2, kept here).
- `debug` documentation in the README (note: an actual `debug` command in the CLI does not appear until 0.3.0 — 0.2.0 only ships the debug status level in `UpdateCLI`).

### Changed

- Communications specification rewritten around length-prefixed typed messages.
- `messenger/cli.py` deleted; replaced by `messenger/manager.py`.
- `messenger/socks.py` deleted; SOCKS behavior moved into `forwarders.py`.
- `messenger-server` script now instantiates `Manager` instead of `MessengerServer` + `MessengerCLI`.
- Removed the `--buffer_size` argument on `messenger-server` (hardcoded to 4096 in code paths now).
- README extensively updated.

## [0.1.2] - 2024-05-23

### Added

- `-q` / `--quiet` flag on `messenger-server` to suppress the banner.
- SOCKS5 version check in `messenger/socks.py` — a friendly "SOCKSN is not supported" message is emitted for non-v5 clients.
- Server response now strips the `Server` header via `on_response_prepare` (reduced fingerprinting).

### Changed

- `setup.py`: dropped the `console_scripts` entry point; now installs `messenger-server` and `messenger-client` as top-level scripts. `messenger.py` and `messenger/__main__.py` removed; startup lives in the new `messenger-server` script.
- `messenger/__init__.py` slimmed down to just `__version__` and `BANNER` (main loop moved into `messenger-server`).
- `examples/client.py` promoted/renamed to top-level `messenger-client` script.

### Fixed

- README typos and inaccuracies.

## [0.1.1] - 2024-05-22

### Changed

- `MessengerCLI` now checks `socks_server.is_stopped()` instead of the `socks_server.socks_server` attribute to determine whether the SOCKS server is listening.
- `MessengerCLI` dropped unused `atexit` / `os` / `readline` imports.
- README installation section added (pipx quick-start).

## [0.1.0] - 2024-05-19

Initial tagged release. Aggregates 29 pre-tag commits; below is a snapshot of the feature set at 89ab9dc.

### Added

- Client–server SOCKS5 tunneling framework (Python) with both WebSocket and HTTP transports served by a single `aiohttp` app on `/socketio/?EIO=4&transport=…`.
- `MessengerServer` (`messenger/server.py`) with dynamic per-transport `SocksServer` instances and configurable SOCKS5 port range.
- SOCKS5 negotiator (`messenger/socks.py`) — auth negotiation, CONNECT request handling, address-type support, streaming to/from remote hosts.
- Automatic fallback from WebSocket to HTTP when WS fails.
- Example client at `examples/client.py`.
- Interactive CLI (`messenger/cli.py`) with `socks` and `exit` commands and a formatted `SOCKS SERVERS` table.
- `argparse` entry point (`messenger/__main__.py` / `messenger.py`) exposing `--address`, `--port`, `--ssl CERT KEY`, `--buffer_size`.
- Banner, verbose logging via `messenger/output.py`, JSON deserialization helper (`messenger/convert.py`).
- Client and SOCKS-server cleanup on disconnect; auto-stop of the SOCKS server when the WS connection closes.
- Kevin credited in the banner.
- BSD-3-Clause `LICENSE`, `README.md`, `requirements.txt`, `setup.py` (with `console_scripts` `messenger` entry point).

### Fixed

- Closed ports no longer prevent further clients from being processed (`b24b1c6`).
- `is_stopped` returned the wrong result on the `SocksServer` (`74f31d8`).
- HTTP client was sending too much data at a time.
- Non-URL server URLs are handled via `urllib.parse.urlparse` (layer-8 tolerance).
- Older-Python compatibility: tuple subscript syntax removed.
```
